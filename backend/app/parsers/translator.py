"""翻译器 — 将解析后的日志条目映射为 SecurityEvent 兼容格式.

核心功能：
    - translate(): 统一入口，按 log_source 分流
    - infer_severity(): 根据 Access Log 响应码推断严重度
    - make_dedup_key(): 生成去重哈希
"""

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Translator:
    """日志条目翻译器 — 映射为 SecurityEvent 兼容结构."""

    @classmethod
    def translate(cls, normalized_items: list[dict], host_id: int) -> list[dict]:
        """遍历标准化条目，按 log_source 分流翻译.

        Args:
            normalized_items: 解析后的日志条目列表（来自 EvtxParser/AccessLogParser）。
            host_id: 主机 ID。

        Returns:
            list[dict]: 翻译后的 SecurityEvent 格式条目列表。
        """
        results: list[dict[str, Any]] = []
        for item in normalized_items:
            log_source = item.get("log_source", "")
            if log_source == "evtx":
                translated = cls._translate_evtx(item, host_id)
            elif log_source.endswith("_access"):
                translated = cls._translate_access(item, host_id)
            elif log_source in ("nginx_combined", "nginx_common", "apache_combined",
                                "apache_common", "iis_w3c", "tomcat_access"):
                translated = cls._translate_access(item, host_id)
            elif log_source.startswith("syslog"):
                translated = cls._translate_syslog(item, host_id)
            else:
                logger.debug("Unknown log_source '%s', skipping item", log_source)
                continue

            if translated:
                results.append(translated)

        return results

    @classmethod
    def _translate_evtx(cls, item: dict, host_id: int) -> Optional[dict]:
        """翻译 EVTX 条目为 SecurityEvent 格式.

        Args:
            item: EvtxParser 输出的单条记录。
            host_id: 主机 ID。

        Returns:
            dict | None: 翻译后的条目。
        """
        raw_data = item.get("raw_data", {})
        if not isinstance(raw_data, dict):
            raw_data = {}

        # 生成 event_key
        event_id = item.get("event_id", 0)
        timestamp = item.get("timestamp", "")
        description = raw_data.get("description", "")[:100]
        event_key_raw = f"{event_id}:{timestamp}:{description}"
        event_key = cls.make_dedup_key("evtx", host_id, event_key_raw)

        return {
            "id": f"manual:{host_id}:{event_key}",
            "host_id": host_id,
            "event_type": item.get("event_type", "unknown"),
            "severity": item.get("severity", "medium"),
            "timestamp": timestamp,
            "event_key": event_key,
            "source_collector": "manual_import",
            "evidence": {
                "event_id": event_id,
                "event_label": item.get("event_label", ""),
                "src_ip": raw_data.get("IpAddress", raw_data.get("ip_address", "")),
                "user_name": raw_data.get("TargetUserName", raw_data.get("target_user_name", "")),
                "process_name": raw_data.get("ProcessName", raw_data.get("process_name", "")),
                "description": raw_data.get("description", ""),
            },
            "matched_rules": "[]",
            "ioc_matches": "[]",
            "attack_stage": "unknown",
        }

    @classmethod
    def _translate_access(cls, item: dict, host_id: int) -> Optional[dict]:
        """翻译 Access Log 条目为 SecurityEvent 格式.

        Args:
            item: AccessLogParser 输出的单条记录。
            host_id: 主机 ID。

        Returns:
            dict | None: 翻译后的条目。
        """
        # 生成 event_key
        src_ip = item.get("src_ip", "")
        timestamp = item.get("timestamp", "")
        url = item.get("url", "")
        method = item.get("method", "")
        event_key_raw = f"{src_ip}:{timestamp}:{url}:{method}"
        event_key = cls.make_dedup_key(item.get("log_source", "access"), host_id, event_key_raw)

        severity = cls.infer_severity(item)

        # X-Forwarded-For 优先：如果 item 中有 x_forwarded_for 字段，用它覆盖 src_ip
        xff = item.get("x_forwarded_for", "")
        if xff and xff != "-":
            # XFF 格式: "client_ip, proxy1, proxy2" → 取第一个
            xff_src = xff.split(",")[0].strip()
            src_ip = xff_src

        return {
            "id": f"manual:{host_id}:{event_key}",
            "host_id": host_id,
            "event_type": "web_access",
            "severity": severity,
            "timestamp": timestamp,
            "event_key": event_key,
            "source_collector": "manual_import",
            "evidence": {
                "url": url,
                "method": method,
                "status_code": item.get("status_code", 0),
                "user_agent": item.get("user_agent", ""),
                "referer": item.get("referer", ""),
                "src_ip": src_ip,
            },
            "matched_rules": "[]",
            "ioc_matches": "[]",
            "attack_stage": "unknown",
        }

    @classmethod
    def _translate_syslog(cls, item: dict, host_id: int) -> Optional[dict]:
        """翻译 Syslog 条目为 SecurityEvent."""
        event_key_raw = f"{item.get('tag','')}:{item.get('timestamp','')}:{item.get('message','')[:100]}"
        event_key = cls.make_dedup_key(item.get("log_source", "syslog"), host_id, event_key_raw)
        severity = item.get("severity", "info")
        return {
            "id": f"manual:{host_id}:{event_key}",
            "host_id": host_id,
            "event_type": "syslog",
            "severity": severity,
            "timestamp": item.get("timestamp", ""),
            "event_key": event_key,
            "source_collector": "manual_import",
            "evidence": {
                "facility": item.get("facility", 0),
                "severity_code": item.get("severity_code", 6),
                "hostname": item.get("hostname", ""),
                "tag": item.get("tag", ""),
                "message": item.get("message", ""),
                "app_name": item.get("app_name", ""),
                "proc_id": item.get("proc_id", ""),
                "structured_data": item.get("structured_data", ""),
            },
            "matched_rules": "[]",
            "ioc_matches": "[]",
            "attack_stage": "unknown",
        }

    @staticmethod
    def make_dedup_key(log_source: str, host_id: int, event_key: str) -> str:
        """生成去重哈希键.

        Args:
            log_source: 日志来源。
            host_id: 主机 ID。
            event_key: 事件特征键。

        Returns:
            str: SHA256 哈希的前 16 字符。
        """
        raw = f"{log_source}:{host_id}:{event_key}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def infer_severity(item: dict) -> str:
        """推断日志条目的严重级别.

        Access Log：
            - 5xx → "high"
            - 4xx → "medium"
            - 2xx/3xx → "info"
            - 其他 → "low"
        EVTX：直接从 item 的 severity 字段取。

        Args:
            item: 日志条目字典。

        Returns:
            str: 严重级别（'info' | 'low' | 'medium' | 'high' | 'critical'）。
        """
        log_source = item.get("log_source", "")

        if log_source == "evtx":
            return item.get("severity", "medium")

        # Access Log 按状态码推断
        status_code = item.get("status_code", 0)
        if isinstance(status_code, str):
            try:
                status_code = int(status_code)
            except (ValueError, TypeError):
                status_code = 0

        if 500 <= status_code < 600:
            return "high"
        if 400 <= status_code < 500:
            return "medium"
        if 200 <= status_code < 400:
            return "info"
        return "low"
