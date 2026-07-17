"""Syslog 解析器 — 支持 RFC 3164（传统）和 RFC 5424（结构化）.

RFC 3164:  <PRI>Timestamp Hostname Tag: Message
RFC 5424:  <PRI>VERSION Timestamp Hostname Appname ProcID MsgID StructuredData Message

输出统一转换为标准字段字典。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Severity 映射 ──
# PRI = facility * 8 + severity
SEVERITY_MAP = {
    0: "emergency",
    1: "alert",
    2: "critical",
    3: "error",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug",
}

# ── Severity → 平台标准严重度 ──
SEVERITY_TO_PLATFORM = {
    "emergency": "critical",
    "alert": "critical",
    "critical": "critical",
    "error": "high",
    "warning": "medium",
    "notice": "low",
    "info": "info",
    "debug": "info",
}


def _parse_pri(raw: str) -> tuple[int, int, int]:
    """从 PRI 字段解析 facility 和 severity.

    Args:
        raw: PRI 字符串，如 '<13>'.

    Returns:
        (pri_value, facility, severity).
    """
    pri_val = int(raw.strip("<>"))
    facility = pri_val // 8
    severity = pri_val % 8
    return pri_val, facility, severity


def _rfc3164_timestamp(ts_str: str) -> str:
    """尝试将 RFC 3164 时间戳转为 ISO 8601.

    RFC 3164 格式: 'Oct  1 12:34:56' 或 'Oct 15 12:34:56'
    """
    try:
        # 尝试解析 'MMM  d HH:MM:SS' 或 'MMM dd HH:MM:SS'
        dt = datetime.strptime(ts_str.strip(), "%b %d %H:%M:%S")
        # 替换为当前年份（RFC 3164 不含年份）
        dt = dt.replace(year=datetime.now().year)
        return dt.isoformat()
    except ValueError:
        return ts_str


def _rfc5424_timestamp(ts_str: str) -> str:
    """RFC 5424 时间戳通常是 ISO 8601 格式，直接返回."""
    return ts_str


# ── 主解析函数 ──

def parse_line(line: str) -> Optional[dict]:
    """解析单行 Syslog，返回结构化字典或 None.

    Returns:
        dict: {
            "host_id": 0,  # 由调用方填充
            "hostname": str,
            "log_source": "syslog_rfc3164" / "syslog_rfc5424",
            "event_type": "syslog",
            "severity": str,          # 平台标准严重度
            "facility": int,
            "severity_code": int,
            "timestamp": str,         # ISO 8601
            "tag": str,
            "message": str,
            "app_name": str,
            "proc_id": str,
            "msg_id": str,
            "structured_data": dict,
            "raw": str,
        }
        解析失败返回 None.
    """
    line = line.strip()
    if not line:
        return None

    # ── 提取 PRI ──
    pri_match = re.match(r"<(\d{1,3})>", line)
    if not pri_match:
        return None

    pri_val, facility, severity_code = _parse_pri(pri_match.group(0))
    severity_label = SEVERITY_MAP.get(severity_code, "info")
    platform_severity = SEVERITY_TO_PLATFORM.get(severity_label, "info")
    rest = line[pri_match.end():].strip()

    # ── 尝试 RFC 5424（PRI 后跟数字版本号）──
    rfc5424_match = re.match(r"(\d+)\s+", rest)
    if rfc5424_match:
        version = int(rfc5424_match.group(1))
        rest2 = rest[rfc5424_match.end():].strip()
        # 解析 RFC 5424 的固定头部字段
        # timestamp hostname appname procid msgid structured-data
        fields = rest2.split(None, 5)  # 最多拆 6 段
        if len(fields) >= 1:
            timestamp = _rfc5424_timestamp(fields[0])
        else:
            timestamp = ""
        hostname = fields[1] if len(fields) > 1 else ""
        app_name = fields[2] if len(fields) > 2 else ""
        proc_id = fields[3] if len(fields) > 3 else ""
        msg_id = fields[4] if len(fields) > 4 else ""
        sd_and_msg = fields[5] if len(fields) > 5 else ""

        # 分离 structured-data 和 message
        sd_match = re.match(r"(\[.*?\])\s*(.*)", sd_and_msg)
        if sd_match:
            structured_data = sd_match.group(1)
            message = sd_match.group(2)
        else:
            structured_data = ""
            message = sd_and_msg

        # 从 message 中提取 tag（冒号前部分）
        tag = ""
        msg_parts = message.split(":", 1)
        if len(msg_parts) > 1 and msg_parts[0].strip():
            tag = msg_parts[0].strip()

        return {
            "hostname": hostname,
            "log_source": "syslog_rfc5424",
            "event_type": "syslog",
            "severity": platform_severity,
            "facility": facility,
            "severity_code": severity_code,
            "timestamp": timestamp,
            "tag": tag,
            "message": message,
            "app_name": app_name,
            "proc_id": proc_id,
            "msg_id": msg_id,
            "structured_data": structured_data,
            "version": version,
        }

    # ── 尝试 RFC 3164（传统格式）──
    # timestamp hostname tag: message
    # timestamp: 'Oct  1 12:34:56' 或 'Oct 15 12:34:56'
    rfc3164_match = re.match(
        r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
        r"(\S+)\s+"
        r"(\S+?):\s*(.*)",
        rest,
        re.IGNORECASE,
    )
    if rfc3164_match:
        timestamp = _rfc3164_timestamp(rfc3164_match.group(1))
        hostname = rfc3164_match.group(2)
        tag = rfc3164_match.group(3)
        message = rfc3164_match.group(4)
        return {
            "hostname": hostname,
            "log_source": "syslog_rfc3164",
            "event_type": "syslog",
            "severity": platform_severity,
            "facility": facility,
            "severity_code": severity_code,
            "timestamp": timestamp,
            "tag": tag,
            "message": message,
            "app_name": "",
            "proc_id": "",
            "msg_id": "",
            "structured_data": "",
        }

    # ── 兜底：能提取 PRI，但后续格式不匹配 ──
    return {
        "hostname": "",
        "log_source": "syslog",
        "event_type": "syslog",
        "severity": platform_severity,
        "facility": facility,
        "severity_code": severity_code,
        "timestamp": "",
        "tag": "",
        "message": rest,
        "app_name": "",
        "proc_id": "",
        "msg_id": "",
        "structured_data": "",
    }


class SyslogParser:
    """Syslog 解析器."""

    @staticmethod
    def parse(lines: list[str], log_source: str, host_id: int, hostname: str) -> list[dict]:
        """解析多行 Syslog 文本.

        Args:
            lines: 文件行列表.
            log_source: 日志来源（syslog_rfc3164 / syslog_rfc5424 / syslog）.
            host_id: 主机 ID.
            hostname: 主机名.

        Returns:
            结构化字典列表.
        """
        results: list[dict] = []
        for i, line in enumerate(lines):
            item = parse_line(line)
            if item is None:
                continue
            item["host_id"] = host_id
            item["hostname"] = hostname or item.get("hostname", "")
            results.append(item)
        return results
