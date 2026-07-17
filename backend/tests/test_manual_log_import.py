"""手工日志导入 — 端到端测试.

覆盖 FormatDetector / EvtxParser / AccessLogParser / Translator / API 路由注册.
"""

import hashlib
import os
import sys
import tempfile
from pathlib import Path

# 确保项目根在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ════════════════════════════════════════════════════════════════
# FormatDetector 测试
# ════════════════════════════════════════════════════════════════

class TestFormatDetector:
    """FormatDetector 三级检测策略测试."""

    def test_format_detector_evtx_extension(self):
        """扩展名 .evtx 应直接返回 evtx."""
        from app.parsers.format_detector import FormatDetector

        log_source, fmt = FormatDetector.detect("test.evtx", b"", [])
        assert log_source == "evtx", f"Expected evtx, got {log_source}"
        assert fmt == "evtx", f"Expected evtx, got {fmt}"

    def test_format_detector_evtx_extension_uppercase(self):
        """扩展名 .EVTX 大小写不敏感."""
        from app.parsers.format_detector import FormatDetector

        log_source, fmt = FormatDetector.detect("test.EVTX", b"", [])
        assert log_source == "evtx"
        assert fmt == "evtx"

    def test_format_detector_evtx_magic(self):
        """Magic bytes ElfFile 应返回 evtx."""
        from app.parsers.format_detector import FormatDetector

        log_source, fmt = FormatDetector.detect("test.bin", b"ElfFile\x00...", [])
        assert log_source == "evtx", f"Expected evtx, got {log_source}"
        assert fmt == "evtx"

    def test_format_detector_not_evtx_magic(self):
        """非 EVTX Magic bytes 不应返回 evtx."""
        from app.parsers.format_detector import FormatDetector

        with pytest.raises(Exception):
            FormatDetector.detect("test.bin", b"NotEvtxFile", [])

    def test_format_detector_access_nginx_combined(self):
        """Nginx Combined 格式应检测为 nginx_access."""
        from app.parsers.format_detector import FormatDetector

        nginx_line = (
            '192.168.1.1 - - [15/Jul/2025:10:30:15 +0800] '
            '"GET /index.php HTTP/1.1" 200 1234 "-" "Mozilla/5.0"'
        )
        log_source, fmt = FormatDetector.detect("access.log", None, [nginx_line])
        assert log_source == "nginx_access", f"Expected nginx_access, got {log_source}"
        assert fmt == "nginx_combined", f"Expected nginx_combined, got {fmt}"

    def test_format_detector_access_nginx_common(self):
        """Nginx Common 格式应检测为 nginx_access."""
        from app.parsers.format_detector import FormatDetector

        nginx_line = (
            '10.0.0.1 - frank [10/Oct/2025:13:55:36 +0000] '
            '"GET /api/v1/users HTTP/1.1" 200 4567'
        )
        log_source, fmt = FormatDetector.detect("access.log", None, [nginx_line])
        assert log_source == "nginx_access", f"Expected nginx_access, got {log_source}"
        assert fmt == "nginx_common", f"Expected nginx_common, got {fmt}"

    def test_format_detector_access_iis(self):
        """IIS W3C 格式应检测为 iis_access."""
        from app.parsers.format_detector import FormatDetector

        iis_lines = [
            '#Software: Microsoft Internet Information Services 10.0',
            '#Version: 1.0',
            '#Fields: date time c-ip cs-method cs-uri-stem sc-status',
            '2025-07-15 10:30:15 192.168.1.1 GET /index.html 200',
        ]
        log_source, fmt = FormatDetector.detect("u_ex.log", None, iis_lines)
        assert log_source == "iis_access", f"Expected iis_access, got {log_source}"
        assert fmt == "iis_w3c", f"Expected iis_w3c, got {fmt}"

    def test_format_detector_unsupported_raises(self):
        """不支持的格式应抛出 UnsupportedFormatError."""
        from app.parsers.format_detector import FormatDetector, UnsupportedFormatError

        with pytest.raises(UnsupportedFormatError):
            FormatDetector.detect("unknown.xyz", None, None)


