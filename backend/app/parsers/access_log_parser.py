"""Access Log 解析器 — 支持 Nginx / Apache / IIS W3C / Tomcat 格式.

FORMAT_TEMPLATES 作为模块级共享常量，同时被 FormatDetector 引用。
"""

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Access Log 格式正则模板 ──────────────────────────────
# 所有正则均以 ^ 开头，包含命名捕获组
FORMAT_TEMPLATES: dict[str, Optional[str]] = {
    # Nginx Combined: $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
    "nginx_combined": (
        r'^(?P<src_ip>\S+)\s+'
        r'(?P<ident>\S+)\s+'
        r'(?P<auth_user>\S+)\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+'
        r'(?P<url>\S+)\s+'
        r'(?P<protocol>\S+)"\s+'
        r'(?P<status_code>\d+)\s+'
        r'(?P<body_bytes>\d+)\s+'
        r'"(?P<referer>[^"]*)"\s+'
        r'"(?P<user_agent>[^"]*)"'
    ),
    # Nginx Common: $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent
    "nginx_common": (
        r'^(?P<src_ip>\S+)\s+'
        r'(?P<ident>\S+)\s+'
        r'(?P<auth_user>\S+)\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+'
        r'(?P<url>\S+)\s+'
        r'(?P<protocol>\S+)"\s+'
        r'(?P<status_code>\d+)\s+'
        r'(?P<body_bytes>\d+)'
    ),
    # Apache Combined (同 Nginx Combined 格式, 来源标记不同)
    "apache_combined": (
        r'^(?P<src_ip>\S+)\s+'
        r'(?P<ident>\S+)\s+'
        r'(?P<auth_user>\S+)\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+'
        r'(?P<url>\S+)\s+'
        r'(?P<protocol>\S+)"\s+'
        r'(?P<status_code>\d+)\s+'
        r'(?P<body_bytes>\d+)\s+'
        r'"(?P<referer>[^"]*)"\s+'
        r'"(?P<user_agent>[^"]*)"'
    ),
    # Apache Common (同 Nginx Common 格式)
    "apache_common": (
        r'^(?P<src_ip>\S+)\s+'
        r'(?P<ident>\S+)\s+'
        r'(?P<auth_user>\S+)\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+'
        r'(?P<url>\S+)\s+'
        r'(?P<protocol>\S+)"\s+'
        r'(?P<status_code>\d+)\s+'
        r'(?P<body_bytes>\d+)'
    ),
    # Tomcat Access (Common Log Format)
    "tomcat_access": (
        r'^(?P<src_ip>\S+)\s+'
        r'(?P<ident>\S+)\s+'
        r'(?P<auth_user>\S+)\s+'
        r'\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+'
        r'(?P<url>\S+)\s+'
        r'(?P<protocol>\S+)"\s+'
        r'(?P<status_code>\d+)\s+'
        r'(?P<body_bytes>\d+)'
    ),
    # IIS W3C — 动态构建（从 #Fields: 行解析字段名）
    "iis_w3c": None,
}


