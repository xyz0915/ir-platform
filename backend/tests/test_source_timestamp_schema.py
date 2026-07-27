"""T01: Schema 验证 — 11 张 CM 分析表在 init_db() 后应正确包含 source_timestamp TEXT 列."""

import os
import sys
import tempfile
from pathlib import Path

# 确保 backend 目录在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 使用临时目录和临时数据库
_tmp_dir = tempfile.mkdtemp(prefix="ir_test_schema_")
os.environ["IR_DATA_DIR"] = _tmp_dir
os.environ["IR_DB_PATH"] = os.path.join(_tmp_dir, "test.db")

from app.config import settings
from app.database import get_connection, init_db

# 11 张需要验证的表（与 DDL 和 _migrate_source_timestamp 一致）
SOURCE_TIMESTAMP_TABLES = [
    "abnormal_processes",
    "suspicious_connections",
    "suspicious_startup_items",
    "persistence_items",
    "ioc_hits",
    "network_connections",
    "file_hashes",
    "wmi_subscriptions",
    "registry_keys",
    "webshells",
    "memory_shells",
]

# 不应包含 source_timestamp 的对照表
CONTROL_TABLES = [
    "timeline_events",
    "rules",
    "whitelist",
    "analysis_results",
    "hosts",
    "alerts",
]


def setup_module():
    """初始化测试数据库."""
    settings.DB_PATH = os.environ["IR_DB_PATH"]
    settings.DATA_DIR = _tmp_dir
    init_db()


def get_columns(table: str) -> set:
    """通过 PRAGMA table_info 获取指定表的所有列名."""
    with get_connection() as conn:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return {row["name"] for row in cursor.fetchall()}


class TestSourceTimestampSchema:
    """验证 11 张 CM 分析表的 source_timestamp 列 Schema."""

    def test_all_11_tables_have_source_timestamp(self):
        """每张 CM 分析表都应包含 source_timestamp 列."""
        for table in SOURCE_TIMESTAMP_TABLES:
            columns = get_columns(table)
            assert "source_timestamp" in columns, (
                f"表 {table} 缺少 source_timestamp 列"
            )

    def test_source_timestamp_is_text_type(self):
        """source_timestamp 列类型应为 TEXT."""
        for table in SOURCE_TIMESTAMP_TABLES:
            with get_connection() as conn:
                cursor = conn.execute(f"PRAGMA table_info({table})")
                for row in cursor.fetchall():
                    if row["name"] == "source_timestamp":
                        assert row["type"].upper() == "TEXT", (
                            f"表 {table} 的 source_timestamp 类型是 {row['type']}，应为 TEXT"
                        )

    def test_source_timestamp_nullable(self):
        """source_timestamp 列应为可空（notnull=0）."""
        for table in SOURCE_TIMESTAMP_TABLES:
            with get_connection() as conn:
                cursor = conn.execute(f"PRAGMA table_info({table})")
                for row in cursor.fetchall():
                    if row["name"] == "source_timestamp":
                        assert row["notnull"] == 0, (
                            f"表 {table} 的 source_timestamp 列不可空（notnull={row['notnull']}）"
                        )

    def test_source_timestamp_no_default(self):
        """source_timestamp 列应无默认值."""
        for table in SOURCE_TIMESTAMP_TABLES:
            with get_connection() as conn:
                cursor = conn.execute(f"PRAGMA table_info({table})")
                for row in cursor.fetchall():
                    if row["name"] == "source_timestamp":
                        assert row["dflt_value"] is None, (
                            f"表 {table} 的 source_timestamp 有默认值: {row['dflt_value']}"
                        )

    def test_control_tables_should_not_have_source_timestamp(self):
        """非 CM 分析表不应包含 source_timestamp 列."""
        for table in CONTROL_TABLES:
            columns = get_columns(table)
            assert "source_timestamp" not in columns, (
                f"对照表 {table} 不应包含 source_timestamp 列"
            )

    def test_migration_idempotent(self):
        """_migrate_source_timestamp 应可重复执行（幂等）."""
        from app.database import _migrate_source_timestamp
        with get_connection() as conn:
            # 第一次执行
            _migrate_source_timestamp(conn)
            # 第二次执行（应不报错且不改变 schema）
            _migrate_source_timestamp(conn)

        # 验证 schema 不变
        for table in SOURCE_TIMESTAMP_TABLES:
            columns = get_columns(table)
            assert "source_timestamp" in columns, (
                f"幂等迁移后表 {table} 丢失 source_timestamp 列"
            )

    def test_table_count_matches_11(self):
        """确保确实有 11 张表被验证（防止新表遗漏）."""
        assert len(SOURCE_TIMESTAMP_TABLES) == 11, (
            f"期望验证 11 张表，实际 {len(SOURCE_TIMESTAMP_TABLES)} 张"
        )

    def test_init_db_creates_tables_with_source_timestamp(self):
        """全新 init_db() 建表时 DDL 应直接包含 source_timestamp."""
        # 用新的临时数据库验证
        new_tmp = tempfile.mkdtemp(prefix="ir_test_fresh_")
        fresh_db = os.path.join(new_tmp, "fresh.db")
        old_db_path = settings.DB_PATH
        old_data_dir = settings.DATA_DIR
        try:
            settings.DB_PATH = fresh_db
            settings.DATA_DIR = new_tmp
            init_db()
            for table in SOURCE_TIMESTAMP_TABLES:
                columns = get_columns(table)
                assert "source_timestamp" in columns, (
                    f"全新 init_db 后表 {table} 缺少 source_timestamp 列"
                )
        finally:
            settings.DB_PATH = old_db_path
            settings.DATA_DIR = old_data_dir
