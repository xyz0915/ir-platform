"""第①批 AI 功能测试 — 共享测试基础设施（不会被 pytest 收集）.

提供：
- ``make_isolated_db`` / ``cleanup_db``：创建/清理临时隔离 SQLite（绝不触碰 backend/data/ir.db）。
- ``IsolatedDBTestCase``：每个测试方法使用全新临时库，杜绝跨测试污染。
- ``seed_normalized_logs``：在临时库中写入 cases → hosts → normalized_logs 测试数据。
"""

import os
import gc
import tempfile
import time
import unittest

import app.config as config
from app.database import init_db, get_connection


def make_isolated_db():
    """创建临时 SQLite 文件并建表，返回路径（设置 settings.DB_PATH）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_batch1_")
    os.close(fd)
    config.settings.DB_PATH = path
    init_db()
    return path


def cleanup_db(path):
    """尽力清理临时库及其 WAL/SHM 附属文件。"""
    gc.collect()
    for _ in range(5):
        removed = True
        for suffix in ("", "-wal", "-shm"):
            p = path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    removed = False
        if removed:
            break
        time.sleep(0.1)


class IsolatedDBTestCase(unittest.TestCase):
    """每个测试方法使用独立临时库（function-scoped），保证互不污染。"""

    def setUp(self):
        self._db_path = make_isolated_db()

    def tearDown(self):
        cleanup_db(self._db_path)
        self._db_path = None

    def seed_normalized_logs(self, rows):
        """写入 cases → hosts → normalized_logs，返回 (case_id, host_id)。"""
        from app.models.normalized_log import NormalizedLog

        with get_connection() as conn:
            conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
            case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
                "VALUES (?, 'QAHOST', '10.0.0.5', 'Windows')",
                (case_id,),
            )
            host_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for r in rows:
            item = dict(r)
            item["host_id"] = host_id
            item.setdefault("log_source", "test")
            item.setdefault("event_type", "login")
            item.setdefault("severity", "high")
            item.setdefault("timestamp", "2026-07-18 10:00:00")
            item.setdefault("description", "qa log line")
            NormalizedLog.batch_create([item])
        return case_id, host_id
