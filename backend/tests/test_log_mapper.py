"""LogMapper 单元测试."""

import json
from datetime import datetime, timezone
from app.services.event_normalizer import LogMapper, _MAPPERS, normalize_single, validate_schema


class TestLogMapper:
    """LogMapper 映射逻辑测试."""

    def setup_method(self):
        self.mapper = LogMapper()

    def test_event_types(self):
        """验证 event_types 正确声明."""
        assert self.mapper.event_types == ["log_event"]

    # 1. Win EventLog 4624（登录成功）
    def test_windows_4624(self):
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Security",
               "event_id": "4624", "time": "2026-07-06T10:30:00", "type": "Audit Success",
               "source": "Microsoft Windows security auditing.", "computer": "PC-01",
               "description": "登录成功"}
        result = self.mapper.map(raw)
        assert result["event_type"] == "log_event"
        assert result["event_key"] == "Security/4624"
        assert result["severity"] == "info"
        assert result["timestamp"] == "2026-07-06T10:30:00"
        assert result["source_collector"] == "windows_eventlog"
        assert result["evidence"]["log_name"] == "Security"
        assert result["evidence"]["event_id"] == "4624"
        assert result["evidence"]["description"] == "登录成功"

    # 2. Win EventLog 4672（特殊特权 — high 严重度）
    def test_windows_4672(self):
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Security",
               "event_id": "4672", "time": "2026-07-06T12:00:00"}
        result = self.mapper.map(raw)
        assert result["severity"] == "high"

    # 3. 未知 Event ID → fallback severity=info
    def test_unknown_event_id(self):
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "System",
               "event_id": "9999", "time": "2026-07-06T10:30:00"}
        result = self.mapper.map(raw)
        assert result["severity"] == "info"
        assert result["event_key"] == "System/9999"

    # 4. Linux syslog 路径
    def test_linux_syslog(self):
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "syslog",
               "raw": "Jul  6 10:30:00 server sshd[1234]: Failed password",
               "source": "/var/log/auth.log", "_fallback_ts": "2026-07-06T10:30:00"}
        result = self.mapper.map(raw)
        assert result["source_collector"] == "linux_journal"
        assert result["evidence"]["raw"] == raw["raw"]
        assert result["evidence"]["source"] == "/var/log/auth.log"

    # 5. 空 dict → 不抛异常
    def test_empty_dict(self):
        result = self.mapper.map({"event_type": "log_event", "host_id": 1})
        assert result is not None
        assert result["event_key"] == "unknown/unknown"
        assert result["severity"] == "info"
        assert "_raw_extra" in result["evidence"]

    # 6. _MAPPERS 注册验证
    def test_mappers_registered(self):
        mapper_types = [type(m).__name__ for m in _MAPPERS]
        assert "LogMapper" in mapper_types

    # 7. validate_schema 通过 log_event
    def test_validate_schema(self):
        valid, _ = validate_schema({"event_type": "log_event", "host_id": 1, "timestamp": "2026-07-06T10:30:00"})
        assert valid

    # 8. normalize_single 完整通路
    def test_normalize_single(self):
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Security",
               "event_id": "4624", "time": "2026-07-06T10:30:00"}
        event = normalize_single(raw, validate=True)
        assert event is not None
        assert event.event_type == "log_event"
        assert event.event_key == "Security/4624"


class TestLogFlatten:
    """日志展平逻辑测试（模拟 import_service 中的代码）."""

    def test_dict_flatten(self):
        data = {"logs": {"system": [{"event_id": "1001"}], "security": [{"event_id": "4624"}]}}
        logs_data = data.get("logs", {})
        if isinstance(logs_data, dict):
            flat = []
            for log_name, entries in logs_data.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            entry.setdefault("log_name", log_name)
                            flat.append(entry)
            data["logs"] = flat
        assert len(data["logs"]) == 2
        assert data["logs"][0]["log_name"] == "system"
        assert data["logs"][1]["log_name"] == "security"

    def test_empty_dict(self):
        data = {"logs": {}}
        logs_data = data.get("logs", {})
        if isinstance(logs_data, dict):
            flat = []
            for log_name, entries in logs_data.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            entry.setdefault("log_name", log_name)
                            flat.append(entry)
            data["logs"] = flat
        assert data["logs"] == []

    def test_already_list(self):
        """如果 logs 已经是 list，展平逻辑不应修改."""
        data = {"logs": [{"event_id": "4624"}]}
        logs_data = data.get("logs", {})
        if isinstance(logs_data, dict):
            flat = []
            for log_name, entries in logs_data.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            entry.setdefault("log_name", log_name)
                            flat.append(entry)
            data["logs"] = flat
        # 如果不是 dict（即 list），展平逻辑不会执行，data["logs"] 保持原样
        assert len(data["logs"]) == 1
