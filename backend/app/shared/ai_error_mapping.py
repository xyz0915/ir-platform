"""AI 服务 HTTP 错误 → 中文友好提示映射.

将 httpx.HTTPStatusError（API 返回非 2xx）转换为面向用户的中文提示，
避免把原始的 'Client error '402 Payment Required' for url ...' 直接透传给前端。
"""

from typing import Any

import httpx


def map_http_error(e: httpx.HTTPStatusError) -> str:
    """将 httpx.HTTPStatusError 转换为面向用户的中文友好提示.

    按 HTTP 状态码返回对应的排查建议，覆盖常见的鉴权 / 配额 / 限流 /
    网关错误。未知状态码返回带原始状态码与响应片段的通用提示。

    Args:
        e: httpx 抛出的 HTTPStatusError，其 ``response`` 包含
            ``status_code`` 与 ``text`` 字段。

    Returns:
        面向用户的中文错误提示字符串.
    """
    status_code: int = e.response.status_code

    if status_code == 401:
        return "AI API 鉴权失败，请检查 API Key 是否正确"
    if status_code == 402:
        return "AI 账户余额不足或需要充值，请登录服务商控制台确认账户状态"
    if status_code == 403:
        return "AI API 访问被拒绝，请检查 API Key 权限或服务可用区域"
    if status_code == 404:
        return "AI API 地址错误，请检查 API Base URL 配置"
    if status_code == 429:
        return "AI API 请求过于频繁，请稍后重试"
    if status_code in (500, 502, 503, 504):
        return "AI 服务商暂时不可用，请稍后重试"

    # 其他状态码：返回通用提示，附原始状态码与响应片段（截断避免泄露过多信息）
    body: str = ""
    try:
        body = (e.response.text or "")[:120]
    except Exception:  # noqa: BLE001 - 防御：极端情况下 text 可能不可读
        body = ""
    if body:
        return f"AI 服务调用失败 (HTTP {status_code}): {body}"
    return f"AI 服务调用失败 (HTTP {status_code})"


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
