"""时间归一化工具 — 统一 'YYYY-MM-DD HH:MM:SS' 服务器本地时间契约（P1-1）。

库内时间规范为服务器本地时间、格式 ``YYYY-MM-DD HH:MM:SS``
（与 SQLite ``datetime('now')`` 及现有数据一致）。不引入时区转换
（平台单机部署，``agent_imports.imported_at`` 现状即本地/UTC 朴素格式）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def parse_client_time(value: Optional[str]) -> Optional[str]:
    """前端输入 → 'YYYY-MM-DD HH:MM:SS'.

    - 剥离 'Z'/'z' 后缀；'T' → ' '；截断毫秒；'YYYY-MM-DD' → 补 ' 00:00:00'；
    - 非法 → 原样返回（由 SQL 比较自然失败），端点层可 400。

    Args:
        value: 客户端时间字符串（可为空/None）。

    Returns:
        归一化后的本地时间字符串；空输入原样返回。
    """
    if not value:
        return value
    text = str(value).strip()
    # 剥离 Z/z 后缀（UTC 标记，平台按本地朴素时间处理）
    text = text.rstrip("Zz")
    # 'T' → ' '
    text = text.replace("T", " ")
    # 截断毫秒/微秒：'2026-07-14 09:00:00.123' → '2026-07-14 09:00:00'
    if "." in text:
        text = text.split(".")[0]
    # 'YYYY-MM-DD' → 补 ' 00:00:00'
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        text = text + " 00:00:00"
    # 尝试解析验证（失败原样返回，由 SQL 比较自然失败）
    try:
        datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(value).strip()
    return text


def normalize_db_ts(value: Optional[str]) -> Optional[str]:
    """存量值归一（幂等）：replace('T',' ') + rstrip('Z') + 截断毫秒，用于 migration 回填.

    Args:
        value: 数据库中的时间字符串。

    Returns:
        归一化后的时间字符串（未变化则原样返回）。
    """
    if not value:
        return value
    text = str(value)
    text = text.replace("T", " ").rstrip("Zz")
    # 截断毫秒：'2026-07-14 09:00:00.123' → '2026-07-14 09:00:00'
    if "." in text:
        text = text.split(".")[0]
    return text


def now_local_str() -> str:
    """当前服务器本地时间，'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_frontend(dt: datetime) -> str:
    """前端本地时间格式化（对应 utils/time.js 的 formatLocalTime）.

    Args:
        dt: datetime 对象。

    Returns:
        'YYYY-MM-DD HH:MM:SS' 本地字符串。
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")
