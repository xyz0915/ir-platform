"""LogMapper 单元测试."""

import json
import os
from datetime import datetime, timezone
from app.services.event_normalizer import (
    LogMapper, _MAPPERS, normalize_single, normalize_batch, validate_schema,
)


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


# ═══════════════════════════════════════════════════════════════
# 扩展测试 — Edward (QA)
# ═══════════════════════════════════════════════════════════════


class TestLogMapperEdge:
    """边界情况测试：event_id 类型兼容性."""

    def setup_method(self):
        self.mapper = LogMapper()

    # a) event_id 为 int → 应被 str() 正确转换
    def test_event_id_as_int(self):
        """event_id 是 int 而非 str，应自动转换."""
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Security",
               "event_id": 4624, "time": "2026-07-06T10:30:00"}
        result = self.mapper.map(raw)
        assert result["event_type"] == "log_event"
        assert result["event_key"] == "Security/4624"
        assert result["evidence"]["event_id"] == "4624"
        assert result["severity"] == "info"

    def test_event_id_as_int_4672(self):
        """int event_id=4672 应映射为 high severity."""
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Security",
               "event_id": 4672, "time": "2026-07-06T12:00:00"}
        result = self.mapper.map(raw)
        assert result["severity"] == "high"
        assert result["event_key"] == "Security/4672"

    def test_event_id_as_int_4625(self):
        """int event_id=4625 应映射为 medium severity."""
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Security",
               "event_id": 4625, "time": "2026-07-06T12:00:00"}
        result = self.mapper.map(raw)
        assert result["severity"] == "medium"
        assert result["event_key"] == "Security/4625"

    def test_event_id_as_none(self):
        """event_id 为 None → event_key 应为 'unknown/unknown'."""
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Security",
               "event_id": None, "time": "2026-07-06T10:30:00"}
        result = self.mapper.map(raw)
        assert result["event_key"] == "Security/unknown"
        assert result["evidence"]["event_id"] is None

    def test_event_id_missing(self):
        """完全缺少 event_id → event_key 应为 unknown."""
        raw = {"event_type": "log_event", "host_id": 1, "log_name": "Application",
               "time": "2026-07-06T10:30:00"}
        result = self.mapper.map(raw)
        assert result["event_key"] == "Application/unknown"
        assert result["severity"] == "info"

    def test_log_name_missing(self):
        """缺少 log_name → 默认 unknown."""
        raw = {"event_type": "log_event", "host_id": 1,
               "event_id": "4624", "time": "2026-07-06T10:30:00"}
        result = self.mapper.map(raw)
        assert result["event_key"] == "unknown/4624"
        assert result["evidence"]["log_name"] == "unknown"

    def test_timestamp_fallback(self):
        """没有 timestamp/time/_fallback_ts → 使用当前时间."""
        raw = {"event_type": "log_event", "host_id": 1,
               "log_name": "System", "event_id": "9999"}
        result = self.mapper.map(raw)
        assert result["timestamp"]  # 非空即有值
        # 解析验证是合法 ISO 格式
        parsed = datetime.fromisoformat(result["timestamp"])
        assert parsed is not None


class TestLogMapperBatch:
    """批量归一化测试."""

    def test_batch_50_logs(self):
        """50 条日志条目通过 normalize_batch 批量处理，全部成功."""
        entries = []
        for i in range(50):
            entries.append({
                "event_type": "log_event",
                "host_id": 1,
                "log_name": "Security" if i % 2 == 0 else "System",
                "event_id": str(4624 + i),  # 不同 event_id
                "time": f"2026-07-06T10:{(i % 60):02d}:00",
                "host_id": 1,
            })
        events = normalize_batch(entries, validate=True)
        assert len(events) == 50, f"期望 50 ��事件，实际 {len(events)}"
        # 验证所有事件类型正确
        for ev in events:
            assert ev.event_type == "log_event"
            assert ev.source_collector == "windows_eventlog"
            assert ev.host_id == 1

    def test_batch_mixed_valid_invalid(self):
        """混合有效和无效事件 -> 仅有效事件被保留."""
        entries = [
            {"event_type": "log_event", "host_id": 1, "log_name": "Security",
             "event_id": "4624", "time": "2026-07-06T10:30:00"},
            {"event_type": "log_event", "host_id": 1, "log_name": "System",
             "event_id": "9999", "time": "2026-07-06T10:31:00"},
            {"event_type": "unknown_type", "host_id": 1},  # 无效 event_type
            {"host_id": 1, "time": "2026-07-06T10:32:00"},  # 缺少 event_type
            {"event_type": "log_event", "host_id": 1, "log_name": "Security",
             "event_id": "4672", "time": "2026-07-06T10:33:00"},
        ]
        events = normalize_batch(entries, validate=True)
        assert len(events) == 3, f"期望 3 个有效事件，实际 {len(events)}"
        assert events[0].event_key == "Security/4624"
        assert events[1].event_key == "System/9999"
        assert events[2].event_key == "Security/4672"

    def test_batch_empty(self):
        """空列表 -> 空结果."""
        events = normalize_batch([], validate=True)
        assert events == []


