"""回归测试: AI 指挥台 LLM 智能回复改造.

测试范围:
    - ai_nl_query 端点非 unknown 意图时触发 LLM 调用
    - _llm_summary 函数正常/降级路径
    - unknown 意图/空查询不触发 LLM（耗时/消耗保护）
    - LLM 失败时静默降级（保留模板 summary）
"""

import json
import unittest
from unittest.mock import MagicMock, patch


def _ensure_backend_in_path():
    """将 backend 目录加入 sys.path."""
    import sys
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


class TestLlmSummaryFunction(unittest.IsolatedAsyncioTestCase):
    """测试 _llm_summary 函数（在隔离环境中 mock 所有外部依赖)."""

    def setUp(self):
        _ensure_backend_in_path()
        from app.api.ai_advanced import _llm_summary
        self._llm_summary = _llm_summary

    @patch("app.api.ai_advanced.AiConfigProfile.get_active")
    @patch("app.api.ai_advanced.AiService.decrypt_api_key")
    @patch("app.api.ai_advanced.AiService.call_llm")
    async def test_llm_summary_success(self, mock_call_llm, mock_decrypt, mock_get_active):
        """✅ LLM 调用成功时返回 generated 文本."""
        # Arrange
        mock_get_active.return_value = {
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "encrypted-key",
            "model_name": "gpt-4o",
        }
        mock_decrypt.return_value = "sk-real-key"
        mock_call_llm.return_value = {
            "choices": [
                {"message": {"content": "发现 3 条严重告警，建议立即处理。"}}
            ]
        }

        # Act
        result = await self._llm_summary("严重告警", "alerts", '{"items": []}')

        # Assert
        self.assertEqual(result, "发现 3 条严重告警，建议立即处理。")
        mock_get_active.assert_called_once()
        mock_decrypt.assert_called_once_with("encrypted-key")
        mock_call_llm.assert_called_once()

    @patch("app.api.ai_advanced.AiConfigProfile.get_active")
    async def test_llm_summary_no_profile(self, mock_get_active):
        """✅ 无 AI Profile 时静默返回空字符串."""
        # Arrange
        mock_get_active.return_value = None

        # Act
        result = await self._llm_summary("严重告警", "alerts", '{"items": []}')

        # Assert
        self.assertEqual(result, "")

    @patch("app.api.ai_advanced.AiConfigProfile.get_active")
    @patch("app.api.ai_advanced.AiService.decrypt_api_key")
    @patch("app.api.ai_advanced.AiService.call_llm")
    async def test_llm_summary_empty_choices(self, mock_call_llm, mock_decrypt, mock_get_active):
        """✅ LLM 返回空 choices 时静默返回空字符串."""
        # Arrange
        mock_get_active.return_value = {
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "encrypted-key",
            "model_name": "gpt-4o",
        }
        mock_decrypt.return_value = "sk-real-key"
        mock_call_llm.return_value = {"choices": []}

        # Act
        result = await self._llm_summary("严重告警", "alerts", '{"items": []}')

        # Assert
        self.assertEqual(result, "")

    @patch("app.api.ai_advanced.AiConfigProfile.get_active")
    @patch("app.api.ai_advanced.AiService.decrypt_api_key")
    @patch("app.api.ai_advanced.AiService.call_llm")
    async def test_llm_summary_exception(self, mock_call_llm, mock_decrypt, mock_get_active):
        """✅ LLM 抛出异常时静默降级返回空字符串."""
        # Arrange
        mock_get_active.return_value = {
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "encrypted-key",
            "model_name": "gpt-4o",
        }
        mock_decrypt.return_value = "sk-real-key"
        mock_call_llm.side_effect = RuntimeError("Connection refused")

        # Act
        result = await self._llm_summary("严重告警", "alerts", '{"items": []}')

        # Assert
        self.assertEqual(result, "")

    @patch("app.api.ai_advanced.AiConfigProfile.get_active")
    @patch("app.api.ai_advanced.AiService.decrypt_api_key")
    @patch("app.api.ai_advanced.AiService.call_llm")
    async def test_llm_summary_http_error(self, mock_call_llm, mock_decrypt, mock_get_active):
        """✅ LLM HTTP 错误时静默降级返回空字符串."""
        # Arrange
        import httpx
        mock_get_active.return_value = {
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "encrypted-key",
            "model_name": "gpt-4o",
        }
        mock_decrypt.return_value = "sk-real-key"
        mock_call_llm.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        # Act
        result = await self._llm_summary("严重告警", "alerts", '{"items": []}')

        # Assert
        self.assertEqual(result, "")

    @patch("app.api.ai_advanced.AiConfigProfile.get_active")
    @patch("app.api.ai_advanced.AiService.decrypt_api_key")
    @patch("app.api.ai_advanced.AiService.call_llm")
    async def test_llm_summary_uses_correct_params(self, mock_call_llm, mock_decrypt, mock_get_active):
        """✅ _llm_summary 以正确参数调用 AiService.call_llm()."""
        # Arrange
        mock_get_active.return_value = {
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "enc-abc",
            "model_name": "gpt-4o-mini",
        }
        mock_decrypt.return_value = "sk-decrypted"
        mock_call_llm.return_value = {
            "choices": [{"message": {"content": "OK"}}]
        }

        # Act
        await self._llm_summary("有哪些在线主机", "hosts", '{"hosts": []}')

        # Assert — verify call_llm parameter correctness
        mock_call_llm.assert_called_once()
        call_kwargs = mock_call_llm.call_args.kwargs
        self.assertEqual(call_kwargs["api_base_url"], "https://api.openai.com/v1")
        self.assertEqual(call_kwargs["api_key"], "sk-decrypted")
        self.assertEqual(call_kwargs["model"], "gpt-4o-mini")
        self.assertEqual(call_kwargs["max_tokens"], 600)
        self.assertEqual(call_kwargs["temperature"], 0.7)
        # Verify system_prompt contains key instructions
        self.assertIn("网络安全分析助手", call_kwargs["system_prompt"])
        self.assertIn("150 字以内", call_kwargs["system_prompt"])
        # Verify user_prompt contains query, intent, data
        self.assertIn("有哪些在线主机", call_kwargs["user_prompt"])
        self.assertIn("hosts", call_kwargs["user_prompt"])
        self.assertIn('{"hosts": []}', call_kwargs["user_prompt"])


