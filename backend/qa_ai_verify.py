"""独立 QA 全量回归验证脚本（不依赖前任工程师的自测代码）。

实跑而非读码，对 5 组已落地修复逐项验证：
  1) #11 推荐追问空白：build_suggested_questions 返回 list[dict]，每条含
     title/question/focus_area；前端 DeepDiveQuestionPanel 渲染 item.title/item.question；
     AiAnalysisDialog.handleSelectRecommendedQuestion 消费 item.focus_area。
  2) 402 友好提示：构造 httpx.HTTPStatusError(402)，跑 _execute_task 任务路径，
     断言写入中文友好提示（含「余额」或「充值」），而非原始 HTTP 文本。
  3) 引擎 3 方法：build_evidence_trace / normalize_section / ensure_structured_timeline
     可调用且返回结构符合下游契约。
  4) 时序/竞态：_execute_task 的 finally 调 cleanup_task；map_http_error 各分支
     (401/402/403/404/429/5xx) 返回不同中文；HTTPStatusError 分支在 Exception 之前。
  5) 超时对齐：ai.js chatWithAi timeout=120000、ai_service.chat_with_ai timeout=120.0、
     index.js 全局 30000 未变。

数据库：使用隔离的临时库 data/qa_verify_tmp.db，不影响业务数据。
"""

import ast
import asyncio
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = str(BACKEND_DIR / "data" / "qa_verify_tmp.db")


def _ensure_isolated_db() -> None:
    """重建隔离的临时库（每次调用都清空，顺序无关）。"""
    import sqlite3

    from app.config import settings
    from app.database import init_db
    from app.models.ai_config import AiConfigProfile

    db_path = Path(TEST_DB_PATH)
    if db_path.exists():
        db_path.unlink()
    settings.DB_PATH = TEST_DB_PATH
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    init_db()

    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("INSERT INTO cases (name, case_number) VALUES (?, ?)", ("QA验证案件", "QA-001"))
    conn.execute(
        "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) VALUES (?, ?, ?, ?, ?)",
        (1, "QA-HOST", "10.0.0.99", "windows", "imported"),
    )
    conn.commit()
    conn.close()

    AiConfigProfile.create(
        profile_name="QA配置",
        provider="deepseek",
        api_base_url="https://api.deepseek.com",
        api_key="dummy-encrypted-key",
        model_name="deepseek-chat",
    )


def _make_http_error(status_code: int, body: str = "") -> "httpx.HTTPStatusError":
    """独立构造用于测试的 httpx.HTTPStatusError（不依赖被测模块内部 helper）。"""
    import httpx

    request = httpx.Request("POST", "https://api.example.com/chat/completions")
    response = httpx.Response(status_code, request=request, text=body)
    return httpx.HTTPStatusError(
        f"Client error '{status_code}' for url '{request.url}'",
        request=request,
        response=response,
    )


