"""T03: 检测器注入验证 — 确认 anomaly_detector 和 persistence_finder 返回结果包含 source_timestamp."""

import os
import sys
import tempfile
from pathlib import Path

# 确保 backend 目录在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_tmp_dir = tempfile.mkdtemp(prefix="ir_test_detector_")
os.environ["IR_DATA_DIR"] = _tmp_dir
os.environ["IR_DB_PATH"] = os.path.join(_tmp_dir, "test.db")

from app.config import settings
from app.database import init_db

settings.DB_PATH = os.environ["IR_DB_PATH"]
settings.DATA_DIR = _tmp_dir
init_db()

from app.analysis.anomaly_detector import AnomalyDetector
from app.analysis.persistence_finder import PersistenceFinder


# ── 辅助：最小可用规则（使用 regex 匹配器） ──
MOCK_RULES = [
    {
        "id": 1,
        "name": "test_rule_process",
        "rule_type": "regex",
        "category": "process",
        "condition": {"field": "name", "pattern": "malware"},
        "severity": "high",
        "reason": "Known malware process",
        "enabled": True,
    },
    {
        "id": 2,
        "name": "test_rule_network",
        "rule_type": "regex",
        "category": "network",
        "condition": {"field": "remote_address", "pattern": "evil"},
        "severity": "high",
        "reason": "Known malicious IP",
        "enabled": True,
    },
    {
        "id": 3,
        "name": "test_rule_startup",
        "rule_type": "regex",
        "category": "startup",
        "condition": {"field": "name", "pattern": "bad"},
        "severity": "medium",
        "reason": "Suspicious startup",
        "enabled": True,
    },
]


class TestDetectProcessesSourceTimestamp:
    """验证 detect_processes 返回结果包含 source_timestamp."""

    def test_detect_processes_contains_source_timestamp(self):
        """detect_processes 应给每个结果注入 source_timestamp."""
        raw_data = {
            "processes": [
                {
                    "pid": 101,
                    "name": "malware.exe",
                    "path": "/tmp/malware.exe",
                    "command_line": "malware.exe -h",
                    "ppid": 1,
                    "parent_name": "init",
                    "start_time": "2025-06-15T10:30:00Z",
                    "user": "root",
                    "threads": 2,
                }
            ]
        }
        results = AnomalyDetector.detect_processes(raw_data, MOCK_RULES)
        assert len(results) >= 1
        for item in results:
            assert "source_timestamp" in item, (
                f"detect_processes 返回项缺少 source_timestamp: {item}"
            )
            assert item["source_timestamp"] == "2025-06-15T10:30:00Z", (
                f"source_timestamp 应为进程的 start_time, 实际: {item['source_timestamp']}"
            )

    def test_detect_processes_no_start_time(self):
        """当进程无 start_time 时，source_timestamp 应为 None."""
        raw_data = {
            "processes": [
                {
                    "pid": 102,
                    "name": "malware2.exe",
                    "path": "/tmp/malware2.exe",
                    "command_line": "",
                    "ppid": 1,
                    "parent_name": "init",
                    "user": "root",
                    "threads": 1,
                }
            ]
        }
        results = AnomalyDetector.detect_processes(raw_data, MOCK_RULES)
        assert len(results) >= 1
        for item in results:
            assert "source_timestamp" in item
            # start_time 不存在 ⇒ source_timestamp 取 get("start_time") → None
            assert item["source_timestamp"] is None

    def test_detect_processes_multiple_items(self):
        """多条进程每条都应有自己的 source_timestamp."""
        raw_data = {
            "processes": [
                {
                    "pid": 201, "name": "malware_a.exe", "path": "",
                    "command_line": "", "ppid": 1, "parent_name": "init",
                    "start_time": "2025-01-01T00:00:00Z", "user": "u1",
                },
                {
                    "pid": 202, "name": "malware_b.exe", "path": "",
                    "command_line": "", "ppid": 1, "parent_name": "init",
                    "start_time": "2025-06-15T12:00:00Z", "user": "u2",
                },
            ]
        }
        results = AnomalyDetector.detect_processes(raw_data, MOCK_RULES)
        # 按 pid 排序
        results.sort(key=lambda x: x.get("pid", 0))
        timestamps = [r["source_timestamp"] for r in results]
        assert timestamps == ["2025-01-01T00:00:00Z", "2025-06-15T12:00:00Z"], (
            f"source_timestamp 不匹配: {timestamps}"
        )


class TestDetectConnectionsSourceTimestamp:
    """验证 detect_connections 返回结果包含 source_timestamp."""

    def test_detect_connections_contains_source_timestamp(self):
        """detect_connections 应给每个结果注入 source_timestamp."""
        raw_data = {
            "network": {
                "connections": [
                    {
                        "protocol": "TCP",
                        "local_address": "192.168.1.1",
                        "local_port": 1234,
                        "remote_address": "evil.com",
                        "remote_port": 80,
                        "state": "ESTABLISHED",
                        "process_name": "nc.exe",
                        "pid": 301,
                        "timestamp": "2025-06-15T10:30:00Z",
                    }
                ]
            }
        }
        results = AnomalyDetector.detect_connections(raw_data, MOCK_RULES)
        assert len(results) >= 1
        for item in results:
            assert "source_timestamp" in item, (
                f"detect_connections 返回项缺少 source_timestamp: {item}"
            )
            assert item["source_timestamp"] == "2025-06-15T10:30:00Z", (
                f"source_timestamp 应为连接的 timestamp, 实际: {item['source_timestamp']}"
            )

    def test_detect_connections_no_timestamp(self):
        """连接无 timestamp 时 source_timestamp 应为 None."""
        raw_data = {
            "network": {
                "connections": [
                    {
                        "protocol": "UDP",
                        "local_address": "192.168.1.1",
                        "local_port": 53,
                        "remote_address": "evil.com",
                        "remote_port": 53,
                        "state": "NONE",
                        "process_name": "dns.exe",
                        "pid": 302,
                    }
                ]
            }
        }
        results = AnomalyDetector.detect_connections(raw_data, MOCK_RULES)
        assert len(results) >= 1
        for item in results:
            assert "source_timestamp" in item
            assert item["source_timestamp"] is None