class AccessLogParser:
    """Access Log 解析器.

    支持 Nginx (combined/common)、Apache (combined/common)、
    IIS W3C Extended、Tomcat Access 共 6 种格式。
    """

    # 引用模块级共享模板
    FORMAT_TEMPLATES = FORMAT_TEMPLATES

    @classmethod
    def detect_format(cls, first_lines: list[str]) -> Optional[str]:
        """根据首行内容检测 Access Log 格式.

        Args:
            first_lines: 日志文件的前若干行。

        Returns:
            str | None: 格式名称（如 'nginx_combined'），无法识别返回 None。
        """
        for line in first_lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # IIS W3C 有 #Fields: 头
            if line_stripped.startswith("#Fields:"):
                return "iis_w3c"

            # 尝试匹配各格式正则
            for fmt_name, pattern in cls.FORMAT_TEMPLATES.items():
                if pattern is None:
                    continue
                m = re.match(pattern, line_stripped)
                if m:
                    return fmt_name

        return None

    @classmethod
    def parse(
        cls,
        lines: list[str],
        log_source: str,
        host_id: int,
        hostname: str,
    ) -> list[dict[str, Any]]:
        """解析 Access Log 行列表.

        Args:
            lines: 日志行列表。
            log_source: 日志来源（如 'nginx_access', 'iis_access'）。
            host_id: 主机 ID。
            hostname: 主机名。

        Returns:
            list[dict]: 解析后的日志条目列表。
        """
        fmt_name = log_source.replace("_access", "").replace("iis", "iis_w3c")
        # 纠正映射：iis → iis_w3c, nginx → nginx_combined/nginx_common, apache → apache_combined/apache_common
        if fmt_name == "iis_w3c":
            return cls._parse_iis_w3c(lines, host_id, hostname)

        # 尝试 combined 优先，fallback 到 common
        combined_key = f"{fmt_name}_combined"
        common_key = f"{fmt_name}_common"

        combined_pattern = cls.FORMAT_TEMPLATES.get(combined_key)
        common_pattern = cls.FORMAT_TEMPLATES.get(common_key)

        results: list[dict[str, Any]] = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                continue

            m = None
            used_pattern = None
            if combined_pattern:
                m = re.match(combined_pattern, line_stripped)
                if m:
                    used_pattern = combined_key

            if m is None and common_pattern:
                m = re.match(common_pattern, line_stripped)
                if m:
                    used_pattern = common_key

            if m is None:
                logger.debug("Line did not match %s/%s: %s", combined_key, common_key, line_stripped[:80])
                continue

            item = cls._build_item(m, log_source, host_id, hostname)
            results.append(item)

        return results

    @classmethod
    def _parse_iis_w3c(
        cls,
        lines: list[str],
        host_id: int,
        hostname: str,
    ) -> list[dict[str, Any]]:
        """解析 IIS W3C Extended 格式.

        从 #Fields: 行获取列名，后续行按列名解析。
        """
        fields: list[str] = []
        results: list[dict[str, Any]] = []

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            if line_stripped.startswith("#Fields:"):
                # 提取字段名
                fields = re.split(r"\s+", line_stripped[len("#Fields:"):].strip())
                continue

            if line_stripped.startswith("#"):
                continue

            if not fields:
                continue

            values = re.split(r"\s+", line_stripped)
            # IIS W3C 使用 - 表示空值
            row: dict[str, str] = {}
            for i, fname in enumerate(fields):
                row[fname.lower()] = values[i] if i < len(values) and values[i] != "-" else ""

            timestamp = row.get("date", "") + " " + row.get("time", "")

            # 从 IIS 自定义字段中提取 X-Forwarded-For
            xff = row.get("cs(x-forwarded-for)", row.get("x-forwarded-for", ""))

            results.append({
                "host_id": host_id,
                "hostname": hostname,
                "log_source": "iis_access",
                "event_type": "web_access",
                "severity": "info",
                "src_ip": row.get("c-ip", ""),
                "method": row.get("cs-method", ""),
                "url": row.get("cs-uri-stem", "") + (("?" + row.get("cs-uri-query", "")) if row.get("cs-uri-query") else ""),
                "status_code": int(row.get("sc-status", 0)) if row.get("sc-status", "").isdigit() else 0,
                "referer": row.get("cs(referer)", ""),
                "user_agent": row.get("cs(user-agent)", ""),
                "timestamp": timestamp.strip(),
                "protocol": row.get("cs-version", ""),
                "body_bytes": int(row.get("sc-bytes", 0)) if row.get("sc-bytes", "").isdigit() else 0,
                "x_forwarded_for": xff,
            })

        return results

    @classmethod
    def _build_item(
        cls,
        match: re.Match,
        log_source: str,
        host_id: int,
        hostname: str,
    ) -> dict[str, Any]:
        """从正则匹配结果构建输出字典."""
        gd = match.groupdict()
        return {
            "host_id": host_id,
            "hostname": hostname,
            "log_source": log_source,
            "event_type": "web_access",
            "severity": "info",
            "src_ip": gd.get("src_ip", ""),
            "method": gd.get("method", ""),
            "url": gd.get("url", ""),
            "status_code": int(gd.get("status_code", 0)) if gd.get("status_code", "").isdigit() else 0,
            "referer": gd.get("referer", "-"),
            "user_agent": gd.get("user_agent", "-"),
            "timestamp": gd.get("timestamp", ""),
            "protocol": gd.get("protocol", ""),
            "body_bytes": int(gd.get("body_bytes", 0)) if gd.get("body_bytes", "").isdigit() else 0,
            "ident": gd.get("ident", "-"),
            "auth_user": gd.get("auth_user", "-"),
            "x_forwarded_for": gd.get("x_forwarded_for", ""),
        }
