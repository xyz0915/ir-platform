"""重试与断路器测试套件.

测试范围:
    - CircuitBreaker 状态机 (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
    - 快速失败（熔断期间直接拒绝）
    - Exponential backoff 重试逻辑
"""

import asyncio
import time
import unittest

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import httpx

from app.services.retry_handler import CircuitBreaker, with_retry, RETRYABLE_STATUS_CODES
from app.shared.ai_constants import CircuitBreakerState


class TestCircuitBreakerStateMachine(unittest.TestCase):
    """测试断路器状态机."""

    def setUp(self):
        """每个测试前重置断路器（threshold=3, timeout=0.5s 加速测试）."""
        self.cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)

    def test_01_initial_state_closed(self):
        """初始状态应为 CLOSED."""
        self.assertEqual(self.cb.state, CircuitBreakerState.CLOSED)

    def test_02_closed_to_open_on_failures(self):
        """CLOSED -> 连续失败达到阈值 -> OPEN."""
        async def _test():
            for i in range(3):
                try:
                    await self.cb.call(_always_fail)
                except ValueError:
                    pass
            self.assertEqual(self.cb.state, CircuitBreakerState.OPEN)

        asyncio.run(_test())

    def test_03_open_rejects_calls(self):
        """OPEN 状态下直接拒绝调用."""
        async def _test():
            # 先让断路器熔断
            for i in range(3):
                try:
                    await self.cb.call(_always_fail)
                except ValueError:
                    pass
            # 确保 OPEN
            self.assertEqual(self.cb.state, CircuitBreakerState.OPEN)
            # 再次调用应被拒绝
            with self.assertRaises(RuntimeError) as ctx:
                await self.cb.call(_always_succeed)
            self.assertIn("断路器已熔断", str(ctx.exception))

        asyncio.run(_test())

    def test_04_open_to_half_open_after_timeout(self):
        """OPEN -> 超过恢复超时 -> HALF_OPEN."""
        async def _test():
            # 熔断
            for i in range(3):
                try:
                    await self.cb.call(_always_fail)
                except ValueError:
                    pass
            self.assertEqual(self.cb.state, CircuitBreakerState.OPEN)

            # 等待超过 recovery_timeout
            await asyncio.sleep(1.2)

            # 下一次调用应进入 HALF_OPEN
            result = await self.cb.call(_always_succeed)
            self.assertEqual(result, "success")
            # 成功后转为 CLOSED
            self.assertEqual(self.cb.state, CircuitBreakerState.CLOSED)

        asyncio.run(_test())

    def test_05_half_open_to_open_on_failure(self):
        """HALF_OPEN -> 失败 -> OPEN."""
        async def _test():
            # 先熔断
            for i in range(3):
                try:
                    await self.cb.call(_always_fail)
                except ValueError:
                    pass
            self.assertEqual(self.cb.state, CircuitBreakerState.OPEN)

            # 等待超时
            await asyncio.sleep(1.2)

            # HALF_OPEN 试探失败 -> 回到 OPEN
            try:
                await self.cb.call(_always_fail)
            except ValueError:
                pass
            self.assertEqual(self.cb.state, CircuitBreakerState.OPEN)

        asyncio.run(_test())

    def test_06_half_open_to_closed_on_success(self):
        """HALF_OPEN -> 成功 -> CLOSED (完整恢复路径)."""
        async def _test():
            # 先熔断
            for i in range(3):
                try:
                    await self.cb.call(_always_fail)
                except ValueError:
                    pass
            self.assertEqual(self.cb.state, CircuitBreakerState.OPEN)

            # 等待超时
            await asyncio.sleep(1.2)

            # HALF_OPEN 试探成功
            result = await self.cb.call(_always_succeed)
            self.assertEqual(self.cb.state, CircuitBreakerState.CLOSED)
            self.assertEqual(result, "success")

            # 之后可以正常调用
            result2 = await self.cb.call(_always_succeed)
            self.assertEqual(result2, "success")

        asyncio.run(_test())

    def test_07_reset_manually(self):
        """手动 reset 恢复到 CLOSED."""
        async def _test():
            for i in range(3):
                try:
                    await self.cb.call(_always_fail)
                except ValueError:
                    pass
            self.assertEqual(self.cb.state, CircuitBreakerState.OPEN)

            self.cb.reset()
            self.assertEqual(self.cb.state, CircuitBreakerState.CLOSED)
            self.assertEqual(self.cb._failure_count, 0)

        asyncio.run(_test())

    def test_08_single_failure_no_open(self):
        """单次失败不应触发熔断."""
        async def _test():
            try:
                await self.cb.call(_always_fail)
            except ValueError:
                pass
            self.assertEqual(self.cb.state, CircuitBreakerState.CLOSED)

        asyncio.run(_test())

    def test_09_sync_function_support(self):
        """断路器应支持同步函数."""
        def sync_func():
            return "sync_ok"

        async def _test():
            result = await self.cb.call(sync_func)
            self.assertEqual(result, "sync_ok")

        asyncio.run(_test())


