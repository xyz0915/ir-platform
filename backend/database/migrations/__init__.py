"""数据库迁移包.

用法:
    from database.migrations import run_all
    run_all(conn)  # 应用所有待执行的迁移

自动发现 ``backend/database/migrations/`` 目录下所有 ``*.py`` 迁移文件，
并使用 importlib 动态导入（支持以数字开头的模块名）。
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# 按顺序注册的迁移列表：(名称, up函数, down函数)
_MIGRATIONS: list[tuple[str, Callable, Callable]] = []

# 防止重复发现
_DISCOVERED = False


def register_migration(
    name: str,
    up: Callable,
    down: Callable,
) -> None:
    """注册迁移到全局列表。"""
    _MIGRATIONS.append((name, up, down))


def _discover() -> None:
    """自动发现并导入 migrations 目录下的所有迁移模块。"""
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True

    migrations_dir = Path(__file__).resolve().parent
    # 按文件名排序以保证顺序
    migration_files = sorted(
        f for f in os.listdir(str(migrations_dir))
        if f.endswith(".py") and f != "__init__.py"
    )
    for filename in migration_files:
        module_name = filename[:-3]  # strip .py
        try:
            importlib.import_module(f"database.migrations.{module_name}")
            logger.debug("Discovered migration module: %s", module_name)
        except Exception:
            logger.exception("Failed to load migration module: %s", module_name)


def run_all(conn) -> None:
    """执行所有尚未应用的迁移。"""
    import sqlite3

    _discover()  # 确保所有迁移已加载

    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    for name, up_func, _down_func in _MIGRATIONS:
        exists = conn.execute(
            "SELECT name FROM _migrations WHERE name = ?", (name,)
        ).fetchone()
        if not exists:
            up_func(conn)
            conn.execute(
                "INSERT INTO _migrations (name, applied_at) VALUES (?, datetime('now'))",
                (name,),
            )
            conn.commit()
            logger.info("Migration %s applied", name)
        else:
            logger.debug("Migration %s already applied, skipped", name)
