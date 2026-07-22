"""AI 错误映射工具。"""
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def map_http_error(exc) -> str:
    """将 HTTP 错误映射为用户可读的消息。
    
    Args:
        exc: httpx.HTTPStatusError 异常实例。
    
    Returns:
        用户可读的错误消息。
    """
    try:
        status = exc.response.status_code
        body = exc.response.text[:200] if exc.response.text else ""
    except Exception:
        return "AI 服务请求失败"
    
    mapping = {
        400: f"AI 服务请求参数错误: {body}",
        401: "AI 服务认证失败，请检查 API Key",
        402: "AI 服务余额不足，请充值后重试",
        403: "AI 服务权限不足",
        404: "AI 服务 API 地址错误，请检查配置",
        429: "AI 服务请求过于频繁，请稍后重试",
        500: "AI 服务内部错误",
        502: "AI 服务网关错误",
        503: "AI 服务暂时不可用",
        504: "AI 服务暂时不可用，请稍后重试",
    }
    return mapping.get(status, f"AI 服务返回 {status}: {body}")


def _make_http_status_error(status_code: int, body: str = "") -> httpx.HTTPStatusError:
    """构造一个用于测试 / 复现的 httpx.HTTPStatusError.

    Args:
        status_code: 模拟的 HTTP 状态码.
        body: 模拟的响应体文本.

    Returns:
        httpx.HTTPStatusError 实例.
    """
    request: Any = httpx.Request("POST", "https://api.example.com/chat/completions")
    response: Any = httpx.Response(status_code, request=request, text=body)
    return httpx.HTTPStatusError(
        f"Client error '{status_code}' for url '{request.url}'",
        request=request,
        response=response,
    )