class TestLogMapperFullPipeline:
    """展平 + 归一化全链路测试（模拟 import_service 中的完整流程）."""

    def _simulate_import_pipeline(self, logs_dict: dict, host_id: int = 1):
        """模拟 import_service 中 logs 展平 + 事件归一化的完整流程."""
        from app.services.event_normalizer import normalize_batch

        # Step 1: 展平 logs dict → list（同 import_service.py 第 268-278 行）
        if isinstance(logs_dict, dict):
            flat_logs = []
            for log_name, entries in logs_dict.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            entry.setdefault("log_name", log_name)
                            flat_logs.append(entry)
        else:
            flat_logs = logs_dict if isinstance(logs_dict, list) else []

        # Step 2: 赋 event_type 和 host_id
        raw_events = []
        for item in flat_logs:
            if isinstance(item, dict):
                item["event_type"] = "log_event"
                item["host_id"] = host_id
                raw_events.append(item)

        # Step 3: 批量归一化
        return normalize_batch(raw_events, validate=False)

    def test_full_pipeline_security_logs(self):
        """完整模拟：Security 和 System 日志展平 → 归一化."""
        logs = {
            "Security": [
                {"event_id": "4624", "time": "2026-07-06T10:30:00",
                 "type": "Audit Success", "description": "登录成功"},
                {"event_id": "4672", "time": "2026-07-06T10:30:05",
                 "description": "特殊特权分配"},
                {"event_id": "4625", "time": "2026-07-06T10:31:00",
                 "description": "登录失败"},
            ],
            "System": [
                {"event_id": "9999", "time": "2026-07-06T11:00:00"},
            ],
        }
        events = self._simulate_import_pipeline(logs)

        assert len(events) == 4

        # Security/4624 → info
        assert events[0].event_type == "log_event"
        assert events[0].event_key == "Security/4624"
        assert events[0].severity == "info"
        assert events[0].source_collector == "windows_eventlog"

        # Security/4672 → high
        assert events[1].event_key == "Security/4672"
        assert events[1].severity == "high"

        # Security/4625 → medium
        assert events[2].event_key == "Security/4625"
        assert events[2].severity == "medium"

        # System/9999 → info (unknown event_id fallback)
        assert events[3].event_key == "System/9999"
        assert events[3].severity == "info"

    def test_full_pipeline_linux_syslog(self):
        """完整模拟：Linux syslog 日志."""
        logs = {
            "syslog": [
                {"raw": "Jul  6 10:30:00 server sshd[1234]: Failed password",
                 "source": "/var/log/auth.log",
                 "_fallback_ts": "2026-07-06T10:30:00"},
                {"raw": "Jul  6 10:31:00 server sudo: session opened",
                 "source": "/var/log/auth.log",
                 "_fallback_ts": "2026-07-06T10:31:00"},
            ],
        }
        events = self._simulate_import_pipeline(logs)

        assert len(events) == 2
        for ev in events:
            assert ev.event_type == "log_event"
            assert ev.source_collector == "linux_journal"
            assert ev.host_id == 1
        assert "raw" in events[0].evidence
        assert events[0].evidence["source"] == "/var/log/auth.log"

    def test_full_pipeline_empty_logs(self):
        """空 logs dict → 空结果."""
        events = self._simulate_import_pipeline({})
        assert events == []

    def test_full_pipeline_already_flat_list(self):
        """logs 已经是 list（非 dict）→ 直接归一化."""
        logs = [
            {"log_name": "Security", "event_id": "4624",
             "time": "2026-07-06T10:30:00"},
            {"log_name": "Security", "event_id": "4672",
             "time": "2026-07-06T10:31:00"},
        ]
        events = self._simulate_import_pipeline(logs)
        assert len(events) == 2
        assert events[0].event_key == "Security/4624"
        assert events[1].event_key == "Security/4672"


