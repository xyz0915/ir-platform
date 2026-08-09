"""智能体闭环「LLM 服务不可用」横幅修复 — 回归测试（T-A ~ T-H）.

对应设计文档：``deliverables/software-company/agent-orchestration-fix/design.md`` §6.1 测试矩阵。
对应用例文档：``deliverables/software-company/agent-orchestration-fix/test-cases.md``。

覆盖：
- T-A   P0-1 ``import json`` — trace_id 非空路径不得抛 NameError（**合入门禁**）。
- T-C1  P1-2 空 content 必须记 failed，不得伪装 success。
- T-C2  P1-6 HTTP 200 但包体含 error 必须记 failed。
- T-C3  P1-6 五级兜底解析链全部命中。
- T-D   P1-4/P1-5 四个 agent 正常轮无横幅 / 降级轮横幅带真实 reason。
- T-E   P0-1 连带 — resume 携 trace_id 收尾不崩。
- T-E2  P0-1 连带 — root_cause_agent 静默点恢复。
- T-F-unit P2-13 ``degraded_reason`` 经 to_dict/from_dict 往返透传。
- T-G   P2-9 断路器按 bucket 分桶隔离。
- T-H   P2-14 ``get_active()`` 确定性排序。

测试底座：复用 ``_qa_batch1_common.IsolatedDBTestCase``（每个测试方法一个全新临时
SQLite，绝不触碰 ``backend/data/ir.db``）。所有 LLM 交互均以 ``AsyncMock`` 打桩，
不发起任何真实网络请求。
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

# 确保 backend 与 tests 目录均在 sys.path（兼容 pytest / python 直接运行）
_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.database import get_connection
from app.models.ai_audit_log import AiAuditLog
from app.models.ai_config import AiConfigProfile
from app.models.agent_run import AgentRun, AgentRunStep
from app.services.agent_llm import AgentLLM
from app.services.agents.base_agent import AgentResult
from app.services.agents.orchestrator import Orchestrator
from app.services.agents.triage_agent import TriageAgent
from app.services.agents.investigator_agent import InvestigatorAgent
from app.services.agents.responder_agent import ResponderAgent
from app.services.agents.reporter_agent import ReporterAgent
from app.services.agents.root_cause_agent import RootCauseAgent
from app.services.ai_service import AiService

from _qa_batch1_common import IsolatedDBTestCase


# ───────────────────────── 公共夹具 ─────────────────────────
class _FakeProfile:
    """构造一个"已配置"的 Profile 字典（api_key 用明文，decrypt 被打桩）。

    与 ``test_batch1_agents_base._FakeProfile`` 保持同构，便于对照。
    """

    def __init__(self, pid: int = 1):
        self.data = {
            "id": pid,
            "profile_name": "qa_profile",
            "api_key": "enc-key",
            "api_base_url": "http://llm.local/v1",
            "model_name": "gpt-4o",
            "max_tokens": 4096,
            "temperature": 0.3,
            "system_prompt": "sys",
        }


def _ok_resp(content: str = "HELLO") -> dict:
    """标准 OpenAI 兼容成功响应。"""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _call_llm(profile: dict, mock_return=None, mock_side_effect=None, **call_kwargs):
    """在打桩 AiService 的前提下调用 ``AgentLLM.call``，返回其结果。"""
    mock = AsyncMock(return_value=mock_return) if mock_side_effect is None \
        else AsyncMock(side_effect=mock_side_effect)
    with patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
            patch("app.services.ai_service.AiService.call_llm", new=mock):
        return asyncio.run(AgentLLM(profile=profile).call(**call_kwargs))


def seed_full_incident() -> dict:
    """写入 case → host → security_events → normalized_logs → process_events → rule。

    与 ``test_batch2_agents.seed_full_incident`` 同构，供 T-D / T-E2 使用。
    """
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
        case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
            "VALUES (?, 'QAHOST', '10.0.0.7', 'Windows')",
            (case_id,),
        )
        host_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO security_events "
            "(id, timestamp, host_id, event_type, event_key, severity, ai_verdict) "
            "VALUES (?, '2026-07-18 10:00:00', ?, 'malware', 'ek1', 'critical', ?)",
            ("SE-1", host_id, json.dumps({"label": "suspicious", "reason": "beacon"})),
        )
        conn.execute(
            "INSERT INTO normalized_logs "
            "(host_id, log_source, event_type, event_label, severity, timestamp, "
            "source_ip, process_name, command_line) "
            "VALUES (?, 'test', 'network', 'outbound', 'high', '2026-07-18 10:00:01', "
            "'8.8.8.8', 'powershell.exe', 'IWR http://8.8.8.8/x')",
            (host_id,),
        )
        conn.execute(
            "INSERT INTO process_events "
            "(host_id, event_type, pid, ppid, process_name, process_path, "
            "command_line, parent_name, start_time) "
            "VALUES (?, 'process_start', 101, 1, 'evil.exe', 'C:\\\\tmp\\\\evil.exe', "
            "'evil.exe --c2', 'cmd.exe', '2026-07-18 09:59:00')",
            (host_id,),
        )
    return {"host_id": host_id, "event_id": "SE-1"}


# ═════════════════════ T-A：P0-1 合入门禁 ═════════════════════
class TestA_TraceIdNonEmpty(IsolatedDBTestCase):
    """T-A（P0 合入门禁）：trace_id 非空时 ``json.dumps`` 不得抛 NameError。

    修复前实测：``NameError: name 'json' is not defined``（agent_llm.py:175）。
    """

    def test_A_trace_id_non_empty_must_not_raise(self):
        """trace_id="abc123" → 不抛异常、degraded=False、content=="HELLO"。"""
        profile = _FakeProfile().data
        res = _call_llm(
            profile, mock_return=_ok_resp("HELLO"),
            prompt="x", user={"id": 1}, trace_id="abc123",
        )
        # ① 未抛异常（能执行到此行即证明）；② degraded=False；③ content 正确
        self.assertIs(res["degraded"], False)
        self.assertEqual(res["content"], "HELLO")
        self.assertIsNone(res["error"])

    def test_A2_trace_id_emits_parsable_structured_log(self):
        """trace_id 路径产出的日志可被 json.loads 解析，且含 event/trace_id。"""
        profile = _FakeProfile().data
        with self.assertLogs("app.services.agent_llm", level=logging.INFO) as cm:
            res = _call_llm(
                profile, mock_return=_ok_resp("HELLO"),
                prompt="x", user={"id": 1}, trace_id="abc123",
            )
        self.assertIs(res["degraded"], False)
        hit = None
        for line in cm.output:
            payload = line.split(":", 2)[-1]
            try:
                obj = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict) and obj.get("event") == "llm_call":
                hit = obj
                break
        self.assertIsNotNone(hit, f"未找到可解析的 llm_call 结构化日志：{cm.output}")
        self.assertEqual(hit["trace_id"], "abc123")

    def test_A3_trace_id_none_still_works(self):
        """对照组：trace_id=None（custom 路径）同样成功，证明差异只在 trace_id 分支。"""
        profile = _FakeProfile().data
        res = _call_llm(
            profile, mock_return=_ok_resp("HELLO"),
            prompt="x", user={"id": 1}, trace_id=None,
        )
        self.assertIs(res["degraded"], False)
        self.assertEqual(res["content"], "HELLO")


# ═════════════════════ T-C：P1-2 / P1-6 ═════════════════════
class TestC1_EmptyContentMustFail(IsolatedDBTestCase):
    """T-C1（P1-2）：空 content 必须判为 failed，不得伪装成 success。"""

    def test_C1_empty_content_must_be_failed(self):
        profile = _FakeProfile().data
        res = _call_llm(
            profile, mock_return={"choices": [{"message": {"content": ""}}]},
            prompt="x", user={"id": 5}, trace_id="t-c1",
        )
        self.assertIs(res["degraded"], True)
        self.assertEqual(res["error"], "AI 服务返回空内容")
        # 审计恰 1 条且为 failed
        self.assertEqual(AiAuditLog.list_all()["total"], 1)
        item = AiAuditLog.list_all()["items"][0]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["error_message"], "AI 服务返回空内容")
        self.assertEqual(item["user_id"], 5)
        # 无任何 success 记录（修复前此处会有 1 条伪 success）
        self.assertEqual(AiAuditLog.list_all(status="success")["total"], 0)


class TestC2_GatewayErrorMustFail(IsolatedDBTestCase):
    """T-C2（P1-6）：HTTP 200 但包体含 error 必须判为 failed。"""

    def test_C2_http200_with_error_body_must_be_failed(self):
        profile = _FakeProfile().data
        res = _call_llm(
            profile, mock_return={"error": {"message": "model not found"}},
            prompt="x", user={"id": 6}, trace_id="t-c2",
        )
        self.assertIs(res["degraded"], True)
        self.assertIn("model not found", res["error"])
        failed = AiAuditLog.list_all(status="failed")["items"]
        self.assertEqual(len(failed), 1)
        self.assertIn("model not found", failed[0]["error_message"])
        self.assertEqual(AiAuditLog.list_all(status="success")["total"], 0)

    def test_C2b_error_as_plain_string(self):
        """error 为裸字符串（非 dict）时同样判 failed。"""
        profile = _FakeProfile().data
        res = _call_llm(
            profile, mock_return={"error": "rate limited"},
            prompt="x", user={"id": 6}, trace_id="t-c2b",
        )
        self.assertIs(res["degraded"], True)
        self.assertIn("rate limited", res["error"])


class TestC3_ContentFallbackChain(IsolatedDBTestCase):
    """T-C3（P1-6）：五级兜底解析链逐一命中。"""

    CASES = [
        ("message.content",
         {"choices": [{"message": {"content": "V1"}}]}, "V1"),
        ("message.reasoning_content",
         {"choices": [{"message": {"reasoning_content": "V2"}}]}, "V2"),
        ("delta.content",
         {"choices": [{"delta": {"content": "V3"}}]}, "V3"),
        ("choices[0].text",
         {"choices": [{"text": "V4"}]}, "V4"),
        ("output_text",
         {"output_text": "V5"}, "V5"),
    ]

    def test_C3_all_five_structures_parse_successfully(self):
        profile = _FakeProfile().data
        for path, resp, expected in self.CASES:
            with self.subTest(parse_path=path):
                res = _call_llm(
                    profile, mock_return=resp,
                    prompt="x", user={"id": 8}, trace_id="t-c3",
                )
                self.assertIs(res["degraded"], False,
                              f"{path} 解析失败：{res.get('error')}")
                self.assertEqual(res["content"], expected)

    def test_C3b_non_primary_path_logs_warning(self):
        """命中非首选路径时须 WARNING 记录 parse_path，便于统计网关分布。"""
        profile = _FakeProfile().data
        with self.assertLogs("app.services.agent_llm", level=logging.WARNING) as cm:
            res = _call_llm(
                profile, mock_return={"choices": [{"text": "V4"}]},
                prompt="x", user={"id": 8}, trace_id="t-c3b",
            )
        self.assertIs(res["degraded"], False)
        self.assertTrue(any("兜底解析路径" in line for line in cm.output),
                        f"未记录兜底解析路径：{cm.output}")

    def test_C3c_all_paths_miss_returns_failed(self):
        """五级全未命中（如 content 为 list-of-parts，设计 §5 R-4）→ 记 failed。"""
        profile = _FakeProfile().data
        res = _call_llm(
            profile,
            mock_return={"choices": [{"message": {"content": [{"type": "text"}]}}]},
            prompt="x", user={"id": 8}, trace_id="t-c3c",
        )
        self.assertIs(res["degraded"], True)
        self.assertEqual(res["error"], "AI 服务返回空内容")


# ═════════════════════ T-D：P1-4 / P1-5 四个 agent ═════════════════════
_NEW_BANNER = "AI 摘要未生成（原因："
_OLD_BANNER = "当前 LLM 服务不可用"
_PLACEHOLDER = "{reason}"


class TestD_AgentsDegradedBanner(IsolatedDBTestCase):
    """T-D（P1-4 / P1-5）：四个 agent 正常轮无横幅、降级轮横幅带真实 reason。"""

    # ── 正常轮 ──
    def _assert_normal(self, result):
        self.assertNotIn("AI 摘要未生成", result.output)
        self.assertNotIn(_OLD_BANNER, result.output)
        self.assertIsNone(result.error)
        self.assertIsNone(result.degraded_reason)

    # ── 降级轮 ──
    def _assert_degraded(self, result, agent_name: str):
        self.assertIn(_NEW_BANNER, result.output,
                      f"{agent_name} 未使用新横幅文案")
        self.assertNotIn(_PLACEHOLDER, result.output,
                         f"{agent_name} 泄漏了 {{reason}} 字面量（设计 §5 R-3）")
        self.assertNotIn(_OLD_BANNER, result.output,
                         f"{agent_name} 仍在使用旧文案")
        self.assertTrue(result.error, f"{agent_name} 未透出 AgentResult.error")
        self.assertTrue(result.degraded_reason,
                        f"{agent_name} 未透出 degraded_reason")
        self.assertIn("断路器已熔断", result.degraded_reason)

    # ── Triage ──
    def test_D1_triage_normal_round_has_no_banner(self):
        seed_full_incident()
        ctx = {"event_id": "SE-1", "user": {"id": 1}, "trace_id": "tid-d1"}
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(return_value={"content": "LLM 研判：高危外连",
                                               "usage": {}, "degraded": False,
                                               "error": None})):
            result = asyncio.run(TriageAgent().run(ctx, {"event_id": "SE-1"}))
        self._assert_normal(result)

    def test_D1_triage_degraded_round_banner_carries_reason(self):
        seed_full_incident()
        ctx = {"event_id": "SE-1", "user": {"id": 1}, "trace_id": "tid-d1"}
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(side_effect=RuntimeError("断路器已熔断"))):
            result = asyncio.run(TriageAgent().run(ctx, {"event_id": "SE-1"}))
        self._assert_degraded(result, "TriageAgent")

    def test_D1b_triage_degraded_logs_with_traceback(self):
        """P1-4：降级日志级别必须是 ERROR 且含 traceback（logger.exception）。"""
        seed_full_incident()
        ctx = {"event_id": "SE-1", "user": {"id": 1}, "trace_id": "tid-d1b"}
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(side_effect=RuntimeError("断路器已熔断"))):
            with self.assertLogs("app.services.agents.triage_agent",
                                 level=logging.ERROR) as cm:
                asyncio.run(TriageAgent().run(ctx, {"event_id": "SE-1"}))
        joined = "\n".join(cm.output)
        self.assertIn("ERROR", joined)
        self.assertIn("Traceback", joined, "logger.exception 未带 traceback")

    # ── Investigator ──
    def test_D2_investigator_normal_round_has_no_banner(self):
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1}, "trace_id": "tid-d2"}
        with patch("app.services.agents.data_provider.retrieve_cases", return_value=[]), \
                patch("app.services.agent_llm.AgentLLM.call",
                      new=AsyncMock(return_value={"content": "调查结论", "usage": {},
                                                  "degraded": False, "error": None})):
            result = asyncio.run(InvestigatorAgent().run(ctx, {}))
        self._assert_normal(result)

    def test_D2_investigator_degraded_round_banner_carries_reason(self):
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1}, "trace_id": "tid-d2"}
        with patch("app.services.agents.data_provider.retrieve_cases", return_value=[]), \
                patch("app.services.agent_llm.AgentLLM.call",
                      new=AsyncMock(side_effect=RuntimeError("断路器已熔断"))):
            result = asyncio.run(InvestigatorAgent().run(ctx, {}))
        self._assert_degraded(result, "InvestigatorAgent")

    # ── Responder ──
    def test_D3_responder_normal_round_has_no_banner(self):
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1}, "trace_id": "tid-d3",
               "investigation": {"summary": "x", "evidence": []},
               "triage": {"confidence": 0.8}}
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(return_value={"content": "处置建议", "usage": {},
                                               "degraded": False, "error": None})):
            result = asyncio.run(ResponderAgent().run(ctx, {}))
        self._assert_normal(result)

    def test_D3_responder_degraded_round_banner_carries_reason(self):
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1}, "trace_id": "tid-d3",
               "investigation": {"summary": "x", "evidence": []},
               "triage": {"confidence": 0.8}}
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(side_effect=RuntimeError("断路器已熔断"))):
            result = asyncio.run(ResponderAgent().run(ctx, {}))
        self._assert_degraded(result, "ResponderAgent")

    # ── Reporter ──
    def test_D4_reporter_normal_round_has_no_banner(self):
        ctx = {"trigage": {}, "user": {"id": 1}, "trace_id": "tid-d4"}
        task = {"run_id": "run_d4a", "hitl_decision": {}}
        with patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                   new=MagicMock()), \
                patch("app.services.agent_llm.AgentLLM.call",
                      new=AsyncMock(return_value={"content": "复盘报告", "usage": {},
                                                  "degraded": False, "error": None})):
            result = asyncio.run(ReporterAgent().run(ctx, task))
        self._assert_normal(result)

    def test_D4_reporter_degraded_round_banner_carries_reason(self):
        ctx = {"user": {"id": 1}, "trace_id": "tid-d4"}
        task = {"run_id": "run_d4b", "hitl_decision": {}}
        with patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                   new=MagicMock()), \
                patch("app.services.agent_llm.AgentLLM.call",
                      new=AsyncMock(side_effect=RuntimeError("断路器已熔断"))):
            result = asyncio.run(ReporterAgent().run(ctx, task))
        self._assert_degraded(result, "ReporterAgent")

    # ── 横幅工厂函数本身 ──
    def test_D5_build_degraded_message_never_leaks_placeholder(self):
        """build_degraded_message 在 reason 为空/None 时也不得泄漏 {reason}。"""
        from app.shared.ai_constants import build_degraded_message

        for reason in (None, "", "   ", "真实原因"):
            with self.subTest(reason=reason):
                msg = build_degraded_message(reason)
                self.assertIn(_NEW_BANNER, msg)
                self.assertNotIn(_PLACEHOLDER, msg)
                self.assertNotIn(_OLD_BANNER, msg)


# ═════════════════════ T-E：resume 携 trace_id ═════════════════════
class TestE_ResumeWithTraceId(IsolatedDBTestCase):
    """T-E（P0-1 连带）：HITL 审批后 resume 收尾，ctx 中的 trace_id 必然非空。

    该路径**不在 diff 里**（orchestrator.py 零改动），但设计 §4.3 明确要求纳入测试。
    """

    def test_E_resume_with_trace_id_in_ctx_does_not_crash(self):
        run_id = "run_resume_trace"
        AgentRun.create(run_id=run_id, title="resume", user_id=1)
        # 模拟 orchestrator.py:254 持久化的 ctx（含 :384 注入的 trace_id）
        ctx = {"trace_id": "resume-trace-1", "mode": "hardcoded", "host_id": None}
        AgentRun.update(run_id, ctx_json=json.dumps(ctx, ensure_ascii=False))
        approval = {
            "status": "approved",
            "action": "export_report",
            "target_json": "{}",
            "reason": "ok",
        }
        with patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                   new=MagicMock()), \
                patch("app.services.action_service.ActionService.execute",
                      new=AsyncMock(return_value={"success": True, "action": "export_report",
                                                  "status": "completed", "result": {}})), \
                patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
                patch("app.services.ai_service.AiService.call_llm",
                      new=AsyncMock(return_value=_ok_resp("收尾报告正文"))), \
                patch("app.models.ai_config.AiConfigProfile.get_active",
                      return_value=_FakeProfile().data):
            out = asyncio.run(Orchestrator().resume(run_id, approval,
                                                    decided_by=2, user={"id": 2}))
        # ① 不抛异常；② status == completed
        self.assertEqual(out["status"], "completed")
        # ③ reporter 步骤不含降级横幅（LLM mock 成功）
        steps = AgentRunStep.list_by_run(run_id)
        report_steps = [s for s in steps if s.get("stage") == "report"]
        self.assertTrue(report_steps, "resume 未产出 report 步骤")
        raw = report_steps[-1]["output_json"]
        # AgentRunStep.list_by_run 已把 output_json 反序列化为 dict；兼容个别返回原始串的路径
        payload = raw if isinstance(raw, dict) else json.loads(raw)
        self.assertNotIn(_NEW_BANNER, payload["output"])
        self.assertNotIn(_OLD_BANNER, payload["output"])
        # ④ 审计出现 success 记录（证明 LLM 链路真正跑通）
        self.assertGreaterEqual(AiAuditLog.list_all(status="success")["total"], 1)

    def test_E2_finish_with_reporter_unit_trace_id_non_empty(self):
        """简化点：单元级验证 _finish_with_reporter 在 trace_id 非空时不抛 NameError。

        说明：本用例绕开 HITL 审批与动作执行，直接驱动收尾链路，
        用于在 resume 全链路夹具不可用时仍能守住 P0-1 的 resume 分支。
        """
        run_id = "run_finish_unit"
        AgentRun.create(run_id=run_id, title="finish", user_id=1)
        ctx = {"trace_id": "finish-trace-1", "mode": "hardcoded"}
        with patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                   new=MagicMock()), \
                patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
                patch("app.services.ai_service.AiService.call_llm",
                      new=AsyncMock(return_value=_ok_resp("收尾报告正文"))), \
                patch("app.models.ai_config.AiConfigProfile.get_active",
                      return_value=_FakeProfile().data):
            out = asyncio.run(
                Orchestrator()._finish_with_reporter(run_id, ctx, {"id": 2},
                                                     hitl_decision={"status": "approved"})
            )
        self.assertEqual(out["status"], "completed")
        self.assertNotIn(_OLD_BANNER, out["result"]["output"])
        self.assertNotIn(_NEW_BANNER, out["result"]["output"])


# ═════════════════════ T-E2：root_cause 静默点 ═════════════════════
class TestE2_RootCauseSilentPoint(IsolatedDBTestCase):
    """T-E2（P0-1 连带）：root_cause_agent 的 LLM 解释点恢复。"""

    def test_E2_llm_explanation_not_none_when_llm_succeeds(self):
        """ctx 带 trace_id + LLM mock 成功 → llm_explanation 必须非 None。

        修复前该点恒为 None（NameError 被 except 吞掉）。
        """
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1},
               "trace_id": "rc-trace-1"}
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(return_value={"content": "根因自然语言解释",
                                               "usage": {}, "degraded": False,
                                               "error": None})):
            detail = asyncio.run(RootCauseAgent().analyze(ctx=ctx, task={}))
        self.assertIsNotNone(
            detail.get("llm_explanation"),
            "root_cause_agent 的 llm_explanation 仍为 None —— 静默点未恢复",
        )
        self.assertEqual(detail["llm_explanation"], "根因自然语言解释")

    def test_E2b_failure_round_logs_at_error_level(self):
        """失败轮日志级别必须是 ERROR（原为 DEBUG，生产不可见）。"""
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1},
               "trace_id": "rc-trace-2"}
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(side_effect=RuntimeError("断路器已熔断"))):
            with self.assertLogs("app.services.agents.root_cause_agent",
                                 level=logging.ERROR) as cm:
                asyncio.run(RootCauseAgent().analyze(ctx=ctx, task={}))
        self.assertTrue(any("Traceback" in line for line in cm.output),
                        f"root_cause 失败轮未按 ERROR+traceback 记录：{cm.output}")


# ═════════════════════ T-F-unit：degraded_reason 往返 ═════════════════════
class TestFUnit_DegradedReasonRoundTrip(IsolatedDBTestCase):
    """T-F-unit（P2-13）：``degraded_reason`` 经 to_dict/from_dict 往返透传。

    完整端到端（API → Vue → useSSE 白名单 → el-alert）列为手工/集成验证项，
    见 test-cases.md T-F。
    """

    def test_F_unit_to_dict_contains_degraded_reason(self):
        r = AgentResult(stage="triage", output="o", degraded_reason="AI 服务返回空内容")
        d = r.to_dict()
        self.assertIn("degraded_reason", d)
        self.assertEqual(d["degraded_reason"], "AI 服务返回空内容")

    def test_F_unit_from_dict_roundtrip(self):
        r = AgentResult(stage="report", output="o", error="E",
                        degraded_reason="AI 服务返回错误: 404 not found")
        r2 = AgentResult.from_dict(r.to_dict())
        self.assertEqual(r2.degraded_reason, "AI 服务返回错误: 404 not found")
        self.assertEqual(r2.error, "E")

    def test_F_unit_legacy_output_json_without_field_is_none(self):
        """历史 output_json 无该字段 → from_dict 返回 None，不抛 KeyError（R-9）。"""
        legacy = {"stage": "triage", "output": "旧数据", "confidence": 0.5}
        r = AgentResult.from_dict(legacy)
        self.assertIsNone(r.degraded_reason)
        self.assertEqual(r.output, "旧数据")

    def test_F_unit_normal_path_degraded_reason_is_none(self):
        """正常路径 degraded_reason 为 None → 前端 v-if 不渲染 alert。"""
        r = AgentResult(stage="triage", output="正常摘要")
        self.assertIsNone(r.to_dict()["degraded_reason"])


# ═════════════════════ T-G：断路器分桶 ═════════════════════
class TestG_CircuitBreakerBuckets(IsolatedDBTestCase):
    """T-G（P2-9）：断路器按 bucket 分桶，单 profile 熔断不连坐。"""

    def setUp(self):
        super().setUp()
        # 隔离类级状态，避免跨用例污染
        AiService._breakers = {}
        AiService._ai_circuit_breaker.reset()

    def tearDown(self):
        AiService._breakers = {}
        AiService._ai_circuit_breaker.reset()
        super().tearDown()

    @staticmethod
    async def _boom():
        raise RuntimeError("upstream 500")

    @staticmethod
    async def _ok():
        return {"ok": True}

    def test_G_bucket_isolation(self):
        async def scenario():
            b1 = AiService._get_breaker("profile:1")
            b2 = AiService._get_breaker("profile:2")
            self.assertIsNot(b1, b2, "两个 bucket 复用了同一个断路器实例")

            # profile:1 连续失败 5 次 → OPEN
            for _ in range(5):
                try:
                    await b1.call(self._boom)
                except RuntimeError:
                    pass
            self.assertEqual(b1.state.value, "OPEN")

            # ① profile:1 桶已 OPEN，再次调用抛"断路器已熔断"
            with self.assertRaises(RuntimeError) as ctx1:
                await b1.call(self._ok)
            self.assertIn("断路器已熔断", str(ctx1.exception))

            # ② profile:2 桶仍 CLOSED 且可正常调用
            self.assertEqual(b2.state.value, "CLOSED")
            out = await b2.call(self._ok)
            self.assertEqual(out, {"ok": True})

            # ③ 默认桶不受影响
            default = AiService._get_breaker("default")
            self.assertIs(default, AiService._ai_circuit_breaker)
            self.assertEqual(default.state.value, "CLOSED")
            self.assertEqual(await default.call(self._ok), {"ok": True})

        asyncio.run(scenario())

    def test_G2_empty_and_none_bucket_map_to_default(self):
        """空串 / "default" / None 均落到兼容保留的默认桶。"""
        self.assertIs(AiService._get_breaker(""), AiService._ai_circuit_breaker)
        self.assertIs(AiService._get_breaker("default"), AiService._ai_circuit_breaker)
        self.assertIs(AiService._get_breaker(None), AiService._ai_circuit_breaker)

    def test_G3_agent_llm_passes_profile_bucket(self):
        """AgentLLM 调用 call_llm 时须传 breaker_bucket=profile:{id}。"""
        profile = _FakeProfile(pid=42).data
        mock = AsyncMock(return_value=_ok_resp("HELLO"))
        with patch.object(AiService, "decrypt_api_key", return_value="sk-plain"), \
                patch("app.services.ai_service.AiService.call_llm", new=mock):
            asyncio.run(AgentLLM(profile=profile).call("x", {"id": 1}, trace_id="t-g3"))
        self.assertEqual(mock.await_args.kwargs.get("breaker_bucket"), "profile:42")


# ═════════════════════ T-H：get_active 确定性 ═════════════════════
class TestH_GetActiveDeterministic(IsolatedDBTestCase):
    """T-H（P2-14）：多条 is_active=1 时 get_active() 必须确定性命中 id 最大者。"""

    def _seed_three_active(self):
        with get_connection() as conn:
            for pid in (1, 2, 3):
                conn.execute(
                    "INSERT INTO ai_config_profiles "
                    "(id, profile_name, provider, api_base_url, api_key, model_name, "
                    "max_tokens, temperature, system_prompt, is_active) "
                    "VALUES (?, ?, 'openai', 'http://llm.local/v1', 'k', ?, "
                    "4096, 0.3, '', 1)",
                    (pid, f"p{pid}", f"model-{pid}"),
                )

    def test_H_get_active_returns_max_id_ten_times(self):
        self._seed_three_active()
        with get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM ai_config_profiles WHERE is_active = 1"
            ).fetchone()[0]
        self.assertEqual(total, 3, "前置失败：未造出 3 条 is_active=1")

        for i in range(10):
            with self.subTest(iteration=i):
                got = AiConfigProfile.get_active()
                self.assertIsNotNone(got)
                self.assertEqual(got["id"], 3)
                self.assertEqual(got["model_name"], "model-3")

    def test_H2_get_active_returns_none_when_no_active(self):
        """无激活 profile → None（契约不变）。"""
        self.assertIsNone(AiConfigProfile.get_active())


if __name__ == "__main__":
    import unittest

    unittest.main(verbosity=2)