# ============================================================================
# #11 推荐追问 + 前端渲染契约
# ============================================================================
class TestQaIssue11SuggestedQuestions(unittest.TestCase):
    def test_build_suggested_questions_returns_list_of_dicts_with_three_keys(self):
        """直接调用，断言返回 list[dict]，每条含 title/question/focus_area。"""
        from app.services.explainability_service import ExplainabilityService

        parsed = {
            "risk_assessment": {"risk_level": "高危"},
            "threat_analysis": {"attack_vector": "钓鱼邮件"},
            "timeline_analysis": {"attack_chain": "点击→下载→执行"},
        }
        gaps = {"missing_data": ["缺时间线"], "blind_spots": ["缺外联证据"]}
        questions = ExplainabilityService.build_suggested_questions(parsed, gaps)

        self.assertIsInstance(questions, list, "必须返回 list")
        self.assertEqual(len(questions), 5, "5 条候选应全部命中")
        for i, q in enumerate(questions):
            self.assertIsInstance(q, dict, f"第 {i} 条必须是 dict")
            for key in ("title", "question", "focus_area"):
                self.assertIn(key, q, f"第 {i} 条缺少键 '{key}'")
                self.assertTrue(q.get(key), f"第 {i} 条的 '{key}' 必须非空")
        # focus_area 取值齐全
        self.assertEqual(
            {q["focus_area"] for q in questions},
            {"attack_vector", "attack_chain", "missing_data", "blind_spots", "risk"},
        )

    def test_frontend_deepdive_panel_renders_title_and_question(self):
        """断言 DeepDiveQuestionPanel.vue 渲染 item.title / item.question。"""
        vue = (FRONTEND_DIR / "src" / "components" / "ai" / "DeepDiveQuestionPanel.vue").read_text(encoding="utf-8")
        self.assertIn("item.title", vue, "DeepDiveQuestionPanel 必须渲染 item.title")
        self.assertIn("item.question", vue, "DeepDiveQuestionPanel 必须渲染 item.question")
        # 必须 emit 出整条 item 供父组件消费 focus_area
        self.assertIn("$emit('select', item)", vue, "必须 emit 整条 item")

    def test_frontend_dialog_consumes_focus_area(self):
        """断言 AiAnalysisDialog.handleSelectRecommendedQuestion 消费 item.focus_area。"""
        dlg = (FRONTEND_DIR / "src" / "components" / "AiAnalysisDialog.vue").read_text(encoding="utf-8")
        self.assertIn("handleSelectRecommendedQuestion", dlg)
        self.assertIn("item.focus_area", dlg, "handleSelectRecommendedQuestion 必须消费 item.focus_area")


# ============================================================================
# 3) 引擎静态方法契约
# ============================================================================
class TestQaEngineThreeMethods(unittest.TestCase):
    def test_build_evidence_trace_contract(self):
        from app.services.explainability_service import ExplainabilityService

        parsed = {
            "risk_assessment": {"risk_level": "high"},
            "threat_analysis": {"attack_vector": "钓鱼邮件", "attack_chain": "A→B→C"},
            "timeline_analysis": {"attack_chain": "点击→执行"},
        }
        out = ExplainabilityService.build_evidence_trace(parsed, [], {})
        self.assertIn("evidence_trace", out)
        self.assertIn("recommended_questions", out)
        ev = out["evidence_trace"]
        for k in ("knowledge_evidence", "local_evidence", "explainability_labels"):
            self.assertIn(k, ev, f"evidence_trace 缺少 {k}")
        # recommended_questions 本身是 #11 契约对象列表
        self.assertIsInstance(out["recommended_questions"], list)
        for q in out["recommended_questions"]:
            self.assertIn("title", q)
            self.assertIn("question", q)
            self.assertIn("focus_area", q)

    def test_normalize_section_returns_fresh_dict_and_no_pollution(self):
        from app.services.explainability_service import ExplainabilityService

        self.assertEqual(ExplainabilityService.normalize_section(None), {})
        self.assertEqual(ExplainabilityService.normalize_section("x"), {})
        src = {"a": {"b": 1}}
        out = ExplainabilityService.normalize_section(src)
        self.assertEqual(out, src)
        self.assertIsNot(out, src)
        out["a"]["b"] = 999
        self.assertEqual(src["a"]["b"], 1, "修改副本不应污染原对象")

    def test_ensure_structured_timeline_has_key_events(self):
        from app.services.explainability_service import ExplainabilityService

        section = {"attack_chain": "X", "key_events": [{"event": "进程创建"}]}
        out = ExplainabilityService.ensure_structured_timeline(section, {})
        self.assertIn("key_events", out)
        self.assertEqual(out["key_events"][0]["event"], "进程创建")
        # 空输入也不崩，且返回结构安全
        self.assertEqual(ExplainabilityService.ensure_structured_timeline(None, None)["key_events"], [])


