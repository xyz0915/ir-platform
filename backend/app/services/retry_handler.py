"""重试与断路器模块.

提供指数退避重试和断路器保护，确保 AI API 调用的可靠性和故障隔离.
"""

import asyncio
import functools
import logging
import time
from typing import Any, Callable, Optional, TypeVar

import httpx

from app.config import settings
from app.shared.ai_constants import CircuitBreakerState

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# 可重试的 HTTP 状态码
RETRYABLE_STATUS_CODES: set[int] = {429, 502, 503}


class CircuitBreaker:
    """断路器 — 防止对故障服务的持续调用.

    状态机：
        CLOSED → (失败达到阈值) → OPEN
        OPEN → (超过恢复超时) → HALF_OPEN
        HALF_OPEN → (成功) → CLOSED
        HALF_OPEN → (失败) → OPEN

    Attributes:
        failure_threshold: 触发熔断的连续失败次数.
        recovery_timeout: 熔断后恢复尝试的冷却时间（秒）.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: Optional[int] = None,
    ) -> None:
        """初始化断路器.

        Args:
            failure_threshold: 连续失败次数阈值，默认 5.
            recovery_timeout: 熔断恢复超时（秒），默认从 settings 读取.
        """
        self.failure_threshold: int = failure_threshold
        self.recovery_timeout: int = recovery_timeout or settings.AI_CIRCUIT_BREAKER_TIMEOUT
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitBreakerState:
        """获取当前状态."""
        return self._state

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """根据断路器状态决定：放行 / 拒绝 / 试探.

        Args:
            func: 要调用的函数（支持同步和异步）.
            *args: 位置参数.
            **kwargs: 关键字参数.

        Returns:
            函数执行结果.

        Raises:
            RuntimeError: 断路器 OPEN 状态时拒绝调用.
            原封不动抛出 func 执行异常.
        """
        if self._state == CircuitBreakerState.OPEN:
            # 检查冷却时间是否已过
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitBreakerState.HALF_OPEN
                logger.info("Circuit breaker transitioning to HALF_OPEN after %.1fs", elapsed)
            else:
                raise RuntimeError(
                    f"断路器已熔断，{self.recovery_timeout - elapsed:.0f}秒后可重试"
                )

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self) -> None:
        """调用成功时更新状态."""
        self._failure_count = 0
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.CLOSED
            logger.info("Circuit breaker recovered to CLOSED")

    def _on_failure(self) -> None:
        """调用失败时更新状态."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if (
            self._failure_count >= self.failure_threshold
            or self._state == CircuitBreakerState.HALF_OPEN
        ):
            self._state = CircuitBreakerState.OPEN
            logger.warning(
                "Circuit breaker OPEN (failures=%d, threshold=%d)",
                self._failure_count,
                self.failure_threshold,
            )

    def reset(self) -> None:
        """手动重置断路器到 CLOSED 状态."""
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        logger.info("Circuit breaker manually reset to CLOSED")


def with_retry(
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
) -> Callable[[F], F]:
    """装饰器：对函数添加指数退避重试逻辑.

    只在遇到可重试的 HTTP 状态码 (429/502/503) 时重试.
    同步函数返回同步 wrapper，异步函数返回异步 wrapper.

    Args:
        max_retries: 最大重试次数，默认从 settings 读取.
        base_delay: 基础延迟（秒），默认从 settings 读取.

    Returns:
        装饰器函数.
    """
    max_retries_val: int = max_retries or settings.AI_MAX_RETRIES
    base_delay_val: float = base_delay or settings.AI_RETRY_BASE_DELAY

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            for attempt in range(max_retries_val + 1):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    last_exception = e
                    if e.response.status_code not in RETRYABLE_STATUS_CODES:
                        raise
                    if attempt < max_retries_val:
                        delay = base_delay_val * (2 ** attempt)
                        logger.warning(
                            "Retry %d/%d after %.1fs (HTTP %d)",
                            attempt + 1,
                            max_retries_val,
                            delay,
                            e.response.status_code,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    last_exception = e
                    if attempt < max_retries_val:
                        delay = base_delay_val * (2 ** attempt)
                        logger.warning(
                            "Retry %d/%d after %.1fs (%s)",
                            attempt + 1,
                            max_retries_val,
                            delay,
                            type(e).__name__,
                        )
                        await asyncio.sleep(delay)
                    else:
                        raise
            # Should not reach here
            if last_exception:
                raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            for attempt in range(max_retries_val + 1):
                try:
                    return func(*args, **kwargs)
                except httpx.HTTPStatusError as e:
                    last_exception = e
                    if e.response.status_code not in RETRYABLE_STATUS_CODES:
                        raise
                    if attempt < max_retries_val:
                        delay = base_delay_val * (2 ** attempt)
                        logger.warning(
                            "Retry %d/%d after %.1fs (HTTP %d)",
                            attempt + 1,
                            max_retries_val,
                            delay,
                            e.response.status_code,
                        )
                        time.sleep(delay)
                    else:
                        raise
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    last_exception = e
                    if attempt < max_retries_val:
                        delay = base_delay_val * (2 ** attempt)
                        logger.warning(
                            "Retry %d/%d after %.1fs (%s)",
                            attempt + 1,
                            max_retries_val,
                            delay,
                            type(e).__name__,
                        )
                        time.sleep(delay)
                    else:
                        raise
            if last_exception:
                raise last_exception

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
