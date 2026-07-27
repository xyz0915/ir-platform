"""T02: batch_create source_timestamp 写入验证.

覆盖模型: AbnormalProcess, SuspiciousConnection, SuspiciousStartupItem,
          PersistenceItem, NetworkConnection, IocHit(含 append).
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# 确保 backend 目录在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_tmp_dir = tempfile.mkdtemp(prefix="ir_test_batch_")
os.environ["IR_DATA_DIR"] = _tmp_dir
os.environ["IR_DB_PATH"] = os.path.join(_tmp_dir, "test.db")

from app.config import settings
from app.database import get_connection, init_db

settings.DB_PATH = os.environ["IR_DB_PATH"]
settings.DATA_DIR = _tmp_dir
init_db()

from app.models.analysis import (
    AbnormalProcess,
    SuspiciousConnection,
    SuspiciousStartupItem,
    PersistenceItem,
    NetworkConnection,
    IocHit,
)


def _fetch_all(table: str) -> list[dict]:
    """查询指定表全部记录."""
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]


def _clean_table(table: str) -> None:
    """清空指定表."""
    with get_connection() as conn:
        conn.execute(f"DELETE FROM {table}")


HOST_ID = 9999
TIMESTAMP_VALUE = "2025-06-15T10:30:00Z"


def _ensure_case() -> None:
    """确保存在 case_id=1 的案例（hosts.case_id 的引用目标）."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO cases (id, name) VALUES (?, ?)",
            (1, "Test Case"),
        )
        conn.commit()


