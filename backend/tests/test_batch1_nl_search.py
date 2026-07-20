"""第①批 T-C1 NL 检索 + 鉴权加固（逻辑层）测试.

覆盖：
- NlQueryGuard.validate：白名单字段通过；拒绝非白名单字段 / DDL / 写操作 / 超行数 / 注释注入。
- NlQueryGuard.compile：空文本返回默认意图；LLM 返回合法 JSON → 解析意图；LLM 降级 → 关键字安全回退。
- nl_log_search：正常路径（mock LLM）返回脱敏行 + 摘要 + 写审计(masked=1)；
  LLM 不可用 → 仍返回脱敏行 + 空摘要 + 不抛 500；非法意图（DDL）→ 写 rejected 审计并抛 ValueError。
- NlQueryAudit 模型 CRUD。

安全红线：全部使用临时隔离 SQLite（绝不触碰 backend/data/ir.db）；LLM 不可用路径必须覆盖且不能抛 500。
"""

import asyncio
import json
from unittest.mock import patch

from app.services.nl_query_guard import NlQueryGuard
from app.services.nl_log_search import nl_log_search
from app.models.nl_query_audit import NlQueryAudit
from app.models.normalized_log import NormalizedLog

from _qa_batch1_common import IsolatedDBTestCase


# ───────────────────────── 可控 LLM 替身 ─────────────────────────
class FakeLLM:
    """依据 prompt 区分『编译意图』与『生成摘要』的 AgentLLM 替身（仅用于成功路径）。"""

    INTENT_MARKER = "请输出 JSON 查询意图"

    def __init__(self, degraded=False, intent=None, summary="这是自动生成的摘要文本"):
        self.degraded = degraded
        self.intent = intent or {
            "filters": [{"field": "severity", "op": "=", "value": "high"}],
            "time_range": {},
            "sort": "timestamp DESC",
            "page_size": 50,
            "summary_requested": True,
        }
        self.summary = summary

    async def call(self, prompt, user=None, budget=None):
        if self.INTENT_MARKER in (prompt or ""):
            if self.degraded:
                return {"content": "", "usage": {}, "degraded": True, "error": "degraded"}
            return {
                "content": json.dumps(self.intent, ensure_ascii=False),
                "usage": {"total_tokens": 10},
                "degraded": False,
                "error": None,
            }
        # 摘要请求
        if self.degraded:
            return {"content": "", "usage": {}, "degraded": True, "error": "degraded"}
        return {
            "content": self.summary,
            "usage": {"total_tokens": 5},
            "degraded": False,
            "error": None,
        }


# ───────────────────────── NlQueryGuard.validate ─────────────────────────
class TestNlQueryGuardValidate(IsolatedDBTestCase):
    def test_whitelist_field_passes(self):
        ok, err = NlQueryGuard().validate(
            {"filters": [{"field": "source_ip", "op": "contains", "value": "10.0.0.1"}]},
            nl_text="",
        )
        self.assertTrue(ok, err)

    def test_non_whitelist_field_rejected(self):
        ok, err = NlQueryGuard().validate(
            {"filters": [{"field": "password", "op": "=", "value": "x"}]},
            nl_text="",
        )
        self.assertFalse(ok)
        self.assertIn("白名单", err)

    def test_bad_op_rejected(self):
        ok, err = NlQueryGuard().validate(
            {"filters": [{"field": "severity", "op": "LIKE", "value": "x"}]},
            nl_text="",
        )
        self.assertFalse(ok)
        self.assertIn("操作符", err)

    def test_ddl_drop_rejected(self):
        ok, err = NlQueryGuard().validate({"filters": []}, nl_text="DROP TABLE users")
        self.assertFalse(ok)
        self.assertIn("DDL", err)

    def test_write_delete_rejected(self):
        ok, err = NlQueryGuard().validate({"filters": []}, nl_text="DELETE FROM logs")
        self.assertFalse(ok)
        self.assertIn("DDL", err)

    def test_alter_rejected(self):
        ok, err = NlQueryGuard().validate({"filters": []}, nl_text="ALTER TABLE x ADD y")
        self.assertFalse(ok)

    def test_comment_injection_rejected(self):
        ok, err = NlQueryGuard().validate({"filters": []}, nl_text="x; DROP TABLE y")
        self.assertFalse(ok)

    def test_oversized_page_size_rejected(self):
        ok, err = NlQueryGuard().validate({"filters": [], "page_size": 999}, nl_text="")
        self.assertFalse(ok)
        self.assertIn("上限", err)

    def test_exact_page_size_500_allowed(self):
        ok, err = NlQueryGuard().validate({"filters": [], "page_size": 500}, nl_text="")
        self.assertTrue(ok, err)