# ============================================================================
# 4) map_http_error 各分支返回不同中文
# ============================================================================
class TestQaMapHttpErrorBranches(unittest.TestCase):
    CASES = [
        (401, "鉴权失败"),
        (402, "余额不足"),
        (403, "访问被拒绝"),
        (404, "API 地址错误"),
        (429, "请求过于频繁"),
        (500, "暂时不可用"),
        (502, "暂时不可用"),
        (503, "暂时不可用"),
        (504, "暂时不可用"),
    ]

    def test_all_known_codes_return_distinct_chinese(self):
        from app.shared.ai_error_mapping import map_http_error

        seen = {}
        for code, kw in self.CASES:
            msg = map_http_error(_make_http_error(code))
            self.assertIn(kw, msg, f"状态码 {code} 应含 '{kw}'")
            self.assertNotIn("Client error", msg, f"状态码 {code} 不应透传原始 HTTP 文案")
            self.assertNotIn("Payment Required", msg, f"状态码 {code} 不应透传响应体")
            seen.setdefault(msg, []).append(code)
        # 401/402/403/404/429 必须各不相同
        for code in (401, 402, 403, 404, 429):
            self.assertEqual(len(seen[map_http_error(_make_http_error(code))]), 1,
                             f"状态码 {code} 的提示不应与其它状态码重复")

    def test_402_keyword_balance_or_recharge(self):
        from app.shared.ai_error_mapping import map_http_error

        msg = map_http_error(_make_http_error(402, "Payment Required"))
        self.assertTrue("余额" in msg or "充值" in msg, "402 必须提示余额/充值")


# ============================================================================
# 2) 402 友好提示 —— 实跑 _execute_task 任务路径
# ============================================================================
class TestQa402TaskPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_isolated_db()

    def _run_with_402(self) -> dict:
        from app.models.ai_task import AiTask
        from app.services.ai_task_service import AiTaskService
        from app.services.ai_service import AiService
        from app.services.audit_service import AuditService

        task = AiTask.create(host_id=1, profile_id=1, masked_mode=0)
        task_id = task["id"]
        AiTaskService._task_streams[str(task_id)] = asyncio.Queue()
        AiTaskService._cancel_flags[str(task_id)] = asyncio.Event()

        async def _fake_stream(*args, **kwargs):
            raise _make_http_error(402, "Payment Required")
            yield  # 使其成为异步生成器

        async def _run():
            with mock.patch.object(AiService, "call_llm_stream", _fake_stream), \
                 mock.patch.object(AiService, "decrypt_api_key", return_value="dummy-key"), \
                 mock.patch("app.services.ai_task_service.PromptBuilder") as mock_pb, \
                 mock.patch.object(AuditService, "log_call", return_value=None):
                mock_pb.build.return_value = {"system_prompt": "sys", "user_prompt": "usr"}
                await AiTaskService._execute_task(task_id)

        asyncio.run(_run())
        return AiTask.get_by_id(task_id)

    def test_402_writes_friendly_message_not_raw_text(self):
        result = self._run_with_402()
        self.assertEqual(result["status"], "failed")
        self.assertTrue("余额" in result["error_message"] or "充值" in result["error_message"],
                        f"error_message 应为余额/充值提示，实际: {result['error_message']}")
        self.assertNotIn("Payment Required", result["error_message"])
        self.assertNotIn("Client error", result["error_message"])