# ════════════════════════════════════════════════════════════════
# EvtxParser 测试
# ════════════════════════════════════════════════════════════════

class TestEvtxParser:
    """EvtxParser 单元测试（不含真实文件解析）. """

    def test_evtx_parser_map_event_id_4625(self):
        """4625 应映射为 failed_logon / high / T1110."""
        from app.parsers.evtx_parser import EvtxParser
        event_type, event_label, severity, mitre = EvtxParser._map_event_id(4625)
        assert event_type == "failed_logon", f"Expected failed_logon, got {event_type}"
        assert severity == "high", f"Expected high, got {severity}"
        assert mitre == "T1110", f"Expected T1110, got {mitre}"

    def test_evtx_parser_map_event_id_4688(self):
        """4688 应映射为 process_creation."""
        from app.parsers.evtx_parser import EvtxParser
        event_type, event_label, severity, mitre = EvtxParser._map_event_id(4688)
        assert event_type == "process_creation", f"Expected process_creation, got {event_type}"
        assert severity == "medium", f"Expected medium, got {severity}"

    def test_evtx_parser_map_event_id_unknown(self):
        """未知 ID 应返回 unknown_{id}."""
        from app.parsers.evtx_parser import EvtxParser
        event_type, event_label, severity, mitre = EvtxParser._map_event_id(99999)
        assert event_type == "unknown_99999", f"Expected unknown_99999, got {event_type}"
        assert severity == "info", f"Expected info, got {severity}"

    def test_evtx_parser_map_event_id_0(self):
        """ID=0 应返回 unknown_0."""
        from app.parsers.evtx_parser import EvtxParser
        event_type, event_label, severity, mitre = EvtxParser._map_event_id(0)
        assert event_type == "unknown_0"


# ════════════════════════════════════════════════════════════════
# AccessLogParser 测试
# ════════════════════════════════════════════════════════════════

