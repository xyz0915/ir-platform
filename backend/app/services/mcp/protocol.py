"""JSON-RPC 2.0 消息构建/解析模块.

标准库实现，零第三方依赖。
遵循 JSON-RPC 2.0 规范：
  - 请求：{"jsonrpc": "2.0", "method": "...", "params": {...}, "id": 1}
  - 响应：{"jsonrpc": "2.0", "result": {...}, "id": 1} 或 {"jsonrpc": "2.0", "error": {...}, "id": 1}
  - 通知：{"jsonrpc": "2.0", "method": "...", "params": {...}}（无 id）
"""

import json
from typing import Any, Optional


def build_request(method: str, params: dict, id: int = 1) -> str:
    """构建 JSON-RPC 2.0 请求 JSON 字符串.

    Args:
        method: 方法名（如 "tools/list"、"tools/call"）.
        params: 参数字典.
        id: 请求 ID（缺省 1）.

    Returns:
        JSON 格式的请求字符串.
    """
    request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": id,
    }
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"))


def parse_response(raw: str) -> dict:
    """解析 JSON-RPC 2.0 响应字符串.

    成功时返回 result 字典；失败时抛出 ValueError（含 error 信息）。

    Args:
        raw: 原始响应字符串（单行 JSON）.

    Returns:
        result 字典（响应中的 "result" 字段）.

    Raises:
        ValueError: 解析失败、非 JSON-RPC 响应、或包含 error 字段.
    """
    if not raw or not raw.strip():
        raise ValueError("空响应")

    try:
        response = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"无效 JSON 响应: {exc}") from exc

    if not isinstance(response, dict):
        raise ValueError(f"响应不是 JSON 对象: {type(response).__name__}")

    if "jsonrpc" not in response:
        raise ValueError("非 JSON-RPC 2.0 响应（缺少 jsonrpc 字段）")

    if "error" in response and response["error"] is not None:
        error = response["error"]
        code = error.get("code", -1)
        message = error.get("message", "未知错误")
        raise ValueError(json.dumps({"code": code, "message": message}, ensure_ascii=False))

    if "result" not in response:
        raise ValueError("JSON-RPC 响应缺少 result 或 error 字段")

    return response["result"]


def build_notification(method: str, params: dict) -> str:
    """构建 JSON-RPC 2.0 通知 JSON 字符串（无 id）.

    Args:
        method: 方法名.
        params: 参数字典.

    Returns:
        JSON 格式的通知字符串.
    """
    notification: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    }
    return json.dumps(notification, ensure_ascii=False, separators=(",", ":"))
