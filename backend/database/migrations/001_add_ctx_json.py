"""Migration 001: Add ctx_json column to agent_runs table."""
import logging
import sqlite3

from database.migrations import register_migration

logger = logging.getLogger(__name__)

MIGRATION_NAME = "001_add_ctx_json"


def up(conn: sqlite3.Connection) -> None:
    """执行迁移：向 agent_runs 表添加 ctx_json 列。"""
    cursor = conn.execute("PRAGMA table_info(agent_runs)")
    cols = {row[1] for row in cursor.fetchall()}
    if "ctx_json" not in cols:
        conn.execute(
            "ALTER TABLE agent_runs ADD COLUMN ctx_json TEXT DEFAULT NULL"
        )
        logger.info("Migration 001: added ctx_json to agent_runs")
    else:
        logger.info("Migration 001: ctx_json already exists, skipped")


def down(conn: sqlite3.Connection) -> None:
    """回滚迁移（SQLite 不支持 DROP COLUMN，仅打日志）。"""
    logger.warning("Migration 001: cannot drop ctx_json in SQLite, skipped")


# 自动注册到全局迁移列表
register_migration(MIGRATION_NAME, up, down)