class TestAccessLogParser:
    """AccessLogParser 解析测试."""

    NGINX_COMBINED_LINES = [
        (
            '192.168.1.1 - - [15/Jul/2025:10:30:15 +0800] '
            '"GET /index.php HTTP/1.1" 200 1234 "-" "Mozilla/5.0 (Windows NT 10.0)"'
        ),
        (
            '10.0.0.5 - admin [15/Jul/2025:10:31:00 +0800] '
            '"POST /api/login HTTP/1.1" 401 256 "-" "curl/7.68.0"'
        ),
        (
            '172.16.0.1 - - [15/Jul/2025:10:32:00 +0800] '
            '"GET /assets/css/main.css HTTP/1.1" 304 0 '
            '"https://example.com/" "Mozilla/5.0"'
        ),
    ]

    NGINX_COMMON_LINES = [
        (
            '192.168.1.1 - - [15/Jul/2025:10:30:15 +0800] '
            '"GET /index.php HTTP/1.1" 200 1234'
        ),
        (
            '10.0.0.5 - admin [15/Jul/2025:10:31:00 +0800] '
            '"POST /api/login HTTP/1.1" 401 256'
        ),
    ]

    def test_access_log_parser_nginx_combined(self):
        """Nginx Combined 格式完整解析."""
        from app.parsers.access_log_parser import AccessLogParser

        parsed = AccessLogParser.parse(
            self.NGINX_COMBINED_LINES, "nginx_access", 1, "web01",
        )
        assert len(parsed) == 3, f"Expected 3 items, got {len(parsed)}"

        # 第一条
        item = parsed[0]
        assert item["host_id"] == 1
        assert item["hostname"] == "web01"
        assert item["log_source"] == "nginx_access"
        assert item["src_ip"] == "192.168.1.1"
        assert item["method"] == "GET"
        assert item["url"] == "/index.php"
        assert item["status_code"] == 200
        assert item["referer"] == "-"
        assert "Mozilla/5.0" in item["user_agent"]
        assert item["timestamp"] == "15/Jul/2025:10:30:15 +0800"

        # 第二条（POST 401）
        item = parsed[1]
        assert item["src_ip"] == "10.0.0.5"
        assert item["method"] == "POST"
        assert item["url"] == "/api/login"
        assert item["status_code"] == 401

        # 第三条（有 referer）
        item = parsed[2]
        assert item["referer"] == "https://example.com/"
        assert item["status_code"] == 304

    def test_access_log_parser_nginx_common(self):
        """Nginx Common 格式解析（无 user_agent / referer）. """
        from app.parsers.access_log_parser import AccessLogParser

        parsed = AccessLogParser.parse(
            self.NGINX_COMMON_LINES, "nginx_access", 2, "web02",
        )
        assert len(parsed) == 2, f"Expected 2 items, got {len(parsed)}"

        item = parsed[0]
        assert item["host_id"] == 2
        assert item["hostname"] == "web02"
        assert item["src_ip"] == "192.168.1.1"
        assert item["status_code"] == 200

        # Common 格式中 user_agent / referer 应为 "-"（默认值）
        assert item["user_agent"] == "-"
        assert item["referer"] == "-"

    def test_access_log_parser_iis_w3c(self):
        """IIS W3C 格式解析."""
        from app.parsers.access_log_parser import AccessLogParser

        lines = [
            '#Software: Microsoft Internet Information Services 10.0',
            '#Version: 1.0',
            '#Fields: date time c-ip cs-method cs-uri-stem cs-uri-query sc-status sc-bytes cs(User-Agent) cs(Referer)',
            '2025-07-15 10:30:15 192.168.1.1 GET /index.html - 200 12345 Mozilla/5.0 -',
            '2025-07-15 10:31:00 10.0.0.5 POST /api/login - 401 256 curl/7.68 -',
        ]
        parsed = AccessLogParser.parse(lines, "iis_access", 3, "iis01")
        assert len(parsed) == 2, f"Expected 2 items, got {len(parsed)}"

        item = parsed[0]
        assert item["src_ip"] == "192.168.1.1"
        assert item["method"] == "GET"
        assert item["url"] == "/index.html"
        assert item["status_code"] == 200
        assert item["body_bytes"] == 12345

        item = parsed[1]
        assert item["src_ip"] == "10.0.0.5"
        assert item["method"] == "POST"
        assert item["status_code"] == 401

    def test_access_log_parser_detect_format(self):
        """detect_format 应返回正确的格式名."""
        from app.parsers.access_log_parser import AccessLogParser

        fmt = AccessLogParser.detect_format(self.NGINX_COMBINED_LINES[:1])
        assert fmt == "nginx_combined", f"Expected nginx_combined, got {fmt}"

        fmt = AccessLogParser.detect_format(self.NGINX_COMMON_LINES[:1])
        assert fmt == "nginx_common", f"Expected nginx_common, got {fmt}"

        iis_header = ['#Fields: date time c-ip cs-method cs-uri-stem sc-status']
        fmt = AccessLogParser.detect_format(iis_header)
        assert fmt == "iis_w3c", f"Expected iis_w3c, got {fmt}"


# ════════════════════════════════════════════════════════════════
# Syslog 解析器测试
# ════════════════════════════════════════════════════════════════

