"""T05: sync_service 时间戳优先级验证 — cm_row_to_canonical 的 6 级链."""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

# 确保 backend 目录在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_tmp_dir = tempfile.mkdtemp(prefix="ir_test_sync_")
os.environ["IR_DATA_DIR"] = _tmp_dir
os.environ["IR_DB_PATH"] = os.path.join(_tmp_dir, "test.db")

from app.config import settings
from app.database import get_connection, init_db

settings.DB_PATH = os.environ["IR_DB_PATH"]
settings.DATA_DIR = _tmp_dir
init_db()

from app.services.sync_service import cm_row_to_canonical


# 标准 cfg 用于测试（模拟 abnormal_processes 的映射）
STD_CFG = {
    "event_type": "process_start",
    "category": "behavior",
    "severity_field": "severity",
    "risk_field": "risk_score",
    "evidence_fields": ["process_name", "process_path", "command_line", "pid"],
}

TABLE = "abnormal_processes"
HOST_ID = 42


def _ensure_case() -> None:
    """确保存在 case_id=1 的案例（hosts.case_id 的引用目标）."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO cases (id, name) VALUES (?, ?)",
            (1, "Test Case"),
        )
        conn.commit()


def _create_host(host_id: int, collection_time: str) -> None:
    """在 hosts 表中创建一条测试记录."""
    _ensure_case()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO hosts (id, case_id, hostname, ip_address, os_type, collection_time) VALUES (?, ?, ?, ?, ?, ?)",
            (host_id, 1, "test-host", "192.168.1.1", "linux", collection_time),
        )
        conn.commit()


class TestSyncServiceTimestampPriority:
    """验证 cm_row_to_canonical 的 6 级时间戳优先级链."""

    def setup_method(self):
        # 确保 hosts 表有记录（供第 5 级降级使用）
        _create_host(HOST_ID, "2025-01-01T00:00:00Z")

    # ── 等级 1: source_timestamp 最优先 ──
    def test_priority_1_source_timestamp(self):
        """等级 1: row 有 source_timestamp 时优先使用."""
        row = {
            "id": 1,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 50,
            "source_timestamp": "2025-06-15T10:30:00Z",
            "collected_at": "2025-01-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-06-15T10:30:00Z", (
            f"应使用 source_timestamp, 实际: {event.timestamp}"
        )
        assert event.evidence.get("source_timestamp") == "2025-06-15T10:30:00Z"

    # ── 等级 2: 从 details JSON 提取 ──
    def test_priority_2_details_source_timestamp(self):
        """等级 2a: details JSON 中有 source_timestamp."""
        row = {
            "id": 2,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "details": json.dumps({"source_timestamp": "2025-06-14T00:00:00Z"}),
            "collected_at": "2025-01-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-06-14T00:00:00Z", (
            f"应从 details.source_timestamp 提取, 实际: {event.timestamp}"
        )

    def test_priority_2_details_start_time(self):
        """等级 2b: details JSON 中有 start_time."""
        row = {
            "id": 3,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "details": json.dumps({"start_time": "2025-06-13T00:00:00Z"}),
            "collected_at": "2025-01-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-06-13T00:00:00Z", (
            f"应从 details.start_time 提取, 实际: {event.timestamp}"
        )

    def test_priority_2_details_timestamp(self):
        """等级 2c: details JSON 中有 timestamp."""
        row = {
            "id": 4,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "details": json.dumps({"timestamp": "2025-06-12T00:00:00Z"}),
            "collected_at": "2025-01-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-06-12T00:00:00Z", (
            f"应从 details.timestamp 提取, 实际: {event.timestamp}"
        )

    def test_priority_2_details_precedence(self):
        """details 内优先级: source_timestamp > start_time > timestamp."""
        row = {
            "id": 5,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "details": json.dumps({
                "source_timestamp": "2025-06-14T00:00:00Z",
                "start_time": "2025-06-13T00:00:00Z",
                "timestamp": "2025-06-12T00:00:00Z",
            }),
            "collected_at": "2025-01-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-06-14T00:00:00Z", (
            f"details 中应优先用 source_timestamp, 实际: {event.timestamp}"
        )

    # ── 等级 3: collected_at ──
    def test_priority_3_collected_at(self):
        """等级 3: 无 source_timestamp 且无 details 时用 collected_at."""
        row = {
            "id": 6,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "collected_at": "2025-06-10T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-06-10T00:00:00Z", (
            f"应使用 collected_at, 实际: {event.timestamp}"
        )

    # ── 等级 4: created_at / imported_at ──
    def test_priority_4_created_at(self):
        """等级 4: 无 collected_at 时用 created_at."""
        row = {
            "id": 7,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "created_at": "2025-05-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-05-01T00:00:00Z", (
            f"应使用 created_at, 实际: {event.timestamp}"
        )

    def test_priority_4_imported_at(self):
        """等级 4: created_at 和 imported_at 均可."""
        row = {
            "id": 8,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "imported_at": "2025-04-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-04-01T00:00:00Z", (
            f"应使用 imported_at, 实际: {event.timestamp}"
        )

    # ── 等级 5: hosts.collection_time ──
    def test_priority_5_hosts_collection_time(self):
        """等级 5: 降级到 hosts.collection_time."""
        row = {
            "id": 9,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.timestamp == "2025-01-01T00:00:00Z", (
            f"应使用 hosts.collection_time, 实际: {event.timestamp}"
        )

    # ── 等级 6: datetime.now() 兜底 ──
    def test_priority_6_datetime_now(self):
        """等级 6: 所有字段均无且 hosts 无记录时用 datetime.now()."""
        UNKNOWN_HOST = 99999
        row = {
            "id": 10,
            "host_id": UNKNOWN_HOST,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
        }
        before = datetime.now().isoformat()
        event = cm_row_to_canonical(TABLE, row, UNKNOWN_HOST, STD_CFG)
        after = datetime.now().isoformat()
        # 时间戳应该在 before 和 after 之间或接近
        assert before <= event.timestamp <= after or event.timestamp.startswith(before[:19]), (
            f"应降级到 datetime.now(), 实际: {event.timestamp}, before: {before}"
        )

    # ── evidence.source_timestamp 写入 ──
    def test_evidence_source_timestamp_present(self):
        """evidence.source_timestamp 应包含原始 source_timestamp 值."""
        row = {
            "id": 11,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "source_timestamp": "2025-06-15T10:30:00Z",
            "collected_at": "2025-01-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.evidence.get("source_timestamp") == "2025-06-15T10:30:00Z", (
            f"evidence.source_timestamp 应保留原始值, 实际: {event.evidence.get('source_timestamp')}"
        )

    def test_evidence_source_timestamp_none(self):
        """无 source_timestamp 时 evidence.source_timestamp 应为 None."""
        row = {
            "id": 12,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "collected_at": "2025-01-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        assert event.evidence.get("source_timestamp") is None, (
            f"无 source_timestamp 时应为 None, 实际: {event.evidence.get('source_timestamp')}"
        )

    # ── 完整链验证 ──
    def test_full_priority_chain(self):
        """完整优先级链: source_timestamp > details > collected_at > created_at > hosts > now."""
        row = {
            "id": 13,
            "host_id": HOST_ID,
            "process_name": "test.exe",
            "severity": "high",
            "risk_score": 30,
            "source_timestamp": "2025-06-15T10:30:00Z",
            "details": json.dumps({"start_time": "2025-06-14T00:00:00Z"}),
            "collected_at": "2025-06-10T00:00:00Z",
            "created_at": "2025-05-01T00:00:00Z",
        }
        event = cm_row_to_canonical(TABLE, row, HOST_ID, STD_CFG)
        # source_timestamp 应胜出
        assert event.timestamp == "2025-06-15T10:30:00Z", (
            f"完整链中 source_timestamp 应胜出, 实际: {event.timestamp}"
        )