class TestLogMapperDbEndToEnd:
    """数据库端到端验证（可选 — 需要 DB 可写）."""

    def test_db_insert_log_event(self):
        """直接 INSERT security_events 表验证 log_event 持久化."""
        import sqlite3
        from app.config import settings

        test_id = "test_log_event_e2e"
        conn = sqlite3.connect(settings.DB_PATH)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO security_events
                   (id, timestamp, host_id, event_type, severity,
                    source_collector, event_key, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (test_id, "2026-07-06T10:30:00", 1, "log_event", "info",
                 "windows_eventlog", "Security/4624",
                 json.dumps({"event_id": "4624", "log_name": "Security"})),
            )
            conn.commit()

            # 验证已写入
            row = conn.execute(
                "SELECT id, event_type, event_key, severity FROM security_events WHERE id=?",
                (test_id,),
            ).fetchone()
            assert row is not None, "DB 中未找到刚插入的记录"
            assert row[1] == "log_event"
            assert row[2] == "Security/4624"
            assert row[3] == "info"
        finally:
            # 清理测试数据
            conn.execute("DELETE FROM security_events WHERE id=?", (test_id,))
            conn.commit()
            conn.close()

    def test_db_insert_log_event_high_severity(self):
        """DB 写/读验证：4672 high severity."""
        import sqlite3
        from app.config import settings

        test_id = "test_log_event_e2e_4672"
        conn = sqlite3.connect(settings.DB_PATH)
        try:
            conn.execute(
                """INSERT OR IGNORE INTO security_events
                   (id, timestamp, host_id, event_type, severity,
                    source_collector, event_key, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (test_id, "2026-07-06T12:00:00", 1, "log_event", "high",
                 "windows_eventlog", "Security/4672",
                 json.dumps({"event_id": "4672", "log_name": "Security"})),
            )
            conn.commit()

            row = conn.execute(
                "SELECT severity FROM security_events WHERE id=?", (test_id,),
            ).fetchone()
            assert row is not None
            assert row[0] == "high"
        finally:
            conn.execute("DELETE FROM security_events WHERE id=?", (test_id,))
            conn.commit()
            conn.close()

    def test_db_insert_idempotent(self):
        """INSERT OR IGNORE 幂等性验证：重复 ID 不报错."""
        import sqlite3
        from app.config import settings

        test_id = "test_log_event_idempotent"
        conn = sqlite3.connect(settings.DB_PATH)
        try:
            # 第一次插入
            conn.execute(
                """INSERT OR IGNORE INTO security_events
                   (id, timestamp, host_id, event_type, severity,
                    source_collector, event_key, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (test_id, "2026-07-06T10:30:00", 1, "log_event", "info",
                 "windows_eventlog", "Security/4624",
                 json.dumps({"event_id": "4624"})),
            )
            conn.commit()

            # 第二次插入（相同 ID）— 不应抛异常
            conn.execute(
                """INSERT OR IGNORE INTO security_events
                   (id, timestamp, host_id, event_type, severity,
                    source_collector, event_key, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (test_id, "2026-07-06T10:30:00", 1, "log_event", "info",
                 "windows_eventlog", "Security/4624",
                 json.dumps({"event_id": "4624"})),
            )
            conn.commit()

            # 验证只有一条记录
            rows = conn.execute(
                "SELECT COUNT(*) FROM security_events WHERE id=?", (test_id,),
            ).fetchone()
            assert rows[0] == 1
        finally:
            conn.execute("DELETE FROM security_events WHERE id=?", (test_id,))
            conn.commit()
            conn.close()