class TestSyslogParser:
    """Syslog 解析器测试（RFC 3164 / RFC 5424）. """

    def test_syslog_parse_rfc3164(self):
        from app.parsers.syslog_parser import parse_line
        r = parse_line('<13>Oct 15 10:30:15 webserver sshd[1234]: Failed password for root from 10.0.0.1')
        assert r is not None
        assert r["log_source"] == "syslog_rfc3164"
        assert r["severity"] == "low"       # PRI=13 → severity 5(notice)
        assert r["tag"] == "sshd[1234]"
        assert r["hostname"] == "webserver"
        assert "10.0.0.1" in r["message"]

    def test_syslog_parse_rfc5424(self):
        from app.parsers.syslog_parser import parse_line
        r = parse_line('<14>1 2025-07-16T10:30:15Z webserver sshd 1234 - [example@0] Failed password')
        assert r is not None
        assert r["log_source"] == "syslog_rfc5424"
        assert r["version"] == 1
        assert r["app_name"] == "sshd"
        assert r["severity"] == "info"      # PRI=14 → severity 6(info)

    def test_syslog_parse_invalid(self):
        from app.parsers.syslog_parser import parse_line
        r = parse_line("just a normal line without PRI")
        assert r is None

    def test_syslog_parse_empty_line(self):
        from app.parsers.syslog_parser import parse_line
        r = parse_line("")
        assert r is None

    def test_syslog_parse_batch(self):
        from app.parsers.syslog_parser import SyslogParser
        lines = [
            '<13>Oct 15 10:30:15 server1 sshd: Failed password',
            '<14>1 2025-07-16T10:30:15Z server2 sshd 1 - - Test',
        ]
        results = SyslogParser.parse(lines, "syslog", 1, "test-pc")
        assert len(results) == 2

    def test_syslog_parse_high_severity(self):
        from app.parsers.syslog_parser import parse_line
        r = parse_line('<2>Oct 15 10:30:15 fw1 ACL: denied')  # PRI=2 → severity 2(critical) → critical
        assert r is not None
        assert r["severity"] == "critical"

    def test_syslog_translator(self):
        from app.parsers.syslog_parser import SyslogParser
        from app.parsers.translator import Translator
        lines = ['<13>Oct 15 10:30:15 webserver sshd[1234]: Failed password']
        items = SyslogParser.parse(lines, "syslog", 1, "test-pc")
        events = Translator.translate(items, 1)
        assert len(events) == 1
        assert events[0]["event_type"] == "syslog"
        assert "tag" in events[0]["evidence"]
        assert "message" in events[0]["evidence"]


# ════════════════════════════════════════════════════════════════
# Translator 测试
# ════════════════════════════════════════════════════════════════

