"""Fix A 单元测试 + 集成测试：agent_definitions.tools / model_profile。

覆盖：
- dataclass 往返：from_dict → to_dict 含 tools / model_profile，且缺省为 [] / ''。
- create → get 往返：写入后回读 tools / model_profile 与入参一致。
- update 持久化：tools / model_profile 局部更新并落盘（直接查库验证）。
- 空值默认：未传时默认 [] / ''。
- 存量库 ALTER 迁移：对仅含旧 schema 的临时 sqlite 调 init_db，
  验证 agent_definitions 被补齐 tools / model_profile 两列。

DB 走隔离临时 SQLite（绝不触碰 backend/data/ir.db）。
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import sys

_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.config as config
from app.database import init_db, get_connection
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry


def _make_isolated_db() -> str:
    """创建临时 SQLite 并建表，返回路径（同时设置 settings.DB_PATH）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_fixa_")
    os.close(fd)
    config.settings.DB_PATH = path
    init_db()
    return path


def _cleanup_db(path: str) -> None:
    """清理临时库及其 WAL/SHM 附属文件，并还原 settings.DB_PATH。"""
    orig = getattr(_cleanup_db, "_orig", None)
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    if orig is not None and config.settings.DB_PATH == path:
        config.settings.DB_PATH = orig


class TestAgentToolsModelProfile:
    # ── dataclass 层 ──
    def test_dataclass_roundtrip(self):
        d = AgentDefinition.from_dict({
            "name": "a", "display_name": "A",
            "tools": ["t1", "t2"], "model_profile": "p1",
        })
        dd = d.to_dict()
        assert dd["tools"] == ["t1", "t2"]
        assert dd["model_profile"] == "p1"

    def test_dataclass_defaults(self):
        d = AgentDefinition.from_dict({"name": "a", "display_name": "A"})
        assert d.tools == []
        assert d.model_profile == ""

    # ── 集成层（隔离 DB） ──
    def test_create_get_roundtrip(self):
        path = _make_isolated_db()
        try:
            reg = AgentRegistry()
            reg.register(AgentDefinition(
                name="a1", display_name="A1",
                tools=["t1"], model_profile="p1",
            ))
            got = reg.get("a1")
            assert got.tools == ["t1"]
            assert got.model_profile == "p1"
        finally:
            _cleanup_db(path)

    def test_update_persist(self):
        path = _make_isolated_db()
        try:
            reg = AgentRegistry()
            reg.register(AgentDefinition(name="a2", display_name="A2"))
            reg.update("a2", {"tools": ["t3", "t4"], "model_profile": "p2"})
            got = reg.get("a2")
            assert got.tools == ["t3", "t4"]
            assert got.model_profile == "p2"
            # 直接查库确认已落盘（JSON 序列化 + 纯文本）
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT tools, model_profile FROM agent_definitions WHERE name='a2'"
                ).fetchone()
            assert json.loads(row["tools"]) == ["t3", "t4"]
            assert row["model_profile"] == "p2"
        finally:
            _cleanup_db(path)

    def test_empty_defaults(self):
        path = _make_isolated_db()
        try:
            reg = AgentRegistry()
            reg.register(AgentDefinition(name="a3", display_name="A3"))
            got = reg.get("a3")
            assert got.tools == []
            assert got.model_profile == ""
        finally:
            _cleanup_db(path)

    def test_old_db_alter_migration(self):
        """存量库（无 tools/model_profile 两列）→ 调 init_db 自动 ALTER 补齐。"""
        fd, path = tempfile.mkstemp(suffix=".db", prefix="qa_fixa_old_")
        os.close(fd)
        _cleanup_db._orig = config.settings.DB_PATH
        config.settings.DB_PATH = path
        try:
            # 1) 仅建旧 schema（不含 Fix A 两列）
            conn = sqlite3.connect(path)
            conn.execute(
                """
                CREATE TABLE agent_definitions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL UNIQUE,
                    display_name    TEXT NOT NULL,
                    type            TEXT NOT NULL DEFAULT 'custom',
                    description     TEXT DEFAULT '',
                    data_sources    TEXT DEFAULT '[]',
                    depends_on      TEXT DEFAULT '[]',
                    prompt_template TEXT DEFAULT '',
                    config          TEXT DEFAULT '{}',
                    enabled         INTEGER NOT NULL DEFAULT 1,
                    hitl            INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT DEFAULT (datetime('now')),
                    updated_at      TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.commit()
            conn.close()

            # 2) 触发迁移：init_db 内 CREATE TABLE IF NOT EXISTS 不会加列，
            #    但 _alter_agent_definitions_add_tools_model_profile 会 ALTER 补齐。
            init_db()

            # 3) 校验列已存在
            with sqlite3.connect(path) as c:
                cols = {r[1] for r in c.execute(
                    "PRAGMA table_info(agent_definitions)"
                ).fetchall()}
            assert "tools" in cols
            assert "model_profile" in cols

            # 4) 旧库老记录经迁移回读默认 [] / ''
            reg = AgentRegistry()
            reg.register(AgentDefinition(name="legacy", display_name="Legacy"))
            got = reg.get("legacy")
            assert got.tools == []
            assert got.model_profile == ""
        finally:
            _cleanup_db(path)