class TestDetectStartupItemsSourceTimestamp:
    """验证 detect_startup_items 返回结果包含 source_timestamp."""

    def test_detect_startup_items_with_last_write_time(self):
        """启动项优先使用 last_write_time."""
        raw_data = {
            "startup_items": [
                {
                    "name": "bad.exe",
                    "command": "bad.exe -a",
                    "location": "HKLM\\Run",
                    "type": "registry",
                    "user": "admin",
                    "last_write_time": "2025-06-15T10:30:00Z",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ]
        }
        results = AnomalyDetector.detect_startup_items(raw_data, MOCK_RULES)
        assert len(results) >= 1
        for item in results:
            assert "source_timestamp" in item
            # 优先用 last_write_time
            assert item["source_timestamp"] == "2025-06-15T10:30:00Z", (
                f"应优先使用 last_write_time, 实际: {item['source_timestamp']}"
            )

    def test_detect_startup_items_fallback_to_timestamp(self):
        """无 last_write_time 时降级到 timestamp."""
        raw_data = {
            "startup_items": [
                {
                    "name": "bad.exe",
                    "command": "bad.exe",
                    "location": "Startup",
                    "type": "folder",
                    "user": "user",
                    "timestamp": "2025-06-15T12:00:00Z",
                }
            ]
        }
        results = AnomalyDetector.detect_startup_items(raw_data, MOCK_RULES)
        assert len(results) >= 1
        for item in results:
            assert "source_timestamp" in item
            assert item["source_timestamp"] == "2025-06-15T12:00:00Z"

    def test_detect_startup_items_no_timestamp(self):
        """无任何时间字段时 source_timestamp 应为 None."""
        raw_data = {
            "startup_items": [
                {
                    "name": "bad.exe",
                    "command": "",
                    "location": "",
                    "type": "unknown",
                    "user": "",
                }
            ]
        }
        results = AnomalyDetector.detect_startup_items(raw_data, MOCK_RULES)
        assert len(results) >= 1
        for item in results:
            assert "source_timestamp" in item
            assert item["source_timestamp"] is None


class TestPersistenceFinderSourceTimestamp:
    """验证 PersistenceFinder.find_all 返回结果包含 source_timestamp."""

    def test_find_all_from_persistence(self):
        """persistence 采集器中的条目应包含 source_timestamp."""
        raw_data = {
            "persistence": {
                "run_keys": [
                    {"name": "malware", "value": "malware.exe",
                     "key": "HKLM\\Run", "timestamp": "2025-06-15T10:30:00Z"}
                ]
            }
        }
        items = PersistenceFinder.find_all(raw_data)
        assert len(items) >= 1
        for item in items:
            assert "source_timestamp" in item
            assert item["source_timestamp"] == "2025-06-15T10:30:00Z"

    def test_find_all_from_startup_items(self):
        """startup_items 中的条目应包含 source_timestamp."""
        raw_data = {
            "startup_items": [
                {"name": "bad.exe", "command": "bad.exe",
                 "type": "folder", "timestamp": "2025-06-15T12:00:00Z"}
            ]
        }
        items = PersistenceFinder.find_all(raw_data)
        assert len(items) >= 1
        for item in items:
            assert "source_timestamp" in item
            assert item["source_timestamp"] == "2025-06-15T12:00:00Z"

    def test_find_all_from_registry(self):
        """registry.run_keys 中的条目应包含 source_timestamp."""
        raw_data = {
            "registry": {
                "run_keys": [
                    {"name": "malware", "value": "malware.exe",
                     "key": "HKLM\\Run", "last_write_time": "2025-06-15T10:30:00Z"}
                ]
            }
        }
        items = PersistenceFinder.find_all(raw_data)
        assert len(items) >= 1
        for item in items:
            assert "source_timestamp" in item
            assert item["source_timestamp"] == "2025-06-15T10:30:00Z"

    def test_find_all_priority_chain(self):
        """timestamp / last_write_time / start_time 优先级链."""
        raw_data = {
            "persistence": {
                "services": [
                    {
                        "name": "svc",
                        "command": "svc.exe",
                        "location": "",
                        "user": "SYSTEM",
                        "start_time": "2025-01-01T00:00:00Z",
                        "last_write_time": "2025-06-01T00:00:00Z",
                        "timestamp": "2025-06-15T10:30:00Z",
                    }
                ]
            }
        }
        items = PersistenceFinder.find_all(raw_data)
        assert len(items) >= 1
        # 优先级: timestamp > last_write_time > start_time
        assert items[0]["source_timestamp"] == "2025-06-15T10:30:00Z", (
            f"应优先使用 timestamp, 实际: {items[0]['source_timestamp']}"
        )

    def test_find_all_no_timestamp_fields(self):
        """没有任何时间字段时 source_timestamp 应为 None."""
        raw_data = {
            "persistence": {
                "scheduled_tasks": [
                    {"name": "task", "command": "task.exe", "location": "", "user": ""}
                ]
            }
        }
        items = PersistenceFinder.find_all(raw_data)
        assert len(items) >= 1
        for item in items:
            assert "source_timestamp" in item
            assert item["source_timestamp"] is None