class TestTranslator:
    """Translator 翻译与推断测试."""

    def test_translator_translate_evtx(self):
        """EVTX 条目应翻译为 SecurityEvent 格式."""
        from app.parsers.translator import Translator

        evtx_item = {
            "host_id": 1,
            "hostname": "win01",
            "log_source": "evtx",
            "event_id": 4625,
            "event_type": "failed_logon",
            "event_label": "登录失败",
            "severity": "high",
            "mitre_attack": "T1110",
            "timestamp": "2025-07-16T10:30:00Z",
            "raw_data": {
                "IpAddress": "10.0.0.5",
                "TargetUserName": "admin",
                "ProcessName": "C:\\Windows\\System32\\svchost.exe",
                "description": "Failed logon attempt for admin from 10.0.0.5",
            },
        }
        translated = Translator.translate([evtx_item], 1)
        assert len(translated) == 1, f"Expected 1 item, got {len(translated)}"

        t = translated[0]
        assert t["event_type"] == "failed_logon"
        assert t["severity"] == "high"
        assert t["source_collector"] == "manual_import"
        assert t["id"].startswith("manual:")
        assert t["event_key"] is not None and len(t["event_key"]) == 16

        # 验证 evidence 结构
        ev = t["evidence"]
        assert ev["src_ip"] == "10.0.0.5"
        assert ev["user_name"] == "admin"
        assert ev["process_name"] == "C:\\Windows\\System32\\svchost.exe"
        assert ev["event_id"] == 4625
        assert ev["description"] == "Failed logon attempt for admin from 10.0.0.5"

    def test_translator_translate_access(self):
        """Access Log 条目应翻译为 SecurityEvent 格式."""
        from app.parsers.translator import Translator

        access_item = {
            "host_id": 1,
            "hostname": "web01",
            "log_source": "nginx_access",
            "event_type": "web_access",
            "severity": "info",
            "src_ip": "192.168.1.1",
            "method": "POST",
            "url": "/admin/upload.php",
            "status_code": 403,
            "referer": "https://example.com/admin/",
            "user_agent": "curl/7.68.0",
            "timestamp": "15/Jul/2025:10:30:15 +0800",
        }
        translated = Translator.translate([access_item], 1)
        assert len(translated) == 1, f"Expected 1 item, got {len(translated)}"

        t = translated[0]
        assert t["event_type"] == "web_access"
        # 403 → medium
        assert t["severity"] == "medium", f"Expected medium for 403, got {t['severity']}"
        assert t["source_collector"] == "manual_import"

        ev = t["evidence"]
        assert ev["url"] == "/admin/upload.php"
        assert ev["method"] == "POST"
        assert ev["status_code"] == 403
        assert ev["user_agent"] == "curl/7.68.0"
        assert ev["src_ip"] == "192.168.1.1"

    def test_translator_translate_access_200(self):
        """200 响应应推断为 info 级别."""
        from app.parsers.translator import Translator

        item = {
            "log_source": "nginx_access",
            "src_ip": "1.1.1.1",
            "method": "GET",
            "url": "/",
            "status_code": 200,
            "referer": "-",
            "user_agent": "test",
            "timestamp": "now",
        }
        translated = Translator.translate([item], 1)
        assert translated[0]["severity"] == "info"

    def test_translator_translate_empty(self):
        """空列表应返回空列表"""
        from app.parsers.translator import Translator
        assert Translator.translate([], 1) == []

    def test_translator_infer_severity(self):
        """状态码 → 严重度映射."""
        from app.parsers.translator import Translator

        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 500}) == "high"
        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 502}) == "high"
        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 404}) == "medium"
        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 403}) == "medium"
        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 200}) == "info"
        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 302}) == "info"
        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 100}) == "low"
        assert Translator.infer_severity({"log_source": "nginx_access", "status_code": 0}) == "low"
        # EVTX 直接取 severity 字段
        assert Translator.infer_severity({"log_source": "evtx", "severity": "critical"}) == "critical"
        assert Translator.infer_severity({"log_source": "evtx", "severity": "low"}) == "low"

    def test_translator_make_dedup_key_consistency(self):
        """相同输入应生成相同 key."""
        from app.parsers.translator import Translator

        key1 = Translator.make_dedup_key("evtx", 1, "4625:2025-07-16:logon")
        key2 = Translator.make_dedup_key("evtx", 1, "4625:2025-07-16:logon")
        assert key1 == key2, "Same input should produce same key"
        assert len(key1) == 16, f"Expected 16 chars, got {len(key1)}"

    def test_translator_make_dedup_key_different(self):
        """不同输入应生成不同 key."""
        from app.parsers.translator import Translator

        key1 = Translator.make_dedup_key("evtx", 1, "4625:2025-07-16:logon")
        key2 = Translator.make_dedup_key("evtx", 1, "4625:2025-07-17:logon")
        key3 = Translator.make_dedup_key("nginx", 1, "4625:2025-07-16:logon")
        assert key1 != key2, "Different event_key should produce different key"
        assert key1 != key3, "Different log_source should produce different key"
        assert key2 != key3, "Different inputs should produce different keys"

    def test_translator_make_dedup_key_format(self):
        """key 应为 16 字符十六进制字符串."""
        from app.parsers.translator import Translator
        key = Translator.make_dedup_key("test", 1, "data")
        assert len(key) == 16
        # 应为合法的十六进制
        int(key, 16)


# ════════════════════════════════════════════════════════════════
# 导入记录模型测试
# ════════════════════════════════════════════════════════════════