class TestAiNlQueryEndpointUnit(unittest.IsolatedAsyncioTestCase):
    """测试 ai_nl_query 端点的 LLM 触发逻辑（单元测试，mock 数据库 + LLM)."""

    def setUp(self):
        _ensure_backend_in_path()

    @patch("app.api.ai_advanced.get_current_user")
    async def test_empty_query(self, mock_get_user):
        """✅ 空查询 — 不调用 LLM，直接返回 unknown + 提示."""
        from app.api.ai_advanced import ai_nl_query

        mock_get_user.return_value = {"username": "admin", "role": "admin"}

        result = await ai_nl_query(query="")

        data = result["data"]
        self.assertEqual(data["intent"], "unknown")
        self.assertEqual(data["summary"], "请输入问题")
        self.assertIsNone(data.get("llm_generated"))  # 不应设置 llm_generated

    @patch("app.api.ai_advanced.get_current_user")
    @patch("app.api.ai_advanced._execute_query")
    @patch("app.api.ai_advanced._llm_summary")
    async def test_known_intent_triggers_llm(self, mock_llm_summary, mock_execute_query, mock_get_user):
        """✅ 已知意图（alerts）触发 LLM 调用."""
        from app.api.ai_advanced import ai_nl_query

        mock_get_user.return_value = {"username": "admin", "role": "admin"}
        mock_execute_query.return_value = {
            "intent": "alerts",
            "params": {"limit": 20},
            "summary": "共 5 条告警",
            "data": [{"id": 1, "title": "Test"}],
        }
        mock_llm_summary.return_value = "AI: 发现5条告警，建议立即处理。"

        result = await ai_nl_query(query="严重告警")

        data = result["data"]
        self.assertEqual(data["intent"], "alerts")
        self.assertEqual(data["summary"], "AI: 发现5条告警，建议立即处理。")
        self.assertTrue(data["llm_generated"])
        mock_llm_summary.assert_called_once()

    @patch("app.api.ai_advanced.get_current_user")
    @patch("app.api.ai_advanced._execute_query")
    @patch("app.api.ai_advanced._llm_summary")
    async def test_llm_failure_preserves_template_summary(self, mock_llm_summary, mock_execute_query, mock_get_user):
        """✅ LLM 调用失败时 — 原始模板 summary 保持不变，无 llm_generated."""
        from app.api.ai_advanced import ai_nl_query

        mock_get_user.return_value = {"username": "admin", "role": "admin"}
        mock_execute_query.return_value = {
            "intent": "alerts",
            "params": {"limit": 20},
            "summary": "共 5 条告警",
            "data": [{"id": 1, "title": "Test"}],
        }
        mock_llm_summary.return_value = ""  # 模拟 LLM 返回空（降级）

        result = await ai_nl_query(query="严重告警")

        data = result["data"]
        self.assertEqual(data["summary"], "共 5 条告警")  # 原始模板保留
        self.assertNotIn("llm_generated", data)  # 不应设置 llm_generated

    @patch("app.api.ai_advanced.get_current_user")
    @patch("app.api.ai_advanced._execute_query")
    async def test_unknown_intent_skips_llm(self, mock_execute_query, mock_get_user):
        """✅ unknown 意图不调用 LLM（耗时/消耗保护）. """
        from app.api.ai_advanced import ai_nl_query

        mock_get_user.return_value = {"username": "admin", "role": "admin"}
        mock_execute_query.return_value = {
            "intent": "unknown",
            "params": {},
            "summary": "未识别查询意图",
            "data": None,
        }

        # 注：我们不 mock _llm_summary，如果它被调用会真实报错（无 DB），
        # 但 unknown 路径不应进入 _llm_summary，所以不会出错
        result = await ai_nl_query(query="乱七八糟的输入")

        data = result["data"]
        self.assertEqual(data["intent"], "unknown")
        self.assertNotIn("llm_generated", data)