# ============================================================================
# 4) 时序/竞态：finally 调 cleanup_task；HTTPStatusError 分支在 Exception 之前
# ============================================================================
class TestQaFinallyCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_isolated_db()

    def test_finally_calls_cleanup_task_even_on_error(self):
        from app.models.ai_task import AiTask
        from app.services.ai_task_service import AiTaskService
        from app.services.ai_service import AiService
        from app.services.audit_service import AuditService

        task = AiTask.create(host_id=1, profile_id=1, masked_mode=0)
        task_id = task["id"]
        AiTaskService._task_streams[str(task_id)] = asyncio.Queue()
        AiTaskService._cancel_flags[str(task_id)] = asyncio.Event()

        async def _fake_stream(*args, **kwargs):
            raise RuntimeError("boom")  # 命中 except Exception 分支，仍要走 finally
            yield

        cleanup_spy = mock.MagicMock()

        async def _run():
            with mock.patch.object(AiService, "call_llm_stream", _fake_stream), \
                 mock.patch.object(AiService, "decrypt_api_key", return_value="dummy-key"), \
                 mock.patch("app.services.ai_task_service.PromptBuilder") as mock_pb, \
                 mock.patch.object(AuditService, "log_call", return_value=None), \
                 mock.patch.object(AiTaskService, "cleanup_task", side_effect=cleanup_spy), \
                 mock.patch("asyncio.sleep", new_callable=mock.AsyncMock, return_value=None):
                mock_pb.build.return_value = {"system_prompt": "sys", "user_prompt": "usr"}
                await AiTaskService._execute_task(task_id)

        asyncio.run(_run())
        self.assertTrue(cleanup_spy.called, "finally 必须调用 cleanup_task 释放内存")

    def test_httpstatuserror_branch_before_generic_exception(self):
        """源代码层面确认任务级 except httpx.HTTPStatusError 在 except Exception 之前且不 re-raise。

        注意：文件内还有一个「内层」except Exception（包裹 call_llm_stream 的
        try 块，会 re-raise），必须锚定到「HTTPStatusError 分支之后」出现的
        那个任务级通用处理分支，避免误匹配内层。
        """
        src = (BACKEND_DIR / "app" / "services" / "ai_task_service.py").read_text(encoding="utf-8")
        idx_http = src.find("except httpx.HTTPStatusError")
        self.assertGreater(idx_http, 0, "缺少 except httpx.HTTPStatusError 分支")
        # 任务级通用处理分支 = HTTPStatusError 分支【之后】出现的第一个 except Exception
        idx_exc = src.find("except Exception", idx_http)
        self.assertGreater(idx_exc, 0, "缺少任务级 except Exception 分支")
        self.assertLess(idx_http, idx_exc, "HTTPStatusError 分支必须在任务级 Exception 之前")

        # 该 HTTPStatusError 分支体内不应 re-raise（内层 LLM 流式 try 的 re-raise 不在其内）
        http_branch = src[idx_http:idx_exc]
        self.assertNotIn("raise", http_branch, "任务级 HTTPStatusError 分支不应 re-raise")

        # finally 块内确实存在 cleanup_task 调用，且位于两个 handler 之后
        idx_finally = src.find("finally:", idx_exc)
        idx_cleanup = src.find("cls.cleanup_task(task_id)", idx_finally)
        self.assertGreater(idx_finally, 0, "缺少 finally 块")
        self.assertGreater(idx_cleanup, 0, "finally 内缺少 cleanup_task 调用")
        self.assertGreater(idx_cleanup, idx_finally, "cleanup_task 必须在 finally 块内")


# ============================================================================
# 5) 超时对齐
# ============================================================================
class TestQaTimeoutAlignment(unittest.TestCase):
    def test_backend_chat_with_ai_timeout_120(self):
        """ai_service.chat_with_ai 必须使用 httpx.AsyncClient(timeout=120.0)。"""
        path = BACKEND_DIR / "app" / "services" / "ai_service.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "chat_with_ai":
                timeouts = []
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        func = sub.func
                        if isinstance(func, ast.Attribute) and func.attr == "AsyncClient":
                            for kw in sub.keywords:
                                if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                                    timeouts.append(kw.value.value)
                found = timeouts
                break
        self.assertIsNotNone(found, "未找到 chat_with_ai 函数")
        self.assertIn(120.0, found, f"chat_with_ai 应使用 timeout=120.0，实际: {found}")
        self.assertNotIn(300.0, found, "chat_with_ai 不应使用 300.0（那是历史其它接口）")

    def test_frontend_chat_with_ai_timeout_120000(self):
        text = (FRONTEND_DIR / "src" / "api" / "ai.js").read_text(encoding="utf-8")
        m = re.search(r"export function chatWithAi\([\s\S]*?\n\}", text)
        self.assertIsNotNone(m, "未找到 chatWithAi 函数")
        self.assertIn("120000", m.group(0), "chatWithAi 必须 timeout:120000")

    def test_frontend_global_timeout_still_30000(self):
        text = (FRONTEND_DIR / "src" / "api" / "index.js").read_text(encoding="utf-8")
        self.assertIn("timeout: 30000", text, "全局 axios 必须仍是 timeout:30000")
        self.assertNotIn("120000", text, "全局 axios 不应被改为 120000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