class TestImportRecordExtensions:
    """ImportRecord 扩展字段测试."""

    def test_import_record_update_status_with_error(self):
        """update_status 应支持 error_message 参数."""
        from app.models.import_record import ImportRecord

        # 该方法不依赖数据库连接 —— 验证函数签名包含 error_message
        import inspect
        sig = inspect.signature(ImportRecord.update_status)
        assert "error_message" in sig.parameters, "error_message param missing"

    def test_import_record_create_optional_params(self):
        """create 应支持新增的可选参数."""
        from app.models.import_record import ImportRecord
        import inspect
        sig = inspect.signature(ImportRecord.create)
        for param in ("log_type", "file_size", "parsed_count", "event_count", "task_id"):
            assert param in sig.parameters, f"{param} param missing in create()"
            # 验证有默认值（可选）
            assert sig.parameters[param].default is not inspect.Parameter.empty


# ════════════════════════════════════════════════════════════════
# API 路由注册测试
# ════════════════════════════════════════════════════════════════

class TestImportLogsApiHealth:
    """API 路由注册验证."""

    def test_import_logs_api_router_imports(self):
        """import_logs API 模块应正确导入."""
        from app.api.import_logs import router
        assert router is not None
        # 检查路由数量
        routes = [r for r in router.routes if hasattr(r, "path")]
        assert len(routes) >= 4, f"Expected at least 4 routes, got {len(routes)}"

    def test_import_logs_api_routes_registered(self):
        """验证 import-logs 路由已注册到 app."""
        from app.main import app
        import_log_routes = [
            r.path for r in app.routes
            if hasattr(r, "path") and "import-logs" in r.path
        ]
        assert len(import_log_routes) >= 4, (
            f"Expected at least 4 import-logs routes, got {len(import_log_routes)}: "
            f"{import_log_routes}"
        )
        # 验证 4 个端点
        paths = set(import_log_routes)
        has_upload = any(
            p.endswith("/import-logs") and "{host_id}" in p
            for p in paths
        )
        has_records = any("import-logs/records" in p for p in paths)
        has_detail = any("records/" in p for p in paths)
        has_task = any("tasks/" in p for p in paths)
        assert has_upload, "Upload route not found"
        assert has_records, "Records list route not found"
        assert has_detail, "Record detail route not found"
        assert has_task, "Task status route not found"


# ════════════════════════════════════════════════════════════════
# 导入结果模型测试
# ════════════════════════════════════════════════════════════════

class TestImportResultModel:
    """ImportResult CRUD 结构验证."""

    def test_import_result_methods_exist(self):
        """ImportResult 应包含全部 CRUD 方法."""
        from app.models.import_result import ImportResult

        assert hasattr(ImportResult, "create")
        assert hasattr(ImportResult, "get_by_id")
        assert hasattr(ImportResult, "list_by_import")
        assert hasattr(ImportResult, "count_by_import")
        assert hasattr(ImportResult, "delete_by_import")


# ════════════════════════════════════════════════════════════════
# parsers 包完整性测试
# ════════════════════════════════════════════════════════════════

class TestParsersPackage:
    """parsers 包完整性验证."""

    def test_parsers_all_exports(self):
        """__init__ 应导出全部公开类."""
        from app.parsers import (
            FormatDetector, UnsupportedFormatError,
            EvtxParser, AccessLogParser, FORMAT_TEMPLATES, Translator,
            SyslogParser, parse_syslog_line,
        )
        assert FormatDetector is not None
        assert UnsupportedFormatError is not None
        assert EvtxParser is not None
        assert AccessLogParser is not None
        assert FORMAT_TEMPLATES is not None
        assert Translator is not None
        assert SyslogParser is not None
        assert parse_syslog_line is not None

    def test_format_templates_shared(self):
        """FORMAT_TEMPLATES 在 access_log_parser 和 __init__ 间共享."""
        from app.parsers import FORMAT_TEMPLATES
        from app.parsers.access_log_parser import FORMAT_TEMPLATES as FT2
        assert FORMAT_TEMPLATES is FT2

    def test_unsupported_format_error(self):
        """UnsupportedFormatError 应携带文件名."""
        from app.parsers.format_detector import UnsupportedFormatError
        err = UnsupportedFormatError("test.xyz", "reason")
        assert "test.xyz" in str(err)
        assert "reason" in str(err)
        assert err.filename == "test.xyz"


# 需要 pytest
import pytest