class TestAiNlQueryIntentRouting(unittest.IsolatedAsyncioTestCase):
    """测试 ai_nl_query 意图路由与 LLM 触发覆盖."""

    def setUp(self):
        _ensure_backend_in_path()

    @patch("app.api.ai_advanced.get_current_user")
    @patch("app.api.ai_advanced._execute_query")
    @patch("app.api.ai_advanced._llm_summary")
    async def _test_intent_triggers_llm(self, query, expected_intent,
                                         mock_llm_summary, mock_execute_query, mock_get_user):
        """Helper — 验证给定 query 能触发对应意图的 LLM 调用."""
        from app.api.ai_advanced import ai_nl_query

        mock_get_user.return_value = {"username": "admin", "role": "admin"}
        mock_llm_summary.return_value = f"AI回复关于{expected_intent}"
        mock_execute_query.return_value = {
            "intent": expected_intent,
            "params": {},
            "summary": f"共 5 条{expected_intent}",
            "data": [],
        }

        result = await ai_nl_query(query=query)

        data = result["data"]
        self.assertEqual(data["intent"], expected_intent)
        self.assertTrue(data["llm_generated"])
        self.assertIn(expected_intent, data["summary"])
        mock_llm_summary.assert_called_once()

    async def test_alerts_intent_triggers_llm(self):
        """✅ '告警' 查询触发 LLM."""
        await self._test_intent_triggers_llm("严重的告警有哪些", "alerts")

    async def test_logs_intent_triggers_llm(self):
        """✅ '日志' 查询触发 LLM."""
        await self._test_intent_triggers_llm("查看登录失败的日志", "logs")

    async def test_hosts_intent_triggers_llm(self):
        """✅ '主机' 查询触发 LLM."""
        await self._test_intent_triggers_llm("在线主机有哪些", "hosts")

    async def test_cases_intent_triggers_llm(self):
        """✅ '案件' 查询触发 LLM."""
        await self._test_intent_triggers_llm("当前未结案件", "cases")

    async def test_stats_intent_triggers_llm(self):
        """✅ '统计' 查询触发 LLM."""
        await self._test_intent_triggers_llm("统计信息", "stats")


class TestLlmSummaryFunctionSignature(unittest.TestCase):
    """验证 _llm_summary 函数签名与文档字符串."""

    def setUp(self):
        _ensure_backend_in_path()

    def test_function_is_async(self):
        """✅ _llm_summary 是 async def 函数."""
        import inspect
        from app.api.ai_advanced import _llm_summary
        self.assertTrue(inspect.iscoroutinefunction(_llm_summary))

    def test_function_returns_str(self):
        """✅ _llm_summary 注释标注返回 str."""
        import inspect
        from app.api.ai_advanced import _llm_summary
        sig = inspect.signature(_llm_summary)
        return_annotation = sig.return_annotation
        self.assertEqual(return_annotation, str)


class TestAiNlQueryAsyncEndpoint(unittest.TestCase):
    """测试 ai_nl_query 路由注册为 async."""

    def setUp(self):
        _ensure_backend_in_path()

    def test_route_is_async(self):
        """✅ ai_nl_query 路由函数的 HTTP 方法注册为 async def."""
        import inspect
        from app.api.ai_advanced import ai_nl_query
        self.assertTrue(inspect.iscoroutinefunction(ai_nl_query))


if __name__ == "__main__":
    unittest.main()