def _create_host(host_id: int) -> None:
    """在 hosts 表中创建一条测试记录（满足外键约束）."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO hosts (id, case_id, hostname, ip_address, os_type, collection_time) VALUES (?, ?, ?, ?, ?, ?)",
            (host_id, 1, "test-host", "192.168.1.1", "linux", "2025-01-01T00:00:00Z"),
        )
        conn.commit()


# 创建案例和测试主机记录（满足所有表的外键约束）
_ensure_case()
_create_host(HOST_ID)


class TestAbnormalProcessBatchCreate:
    """AbnormalProcess.batch_create source_timestamp 测试."""

    def teardown_method(self):
        _clean_table("abnormal_processes")

    def test_with_source_timestamp(self):
        """传入 source_timestamp 时应正确落库."""
        items = [{
            "pid": 1001,
            "process_name": "malware.exe",
            "process_path": "/tmp/malware.exe",
            "command_line": "malware.exe -h",
            "parent_pid": 1,
            "parent_name": "init",
            "reason": "Suspicious process",
            "rule_name": "rule_001",
            "severity": "high",
            "details": {"user": "root"},
            "source_timestamp": TIMESTAMP_VALUE,
        }]
        count = AbnormalProcess.batch_create(HOST_ID, items)
        assert count == 1
        rows = _fetch_all("abnormal_processes")
        assert rows[0]["source_timestamp"] == TIMESTAMP_VALUE

    def test_without_source_timestamp(self):
        """不传 source_timestamp 时应为 NULL."""
        items = [{
            "pid": 1002,
            "process_name": "normal.exe",
            "process_path": "/usr/bin/normal.exe",
            "command_line": "normal.exe",
            "reason": "test",
            "rule_name": "rule_002",
            "severity": "low",
            "details": {},
        }]
        AbnormalProcess.batch_create(HOST_ID, items)
        rows = _fetch_all("abnormal_processes")
        assert rows[0]["source_timestamp"] is None

    def test_source_timestamp_none(self):
        """source_timestamp 显式传 None 时应为 NULL."""
        items = [{
            "pid": 1003,
            "process_name": "test.exe",
            "reason": "test",
            "rule_name": "rule_003",
            "severity": "low",
            "details": {},
            "source_timestamp": None,
        }]
        AbnormalProcess.batch_create(HOST_ID, items)
        rows = _fetch_all("abnormal_processes")
        assert rows[0]["source_timestamp"] is None

    def test_multiple_items(self):
        """批量写入多条记录，每条应有各自的 source_timestamp."""
        items = [
            {"pid": 2001, "process_name": "a.exe", "reason": "r1", "rule_name": "rule_a",
             "severity": "low", "details": {}, "source_timestamp": "2025-01-01T00:00:00Z"},
            {"pid": 2002, "process_name": "b.exe", "reason": "r2", "rule_name": "rule_b",
             "severity": "low", "details": {}, "source_timestamp": "2025-06-15T12:00:00Z"},
            {"pid": 2003, "process_name": "c.exe", "reason": "r3", "rule_name": "rule_c",
             "severity": "low", "details": {}},  # 没有 source_timestamp
        ]
        AbnormalProcess.batch_create(HOST_ID, items)
        rows = sorted(_fetch_all("abnormal_processes"), key=lambda r: r["pid"])
        assert rows[0]["source_timestamp"] == "2025-01-01T00:00:00Z"
        assert rows[1]["source_timestamp"] == "2025-06-15T12:00:00Z"
        assert rows[2]["source_timestamp"] is None


class TestSuspiciousConnectionBatchCreate:
    """SuspiciousConnection.batch_create source_timestamp 测试."""

    def teardown_method(self):
        _clean_table("suspicious_connections")

    def test_with_source_timestamp(self):
        items = [{
            "protocol": "TCP", "local_address": "192.168.1.1", "local_port": 1234,
            "remote_address": "10.0.0.1", "remote_port": 80, "state": "ESTABLISHED",
            "process_name": "nc.exe", "pid": 3001,
            "reason": "Suspicious outbound", "rule_name": "r_conn",
            "severity": "high", "source_timestamp": TIMESTAMP_VALUE,
        }]
        SuspiciousConnection.batch_create(HOST_ID, items)
        rows = _fetch_all("suspicious_connections")
        assert rows[0]["source_timestamp"] == TIMESTAMP_VALUE

    def test_without_source_timestamp(self):
        items = [{
            "protocol": "UDP", "local_address": "0.0.0.0", "local_port": 53,
            "remote_address": "8.8.8.8", "remote_port": 53, "state": "NONE",
            "process_name": "dns.exe", "pid": 3002,
            "reason": "DNS query", "rule_name": "r_dns", "severity": "info",
        }]
        SuspiciousConnection.batch_create(HOST_ID, items)
        rows = _fetch_all("suspicious_connections")
        assert rows[0]["source_timestamp"] is None


class TestSuspiciousStartupItemBatchCreate:
    """SuspiciousStartupItem.batch_create source_timestamp 测试."""

    def teardown_method(self):
        _clean_table("suspicious_startup_items")

    def test_with_source_timestamp(self):
        items = [{
            "name": "bad.exe", "command": "bad.exe -autorun", "location": "HKLM\\Run",
            "type": "registry", "user": "admin",
            "reason": "Suspicious startup", "rule_name": "r_startup",
            "severity": "medium", "source_timestamp": TIMESTAMP_VALUE,
        }]
        SuspiciousStartupItem.batch_create(HOST_ID, items)
        rows = _fetch_all("suspicious_startup_items")
        assert rows[0]["source_timestamp"] == TIMESTAMP_VALUE

    def test_without_source_timestamp(self):
        items = [{
            "name": "good.exe", "command": "good.exe", "location": "C:\\startup",
            "type": "folder", "user": "user",
            "reason": "known", "rule_name": "r_known", "severity": "info",
        }]
        SuspiciousStartupItem.batch_create(HOST_ID, items)
        rows = _fetch_all("suspicious_startup_items")
        assert rows[0]["source_timestamp"] is None


class TestPersistenceItemBatchCreate:
    """PersistenceItem.batch_create source_timestamp 测试."""

    def teardown_method(self):
        _clean_table("persistence_items")

    def test_with_source_timestamp(self):
        items = [{
            "type": "run_key", "name": "malware", "command": "malware.exe",
            "location": "HKCU\\Run", "user": "user",
            "is_suspicious": True, "reason": "Persistence mechanism",
            "details": {"key": "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"},
            "source_timestamp": TIMESTAMP_VALUE,
        }]
        PersistenceItem.batch_create(HOST_ID, items)
        rows = _fetch_all("persistence_items")
        assert rows[0]["source_timestamp"] == TIMESTAMP_VALUE

    def test_without_source_timestamp(self):
        items = [{
            "type": "service", "name": "svchost", "command": "svchost.exe -k",
            "location": "", "user": "SYSTEM",
            "is_suspicious": False, "reason": "",
            "details": {},
        }]
        PersistenceItem.batch_create(HOST_ID, items)
        rows = _fetch_all("persistence_items")
        assert rows[0]["source_timestamp"] is None

    def test_source_timestamp_none(self):
        items = [{
            "type": "scheduled_task", "name": "task", "command": "task.exe",
            "location": "", "user": "user",
            "is_suspicious": False, "reason": "",
            "details": {},
            "source_timestamp": None,
        }]
        PersistenceItem.batch_create(HOST_ID, items)
        rows = _fetch_all("persistence_items")
        assert rows[0]["source_timestamp"] is None


class TestNetworkConnectionBatchCreate:
    """NetworkConnection.batch_create source_timestamp 测试."""

    def teardown_method(self):
        _clean_table("network_connections")

    def test_with_source_timestamp(self):
        items = [{
            "protocol": "TCP", "local_addr": "192.168.1.1", "local_port": 8080,
            "remote_addr": "10.0.0.2", "remote_port": 443, "state": "ESTABLISHED",
            "pid": 4001, "process_name": "curl.exe", "collected_at": "2025-06-15T10:00:00Z",
            "source_timestamp": TIMESTAMP_VALUE,
        }]
        NetworkConnection.batch_create(HOST_ID, items)
        rows = _fetch_all("network_connections")
        assert rows[0]["source_timestamp"] == TIMESTAMP_VALUE

    def test_without_source_timestamp(self):
        items = [{
            "protocol": "UDP", "local_addr": "0.0.0.0", "local_port": 123,
            "remote_addr": "pool.ntp.org", "remote_port": 123, "state": "NONE",
            "pid": 4002, "process_name": "ntpd", "collected_at": "2025-06-15T10:00:00Z",
        }]
        NetworkConnection.batch_create(HOST_ID, items)
        rows = _fetch_all("network_connections")
        assert rows[0]["source_timestamp"] is None


class TestIocHitBatchCreate:
    """IocHit.batch_create source_timestamp 测试."""

    def teardown_method(self):
        _clean_table("ioc_hits")

    def test_with_source_timestamp(self):
        items = [{
            "ioc_type": "ip", "ioc_value": "1.2.3.4",
            "matched_in": "network_connections", "context": "malicious IP",
            "severity": "high", "source_timestamp": TIMESTAMP_VALUE,
        }]
        IocHit.batch_create(HOST_ID, items)
        rows = _fetch_all("ioc_hits")
        assert rows[0]["source_timestamp"] == TIMESTAMP_VALUE

    def test_without_source_timestamp(self):
        items = [{
            "ioc_type": "domain", "ioc_value": "evil.com",
            "matched_in": "dns", "context": "known bad domain",
            "severity": "high",
        }]
        IocHit.batch_create(HOST_ID, items)
        rows = _fetch_all("ioc_hits")
        assert rows[0]["source_timestamp"] is None

    def test_append_with_source_timestamp(self):
        """IocHit.append 也应正确写入 source_timestamp."""
        IocHit.append(HOST_ID, [{
            "ioc_type": "hash", "ioc_value": "deadbeef",
            "matched_in": "file_hashes", "context": "malware hash",
            "severity": "critical", "source_timestamp": TIMESTAMP_VALUE,
        }])
        rows = _fetch_all("ioc_hits")
        assert rows[0]["source_timestamp"] == TIMESTAMP_VALUE

    def test_append_without_source_timestamp(self):
        """IocHit.append 不传 source_timestamp 时应为 NULL."""
        IocHit.append(HOST_ID, [{
            "ioc_type": "hash", "ioc_value": "cafebabe",
            "matched_in": "file_hashes", "context": "clean hash",
            "severity": "info",
        }])
        rows = _fetch_all("ioc_hits")
        assert rows[0]["source_timestamp"] is None