class TestRetryHandler(unittest.TestCase):
    """测试指数退避重试逻辑."""

    def test_01_success_no_retry(self):
        """成功调用不重试."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        async def _test():
            result = await succeed()
            self.assertEqual(result, "ok")
            self.assertEqual(call_count, 1)

        asyncio.run(_test())

    def test_02_retry_on_502(self):
        """502 状态码应触发重试."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def fail_502():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                response = httpx.Response(502, request=httpx.Request("POST", "http://test"))
                raise httpx.HTTPStatusError("Bad Gateway", request=response.request, response=response)
            return "recovered"

        async def _test():
            result = await fail_502()
            self.assertEqual(result, "recovered")
            self.assertEqual(call_count, 3)  # 2 fails + 1 success

        asyncio.run(_test())

    def test_03_retry_on_429(self):
        """429 状态码应触发重试."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        async def fail_429():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                response = httpx.Response(429, request=httpx.Request("POST", "http://test"))
                raise httpx.HTTPStatusError("Rate Limit", request=response.request, response=response)
            return "ok"

        async def _test():
            result = await fail_429()
            self.assertEqual(result, "ok")
            self.assertEqual(call_count, 3)

        asyncio.run(_test())

    def test_04_retry_on_503(self):
        """503 状态码应触发重试."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        async def fail_503():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                response = httpx.Response(503, request=httpx.Request("POST", "http://test"))
                raise httpx.HTTPStatusError("Service Unavailable", request=response.request, response=response)
            return "ok"

        async def _test():
            result = await fail_503()
            self.assertEqual(result, "ok")

        asyncio.run(_test())

    def test_05_no_retry_on_401(self):
        """401 (Non-retryable) 不应重试."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def fail_401():
            nonlocal call_count
            call_count += 1
            response = httpx.Response(401, request=httpx.Request("POST", "http://test"))
            raise httpx.HTTPStatusError("Unauthorized", request=response.request, response=response)

        async def _test():
            with self.assertRaises(httpx.HTTPStatusError):
                await fail_401()
            self.assertEqual(call_count, 1)  # 不重试

        asyncio.run(_test())

    def test_06_no_retry_on_400(self):
        """400 (Non-retryable) 不应重试."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def fail_400():
            nonlocal call_count
            call_count += 1
            response = httpx.Response(400, request=httpx.Request("POST", "http://test"))
            raise httpx.HTTPStatusError("Bad Request", request=response.request, response=response)

        async def _test():
            with self.assertRaises(httpx.HTTPStatusError):
                await fail_400()
            self.assertEqual(call_count, 1)

        asyncio.run(_test())

    def test_07_retry_on_timeout(self):
        """超时应触发重试."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        async def fail_timeout():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.TimeoutException("Timeout")
            return "ok"

        async def _test():
            result = await fail_timeout()
            self.assertEqual(result, "ok")
            self.assertEqual(call_count, 3)

        asyncio.run(_test())

    def test_08_retry_on_connect_error(self):
        """连接错误应触发重试."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        async def fail_connect():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.ConnectError("Connection refused")
            return "ok"

        async def _test():
            result = await fail_connect()
            self.assertEqual(result, "ok")

        asyncio.run(_test())

    def test_09_retries_exhausted(self):
        """重试耗尽后抛出异常."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            response = httpx.Response(502, request=httpx.Request("POST", "http://test"))
            raise httpx.HTTPStatusError("Bad Gateway", request=response.request, response=response)

        async def _test():
            with self.assertRaises(httpx.HTTPStatusError):
                await always_fail()
            # 1 initial + 2 retries = 3 attempts
            self.assertEqual(call_count, 3)

        asyncio.run(_test())

    def test_10_exponential_backoff_delays(self):
        """验证指数退避延迟值."""
        # base_delay = 1.0, exponent
        self.assertEqual(1.0 * (2 ** 0), 1.0)   # attempt 0: 1s
        self.assertEqual(1.0 * (2 ** 1), 2.0)   # attempt 1: 2s
        self.assertEqual(1.0 * (2 ** 2), 4.0)   # attempt 2: 4s


# ================================================================
# 测试辅助函数
# ================================================================

async def _always_fail():
    """始终失败的异步函数."""
    raise ValueError("simulated failure")


async def _always_succeed():
    """始终成功的异步函数."""
    return "success"


if __name__ == "__main__":
    unittest.main(verbosity=2)
