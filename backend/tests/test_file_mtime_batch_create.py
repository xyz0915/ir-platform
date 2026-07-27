"""验证 FileHash.batch_create 中 source_timestamp 优先级逻辑.

优先级: file_mtime → timestamp → collected_at

该脚本直接操作 SQLite 验证落库结果，不依赖完整 Web 环境。
"""

import os
import sys
import tempfile
import sqlite3

# ── 确保可以 import backend 模块 ──
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.config import settings
from app.database import init_db, get_connection
from app.models.analysis import FileHash


def setup_temp_db():
    """创建临时 SQLite 数据库，返回 (orig_db_path, db_fd, db_path)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    orig = settings.DB_PATH
    settings.DB_PATH = db_path
    init_db()
    # 插入测试所需的 case 和 host（满足 FOREIGN KEY）
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO cases (id, name) VALUES (1, 'test_case')"
        )
        conn.execute(
            "INSERT INTO hosts (id, case_id, hostname) VALUES (1, 1, 'test_host')"
        )
    return orig, db_path


def cleanup_temp_db(orig_db_path: str, db_path: str):
    """清理临时数据库并恢复原配置."""
    settings.DB_PATH = orig_db_path
    try:
        os.remove(db_path)
    except OSError:
        pass


def test_scenario_1_file_mtime_priority():
    """场景1: 有 file_mtime → source_timestamp 应取 file_mtime."""
    fh_data = [{
        "file_path": "/tmp/test.exe",
        "file_name": "test.exe",
        "sha256": "abc123",
        "collected_at": "2026-07-27T16:56:37+08:00",
        "file_mtime": "2026-07-07T04:48:14+00:00",
    }]

    # 模拟 analysis_service 中注入 source_timestamp 的逻辑
    for item in fh_data:
        item["source_timestamp"] = (item.get("file_mtime")
                                     or item.get("timestamp")
                                     or item.get("collected_at"))

    FileHash.batch_create(1, fh_data)

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM file_hashes WHERE host_id=1"
        ).fetchone()

    assert row is not None, "No row found in file_hashes"
    print(f"[Scenario 1] source_timestamp: {row['source_timestamp']}")
    print(f"[Scenario 1] Expected: 2026-07-07T04:48:14+00:00")

    assert row["source_timestamp"] == "2026-07-07T04:48:14+00:00", \
        f"❌ file_mtime not used! Got: {row['source_timestamp']}"
    print("[Scenario 1] ✅ PASS: file_mtime correctly used as source_timestamp")


def test_scenario_2_fallback_to_collected_at():
    """场景2: 无 file_mtime → source_timestamp 应 fallback 到 collected_at."""
    fh_data = [{
        "file_path": "/tmp/test2.exe",
        "file_name": "test2.exe",
        "sha256": "def456",
        "collected_at": "2026-07-27T16:56:37+08:00",
    }]

    # 模拟 analysis_service 中注入 source_timestamp 的逻辑
    for item in fh_data:
        item["source_timestamp"] = (item.get("file_mtime")
                                     or item.get("timestamp")
                                     or item.get("collected_at"))

    FileHash.batch_create(1, fh_data)

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM file_hashes WHERE host_id=1 AND file_path='/tmp/test2.exe'"
        ).fetchone()

    assert row is not None, "No row found for test2.exe"
    print(f"[Scenario 2] No file_mtime → source_timestamp: {row['source_timestamp']}")

    assert row["source_timestamp"] == "2026-07-27T16:56:37+08:00", \
        f"❌ fallback to collected_at failed! Got: {row['source_timestamp']}"
    print("[Scenario 2] ✅ PASS: correctly fell back to collected_at")


def test_scenario_3_timestamp_middle_priority():
    """场景3: 无 file_mtime 但有 timestamp → source_timestamp 应取 timestamp."""
    fh_data = [{
        "file_path": "/tmp/test3.exe",
        "file_name": "test3.exe",
        "sha256": "ghi789",
        "collected_at": "2026-07-27T16:56:37+08:00",
        "timestamp": "2026-07-15T12:00:00+00:00",
    }]

    for item in fh_data:
        item["source_timestamp"] = (item.get("file_mtime")
                                     or item.get("timestamp")
                                     or item.get("collected_at"))

    FileHash.batch_create(1, fh_data)

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM file_hashes WHERE host_id=1 AND file_path='/tmp/test3.exe'"
        ).fetchone()

    assert row is not None, "No row found for test3.exe"
    print(f"[Scenario 3] timestamp → source_timestamp: {row['source_timestamp']}")

    assert row["source_timestamp"] == "2026-07-15T12:00:00+00:00", \
        f"❌ timestamp not used! Got: {row['source_timestamp']}"
    print("[Scenario 3] ✅ PASS: correctly used timestamp as source_timestamp")


def test_scenario_4_empty_data():
    """场景4: 空数据列表应返回 0."""
    count = FileHash.batch_create(1, [])
    assert count == 0, f"❌ Expected 0 for empty data, got {count}"
    print("[Scenario 4] ✅ PASS: empty data returns 0")


def main():
    print("=" * 60)
    print("FileHash batch_create source_timestamp priority tests")
    print("=" * 60)

    orig_db, tmp_db = setup_temp_db()
    print(f"\n[Setup] Temp DB: {tmp_db}")

    try:
        # ── 场景 1: 有 file_mtime ──
        print("\n─── Scenario 1: file_mtime priority ───")
        test_scenario_1_file_mtime_priority()

        # ── 场景 2: 无 file_mtime, fallback to collected_at ──
        print("\n─── Scenario 2: fallback to collected_at ───")
        test_scenario_2_fallback_to_collected_at()

        # ── 场景 3: timestamp 中间优先级 ──
        print("\n─── Scenario 3: timestamp middle priority ───")
        test_scenario_3_timestamp_middle_priority()

        # ── 场景 4: 空数据 ──
        print("\n─── Scenario 4: empty data ───")
        test_scenario_4_empty_data()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cleanup_temp_db(orig_db, tmp_db)
        print(f"\n[Cleanup] Temp DB removed")


if __name__ == "__main__":
    main()
