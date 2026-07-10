"""AI HTTP 错误友好提示映射测试套件.

测试范围:
    - AiTaskService._map_http_error 按 HTTP 状态码返回中文友好提示
    - 共享模块 app.shared.ai_error_mapping.map_http_error 行为一致
    - _execute_task 在流式调用遇到 402/429 时，将友好提示写入任务状态
      （而非把原始 HTTP 错误文本透传给前端）
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_http_error.db")


def _make_http_error(status_code: int, body: str = "") -> "httpx.HTTPStatusError":
    """构造用于测试的 httpx.HTTPStatusError."""
    import httpx

    request = httpx.Request("POST", "https://api.example.com/chat/completions")
    response = httpx.Response(status_code, request=request, text=body)
    return httpx.HTTPStatusError(
        f"Client error '{status_code}' for url '{request.url}'",
        request=request,
        response=response,
    )


class TestAiHttpErrorMapping(unittest.TestCase):
    """直接测试 HTTP 状态码 → 中文友好提示映射."""

    # (状态码, 期望出现在返回消息中的关键字)
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

    def test_map_http_error_all_known_codes(self):
        """已知状态码都应返回包含期望关键字的中文提示."""
        from app.services.ai_task_service import AiTaskService

        for status_code, keyword in self.CASES:
            with self.subTest(status_code=status_code):
                err = _make_http_error(status_code)
                msg = AiTaskService._map_http_error(err)
                self.assertIn(keyword, msg,
                              f"状态码 {status_code} 的提示应含 '{keyword}'，实际: {msg}")

    def test_map_http_error_402_keyword(self):
        """402 必须提示余额不足 / 充值（对应 DeepSeek 402 Payment Required 场景）."""
        from app.services.ai_task_service import AiTaskService

        err = _make_http_error(402, "Payment Required")
        msg = AiTaskService._map_http_error(err)
        self.assertIn("余额不足", msg)
        self.assertIn("充值", msg)

    def test_map_http_error_unknown_code_includes_status(self):
        """未知状态码返回通用提示，并附原始状态码与响应片段."""
        from app.services.ai_task_service import AiTaskService

        err = _make_http_error(418, '{"error":"teapot"}')
        msg = AiTaskService._map_http_error(err)
        self.assertIn("418", msg)
        self.assertIn("teapot", msg)

    def test_shared_map_http_error_matches_classmethod(self):
        """共享模块函数与 AiTaskService._map_http_error 行为一致."""
        from app.services.ai_task_service import AiTaskService
        from app.shared.ai_error_mapping import map_http_error

        for status_code, _ in self.CASES:
            with self.subTest(status_code=status_code):
                err = _make_http_error(status_code)
                self.assertEqual(
                    AiTaskService._map_http_error(err),
                    map_http_error(err),
                )

    def test_shared_map_http_error_does_not_leak_raw_text(self):
        """友好提示不应直接包含原始 HTTP 错误英文文案（如 'Payment Required'）."""
        from app.services.ai_task_service import AiTaskService

        err = _make_http_error(402, "Payment Required")
        msg = AiTaskService._map_http_error(err)
        self.assertNotIn("Payment Required", msg)
        self.assertNotIn("Client error", msg)


class TestAiTaskServiceHttpErrorIntegration(unittest.TestCase):
    """集成测试：_execute_task 在遇到 HTTP 错误时写入友好提示."""

    @classmethod
    def setUpClass(cls):
        """初始化测试数据库并准备 案件 / 主机 / 激活 Profile."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db, get_connection
        init_db()

        with get_connection() as conn:
            conn.execute(
                "INSERT INTO cases (name, case_number) VALUES (?, ?)",
                ("HTTP错误测试案件", "HTTP-ERR-001"),
            )
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, "HTTP-ERR-HOST", "10.0.0.9", "windows", "imported"),
            )

        from app.models.ai_config import AiConfigProfile
        AiConfigProfile.create(
            profile_name="测试配置",
            provider="deepseek",
            api_base_url="https://api.deepseek.com",
            api_key="dummy-encrypted-key",
            model_name="deepseek-chat",
        )

    def _run_execute_with_error(self, status_code: int, body: str = "") -> dict:
        """运行 _execute_task，流式调用抛出指定 HTTP 错误，返回最终任务状态."""
        from app.models.ai_task import AiTask
        from app.services.ai_task_service import AiTaskService
        from app.services.ai_service import AiService
        from app.services.audit_service import AuditService
        from app.shared.ai_error_mapping import _make_http_status_error

        task = AiTask.create(host_id=1, profile_id=1, masked_mode=0)
        task_id = task["id"]
        AiTaskService._task_streams[str(task_id)] = asyncio.Queue()
        AiTaskService._cancel_flags[str(task_id)] = asyncio.Event()

        async def _fake_stream(*args, **kwargs):
            # 在 async for 首次迭代时抛出，模拟 DeepSeek 返回非 2xx
            raise _make_http_status_error(status_code, body)
            yield  # 使其成为异步生成器

        async def _run():
            with mock.patch.object(AiService, "call_llm_stream", _fake_stream), \
                 mock.patch.object(AiService, "decrypt_api_key", return_value="dummy-key"), \
                 mock.patch("app.services.ai_task_service.PromptBuilder") as mock_pb, \
                 mock.patch.object(AuditService, "log_call", return_value=None):
                mock_pb.build.return_value = {
                    "system_prompt": "sys",
                    "user_prompt": "usr",
                }
                await AiTaskService._execute_task(task_id)

        asyncio.run(_run())
        return AiTask.get_by_id(task_id)

    def test_execute_task_402_writes_friendly_message(self):
        """402 场景下，任务 error_message 应为余额不足提示而非原始 HTTP 文本."""
        result = self._run_execute_with_error(402, "Payment Required")
        self.assertEqual(result["status"], "failed")
        self.assertIn("余额不足", result["error_message"])
        self.assertNotIn("Payment Required", result["error_message"])
        self.assertNotIn("Client error", result["error_message"])

    def test_execute_task_429_writes_friendly_message(self):
        """429 场景下，任务 error_message 应为限流提示."""
        result = self._run_execute_with_error(429, "Too Many Requests")
        self.assertEqual(result["status"], "failed")
        self.assertIn("请求过于频繁", result["error_message"])
        self.assertNotIn("Too Many Requests", result["error_message"])

    def test_execute_task_500_writes_friendly_message(self):
        """500 场景下，任务 error_message 应为服务商不可用提示."""
        result = self._run_execute_with_error(500, "Internal Server Error")
        self.assertEqual(result["status"], "failed")
        self.assertIn("暂时不可用", result["error_message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
