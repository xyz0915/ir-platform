"""SQLite 数据库连接管理与建表初始化."""

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import sqlite3

from app.config import settings

logger = logging.getLogger(__name__)

# 13 张表的 DDL 建表语句
DDL_STATEMENTS = [
    # users — 平台用户表
    """
    CREATE TABLE IF NOT EXISTS users (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        username        TEXT    NOT NULL UNIQUE,
        password_hash   TEXT    NOT NULL,
        role            TEXT    DEFAULT 'admin',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # cases — 案件表
    """
    CREATE TABLE IF NOT EXISTS cases (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL,
        case_number     TEXT    UNIQUE,
        description     TEXT,
        status          TEXT    DEFAULT 'open',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # hosts — 主机表
    """
    CREATE TABLE IF NOT EXISTS hosts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id         INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        hostname        TEXT    NOT NULL,
        ip_address      TEXT,
        os_type         TEXT,
        os_version      TEXT,
        status          TEXT    DEFAULT 'pending',
        agent_version   TEXT,
        collection_time TEXT,
        raw_json_path   TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # import_records — 导入记录表
    """
    CREATE TABLE IF NOT EXISTS import_records (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        file_name       TEXT,
        file_path       TEXT,
        status          TEXT,
        error_message   TEXT,
        data_summary    TEXT,
        imported_at     TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # host_profiles — 主机画像表
    """
    CREATE TABLE IF NOT EXISTS host_profiles (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL UNIQUE REFERENCES hosts(id) ON DELETE CASCADE,
        cpu_info        TEXT,
        memory_info     TEXT,
        disk_info       TEXT,
        network_info    TEXT,
        installed_software TEXT,
        user_accounts   TEXT,
        security_products TEXT,
        system_summary  TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # analysis_results — 分析结果汇总表
    """
    CREATE TABLE IF NOT EXISTS analysis_results (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        risk_level      TEXT,
        risk_score      INTEGER DEFAULT 0,
        total_findings  INTEGER DEFAULT 0,
        summary         TEXT,
        details         TEXT,
        analyzed_at     TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # abnormal_processes — 异常进程表
    """
    CREATE TABLE IF NOT EXISTS abnormal_processes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        pid             INTEGER,
        process_name    TEXT,
        process_path    TEXT,
        command_line    TEXT,
        parent_pid      INTEGER,
        parent_name     TEXT,
        reason          TEXT,
        rule_name       TEXT,
        severity        TEXT,
        details         TEXT
    )
    """,
    # suspicious_connections — 可疑外连表
    """
    CREATE TABLE IF NOT EXISTS suspicious_connections (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        protocol        TEXT,
        local_address   TEXT,
        local_port      INTEGER,
        remote_address  TEXT,
        remote_port     INTEGER,
        state           TEXT,
        process_name    TEXT,
        pid             INTEGER,
        reason          TEXT,
        rule_name       TEXT,
        severity        TEXT
    )
    """,
    # suspicious_startup_items — 可疑启动项表
    """
    CREATE TABLE IF NOT EXISTS suspicious_startup_items (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        name            TEXT,
        command         TEXT,
        location        TEXT,
        type            TEXT,
        user            TEXT,
        reason          TEXT,
        rule_name       TEXT,
        severity        TEXT
    )
    """,
    # persistence_items — 持久化痕迹表
    """
    CREATE TABLE IF NOT EXISTS persistence_items (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        type            TEXT,
        name            TEXT,
        command         TEXT,
        location        TEXT,
        user            TEXT,
        is_suspicious   INTEGER DEFAULT 0,
        reason          TEXT,
        details         TEXT
    )
    """,
    # timeline_events — 时间线事件表
    """
    CREATE TABLE IF NOT EXISTS timeline_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        timestamp       TEXT    NOT NULL,
        event_type      TEXT,
        source          TEXT,
        description     TEXT,
        severity        TEXT,
        details         TEXT
    )
    """,
    # ioc_hits — IOC 命中表
    """
    CREATE TABLE IF NOT EXISTS ioc_hits (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        ioc_type        TEXT,
        ioc_value       TEXT,
        matched_in      TEXT,
        context         TEXT,
        severity        TEXT
    )
    """,
    # rules — 分析规则表
    """
    CREATE TABLE IF NOT EXISTS rules (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL,
        description     TEXT,
        category        TEXT,
        rule_type       TEXT,
        condition       TEXT,
        severity        TEXT    DEFAULT 'medium',
        enabled         INTEGER DEFAULT 1,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # whitelist — 白名单表
    """
    CREATE TABLE IF NOT EXISTS whitelist (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        category        TEXT    NOT NULL,
        pattern         TEXT    NOT NULL,
        source          TEXT    DEFAULT 'default',
        description     TEXT,
        enabled         INTEGER DEFAULT 1,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ai_config — AI大模型配置表
    """
    CREATE TABLE IF NOT EXISTS ai_config (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        api_base_url    TEXT    NOT NULL DEFAULT '',
        api_key         TEXT    NOT NULL DEFAULT '',
        model_name      TEXT    NOT NULL DEFAULT 'gpt-4o',
        enabled         INTEGER DEFAULT 0,
        max_tokens      INTEGER DEFAULT 4096,
        temperature     REAL    DEFAULT 0.3,
        system_prompt   TEXT    DEFAULT '',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ai_analysis_reports — AI分析报告表
    """
    CREATE TABLE IF NOT EXISTS ai_analysis_reports (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        case_id         INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        risk_assessment TEXT,
        threat_analysis TEXT,
        timeline_analysis TEXT,
        recommendations TEXT,
        raw_response    TEXT,
        model_used      TEXT,
        tokens_used     INTEGER,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """获取 SQLite 数据库连接的上下文管理器.

    Yields:
        sqlite3.Connection: 数据库连接对象.

    Raises:
        sqlite3.Error: 数据库操作异常时回滚并重新抛出.
    """
    conn = sqlite3.connect(
        settings.DB_PATH,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_default_admin(conn: sqlite3.Connection) -> None:
    """创建默认管理员用户（如果不存在）."""
    cursor = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        (settings.DEFAULT_ADMIN_USER,),
    )
    if cursor.fetchone() is None:
        from passlib.context import CryptContext

        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        password_hash = pwd_context.hash(settings.DEFAULT_ADMIN_PASSWORD)
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (settings.DEFAULT_ADMIN_USER, password_hash, "admin"),
        )
        logger.info("Default admin user created (username=admin, password=admin123)")


def _import_default_rules(conn: sqlite3.Connection) -> None:
    """导入默认规则集（upsert by name — 新增的插入，已有的更新，用户自建的保留）."""
    rules_path = Path(settings.BACKEND_DIR) / "app" / "rules" / "default_rules.json"
    if not rules_path.exists():
        logger.warning("Default rules file not found: %s", rules_path)
        return

    with open(rules_path, "r", encoding="utf-8") as f:
        rules_data = json.load(f)

    # 获取数据库中已有的规则名集合
    cursor = conn.execute("SELECT name FROM rules")
    existing_names: set[str] = {row["name"] for row in cursor.fetchall()}

    updated = 0
    inserted = 0

    for rule in rules_data:
        name = rule.get("name", "")
        description = rule.get("description", "")
        category = rule.get("category", "")
        rule_type = rule.get("rule_type", "")
        condition = json.dumps(rule.get("condition", {}), ensure_ascii=False)
        severity = rule.get("severity", "medium")
        enabled = 1 if rule.get("enabled", True) else 0

        if name in existing_names:
            conn.execute(
                """
                UPDATE rules
                SET description = ?, category = ?, rule_type = ?, condition = ?, severity = ?, enabled = ?
                WHERE name = ?
                """,
                (description, category, rule_type, condition, severity, enabled, name),
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO rules (name, description, category, rule_type, condition, severity, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, description, category, rule_type, condition, severity, enabled),
            )
            inserted += 1

    preserved = len(existing_names) - updated
    logger.info(
        "Default rules import: updated=%d, inserted=%d, preserved(user)=%d, total_default=%d",
        updated, inserted, preserved, len(rules_data),
    )


def _alter_abnormal_processes_table(conn: sqlite3.Connection) -> None:
    """检测并添加 abnormal_processes 表新增的 risk_score/matched_rules/attack_path 列.

    SQLite 不支持单条 ALTER TABLE 添加多列，需分三条语句执行。
    使用 PRAGMA table_info 检测列是否已存在，不存在才 ALTER ADD COLUMN.
    """
    cursor = conn.execute("PRAGMA table_info(abnormal_processes)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("risk_score", "INTEGER DEFAULT 0"),
        ("matched_rules", "TEXT"),
        ("attack_path", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE abnormal_processes ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to abnormal_processes table", col_name)


def _import_default_whitelist(conn: sqlite3.Connection) -> None:
    """导入内置默认白名单项（upsert by category+pattern).

    默认白名单包含系统路径和常见系统进程名。
    """
    # 获取已有的白名单项（category+pattern 组合）
    cursor = conn.execute("SELECT category, pattern FROM whitelist")
    existing_set: set[tuple[str, str]] = {
        (row["category"], row["pattern"]) for row in cursor.fetchall()
    }

    # 默认路径类白名单
    default_paths: list[str] = [
        "C:\\Windows\\System32\\",
        "C:\\Windows\\SysWOW64\\",
        "C:\\Windows\\",
        "C:\\Program Files\\Windows Defender\\",
        "C:\\Program Files\\Microsoft\\",
        "C:\\ProgramData\\Microsoft\\",
        "C:\\Program Files\\Common Files\\",
        "/usr/bin/",
        "/usr/sbin/",
        "/usr/lib/",
        "/bin/",
        "/sbin/",
    ]

    # 默认进程名类白名单
    default_process_names: list[str] = [
        "svchost.exe",
        "csrss.exe",
        "lsass.exe",
        "lsm.exe",
        "smss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "taskhostw.exe",
        "dwm.exe",
        "conhost.exe",
        "rundll32.exe",
        "MsMpEng.exe",
        "SecurityHealthService.exe",
        "NisSrv.exe",
        "explorer.exe",
        "System",
        "sihost.exe",
        "taskhost.exe",
        "RuntimeBroker.exe",
        "SearchIndexer.exe",
    ]

    inserted = 0
    skipped = 0

    # 插入路径类白名单
    for pattern in default_paths:
        key = ("path", pattern)
        if key not in existing_set:
            conn.execute(
                """
                INSERT INTO whitelist (category, pattern, source, description, enabled)
                VALUES (?, ?, 'default', '系统内置路径白名单', 1)
                """,
                ("path", pattern),
            )
            inserted += 1
        else:
            skipped += 1

    # 插入进程名类白名单
    for pattern in default_process_names:
        key = ("process_name", pattern)
        if key not in existing_set:
            conn.execute(
                """
                INSERT INTO whitelist (category, pattern, source, description, enabled)
                VALUES (?, ?, 'default', '系统内置进程名白名单', 1)
                """,
                ("process_name", pattern),
            )
            inserted += 1
        else:
            skipped += 1

    logger.info(
        "Default whitelist import: inserted=%d, skipped(existing)=%d",
        inserted, skipped,
    )


def init_db() -> None:
    """初始化数据库：创建目录、执行建表语句、创建默认用户、导入默认规则、ALTER 表、导入默认白名单."""
    # 确保数据目录存在
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        for ddl in DDL_STATEMENTS:
            conn.execute(ddl)
        conn.commit()
        _create_default_admin(conn)
        _import_default_rules(conn)
        _alter_abnormal_processes_table(conn)
        _import_default_whitelist(conn)
        conn.commit()
        logger.info("Database initialized successfully at %s", settings.DB_PATH)
    except Exception:
        conn.rollback()
        logger.exception("Database initialization failed")
        raise
    finally:
        conn.close()