# ───────────────────────── NlQueryGuard.compile ─────────────────────────
class TestNlQueryGuardCompile(IsolatedDBTestCase):
    def test_empty_nltext_returns_default_intent(self):
        intent = asyncio.run(NlQueryGuard().compile(""))
        self.assertEqual(intent["filters"], [])
        self.assertFalse(intent["_llm_failed"])

    def test_llm_returns_valid_json_intent(self):
        intent_json = {
            "filters": [{"field": "severity", "op": "=", "value": "high"}],
            "time_range": {},
            "sort": "timestamp DESC",
            "page_size": 50,
            "summary_requested": True,
        }
        guard = NlQueryGuard(llm=FakeLLM(degraded=False, intent=intent_json))
        intent = asyncio.run(guard.compile("显示高危日志"))
        self.assertFalse(intent["_llm_failed"])
        self.assertEqual(intent["filters"][0]["field"], "severity")

    def test_llm_degraded_falls_back_to_keyword(self):
        guard = NlQueryGuard(llm=FakeLLM(degraded=True))
        intent = asyncio.run(guard.compile("用户登录失败"))
        self.assertTrue(intent["_llm_failed"])
        self.assertEqual(intent["filters"][0]["field"], "description")
        self.assertEqual(intent["filters"][0]["op"], "contains")
        self.assertEqual(intent["filters"][0]["value"], "用户登录失败")


# ───────────────────────── nl_log_search 主流程 ─────────────────────────
class TestNlLogSearch(IsolatedDBTestCase):
    def test_normal_path_returns_masked_rows_and_summary_and_audit(self):
        """正常路径（mock LLM）：返回脱敏行 + 摘要 + 写审计(masked=1)。"""
        self.seed_normalized_logs([
            {"description": "高危登录事件", "severity": "high",
             "source_ip": "10.0.0.5", "user_name": "alice"},
        ])
        with patch("app.services.nl_query_guard.AgentLLM", FakeLLM), \
                patch("app.services.nl_log_search.AgentLLM", FakeLLM):
            res = asyncio.run(nl_log_search("显示高危日志", user={"id": 5}))

        self.assertGreaterEqual(res["total"], 1)
        self.assertEqual(res["summary"], "这是自动生成的摘要文本")
        self.assertIsNotNone(res["audit_id"])
        # 脱敏生效：原始明文不应出现在结果中（IPv4 末两段掩码：10.0.0.5 -> 10.0.*.*）
        flat = json.dumps(res["rows"], ensure_ascii=False)
        self.assertNotIn("10.0.0.5", flat)
        self.assertNotIn("alice", flat)
        self.assertIn("10.0.*.*", flat)
        self.assertIn("a***e", flat)
        # 审计：ok + 已脱敏
        audit = NlQueryAudit.get_by_id(res["audit_id"])
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(audit["masked"], 1)
        self.assertEqual(audit["row_count"], res["total"])

    def test_llm_unavailable_returns_masked_rows_empty_summary_no_500(self):
        """LLM 不可用（无 Profile → 降级）：仍返回脱敏行 + 空摘要 + 不抛异常。"""
        self.seed_normalized_logs([
            {"description": "用户登录失败来自未知主机", "severity": "high",
             "source_ip": "10.0.0.9", "user_name": "bob"},
        ])
        # 不 patch：使用真实 AgentLLM（临时库无激活 Profile → 降级 → 关键字回退）
        res = asyncio.run(nl_log_search("登录失败", user={"id": 6}))
        self.assertGreaterEqual(res["total"], 1)
        # 降级时摘要为空（不抛 500）
        self.assertEqual(res["summary"], "")
        self.assertIsNotNone(res["audit_id"])
        audit = NlQueryAudit.get_by_id(res["audit_id"])
        self.assertEqual(audit["status"], "ok")
        self.assertEqual(audit["masked"], 1)
        # 脱敏仍然生效
        flat = json.dumps(res["rows"], ensure_ascii=False)
        self.assertNotIn("10.0.0.9", flat)

    def test_illegal_intent_writes_rejected_audit_and_raises(self):
        """非法意图（含 DDL 关键字）：写 rejected 审计并抛 ValueError（不写 ok 审计）。"""
        self.seed_normalized_logs([
            {"description": "普通日志", "severity": "low"},
        ])
        with self.assertRaises(ValueError):
            asyncio.run(nl_log_search("DROP TABLE users", user={"id": 7}))
        rejected = NlQueryAudit.list_all(status="rejected")["items"]
        self.assertEqual(len(rejected), 1)
        self.assertIn("DDL", rejected[0]["error_message"] or "")
        # 不应写入 ok 审计
        self.assertEqual(NlQueryAudit.list_all(status="ok")["total"], 0)


# ───────────────────────── NlQueryAudit 模型 CRUD ─────────────────────────
class TestNlQueryAuditModel(IsolatedDBTestCase):
    def test_create_and_get(self):
        aid = NlQueryAudit.create(
            user_id=11, nl_text="测试",
            intent_json={"filters": []}, row_count=3, masked=1, status="ok",
        )
        self.assertIsInstance(aid, int)
        rec = NlQueryAudit.get_by_id(aid)
        self.assertEqual(rec["user_id"], 11)
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["masked"], 1)

    def test_list_filter_by_status(self):
        NlQueryAudit.create(user_id=12, nl_text="a", status="ok")
        NlQueryAudit.create(user_id=12, nl_text="b", status="rejected", error_message="x")
        self.assertEqual(NlQueryAudit.list_all(status="ok")["total"], 1)
        self.assertEqual(NlQueryAudit.list_all(status="rejected")["total"], 1)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
