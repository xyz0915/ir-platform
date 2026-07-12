"""SQLite 数据库连接管理与建表初始化."""

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import sqlite3

from app.config import settings

logger = logging.getLogger(__name__)

# 13 张表的 DDL 建表语句（含新增的 3 张 AI 表 + 1 张旧 ai_config 保留兼容）
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
        details         TEXT,
        risk_score      INTEGER DEFAULT 0,
        matched_rules   TEXT,
        attack_path     TEXT
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
    # ai_config — AI大模型配置表（旧表，保留兼容）
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
    # ai_config_profiles — AI配置多Profile表（新）
    """
    CREATE TABLE IF NOT EXISTS ai_config_profiles (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_name    TEXT    NOT NULL DEFAULT '默认配置',
        provider        TEXT    NOT NULL DEFAULT 'openai',
        api_base_url    TEXT    NOT NULL DEFAULT '',
        api_key         TEXT    NOT NULL DEFAULT '',
        model_name      TEXT    NOT NULL DEFAULT 'gpt-4o',
        max_tokens      INTEGER DEFAULT 4096,
        temperature     REAL    DEFAULT 0.3,
        system_prompt   TEXT    DEFAULT '',
        is_active       INTEGER DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ai_audit_log — AI调用审计日志表
    """
    CREATE TABLE IF NOT EXISTS ai_audit_log (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id             INTEGER,
        host_name           TEXT,
        profile_id          INTEGER,
        profile_name        TEXT,
        model_name          TEXT,
        status              TEXT    NOT NULL DEFAULT 'success',
        prompt_tokens       INTEGER DEFAULT 0,
        completion_tokens   INTEGER DEFAULT 0,
        total_tokens        INTEGER DEFAULT 0,
        latency_ms          INTEGER DEFAULT 0,
        masked_mode         INTEGER DEFAULT 0,
        prompt              TEXT,
        response            TEXT,
        error_message       TEXT,
        ip_address          TEXT,
        user_id             INTEGER,
        created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ai_tasks — AI异步任务状态表
    """
    CREATE TABLE IF NOT EXISTS ai_tasks (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id             INTEGER NOT NULL,
        profile_id          INTEGER,
        status              TEXT    NOT NULL DEFAULT 'pending',
        progress            INTEGER DEFAULT 0,
        progress_message    TEXT,
        report_id           INTEGER,
        error_message       TEXT,
        masked_mode         INTEGER DEFAULT 0,
        created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
        started_at          TEXT,
        completed_at        TEXT
    )
    """,
    # ai_analysis_reports — AI分析报告表（原始建表，ALTER 在 init_db 中处理）
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
    # ai_prompt_versions — AI提示词优化历史版本表
    """
    CREATE TABLE IF NOT EXISTS ai_prompt_versions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id      INTEGER NOT NULL,
        version         INTEGER NOT NULL DEFAULT 1,
        content         TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # iocs — IOC 指标表（T-P1-4，仅管理入库，不参与引擎匹配）
    """
    CREATE TABLE IF NOT EXISTS iocs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ioc_type    TEXT    NOT NULL,
        ioc_value   TEXT    NOT NULL,
        source      TEXT    DEFAULT 'default',
        description TEXT,
        enabled     INTEGER DEFAULT 1,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # threat_intel — IOC 外联威胁情报查询结果表（Enrichment）
    # 保留全历史（不去重）；threat_level 为派生冗余列，便于查询与回灌。
    # ioc_id 可空（部分情报可能未关联 iocs 表主键），不强制约束但保留 FK 语义。
    """
    CREATE TABLE IF NOT EXISTS threat_intel (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ioc_id          INTEGER REFERENCES iocs(id) ON DELETE SET NULL,
        ioc_type        TEXT    NOT NULL,
        ioc_value       TEXT    NOT NULL,
        provider        TEXT    NOT NULL,
        risk_score      INTEGER DEFAULT 0,
        judgments       TEXT,
        tags             TEXT,
        confidence      INTEGER DEFAULT 0,
        attck           TEXT,
        company         TEXT,
        threat_level    TEXT,
        queried_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        raw_summary     TEXT,
        providers       TEXT,
        consensus       TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_threat_intel_ioc_id
        ON threat_intel(ioc_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_threat_intel_value_provider
        ON threat_intel(ioc_value, provider)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_threat_intel_provider_queried
        ON threat_intel(provider, queried_at)
    """,
    # rule_audit_log — 规则变更审计表（T-P2-2）
    """
    CREATE TABLE IF NOT EXISTS rule_audit_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id     INTEGER NOT NULL,
        action      TEXT    NOT NULL,
        changed_by  TEXT,
        old_val     TEXT,
        new_val     TEXT,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # network_connections — 网络连接表（数据采集增强 P1-2）
    """
    CREATE TABLE IF NOT EXISTS network_connections (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        protocol        TEXT,
        local_addr      TEXT,
        local_port      INTEGER,
        remote_addr     TEXT,
        remote_port     INTEGER,
        state           TEXT,
        pid             INTEGER,
        process_name    TEXT,
        collected_at    TEXT
    )
    """,
    # file_hashes — 文件哈希表（数据采集增强 P1-3）
    """
    CREATE TABLE IF NOT EXISTS file_hashes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        file_path       TEXT,
        file_name       TEXT,
        sha256          TEXT,
        is_signed       INTEGER DEFAULT 0,
        signer          TEXT,
        file_size       INTEGER,
        product_name    TEXT,
        product_version TEXT,
        collected_at    TEXT
    )
    """,
    # wmi_subscriptions — WMI 订阅表（数据采集增强 P1-5）
    """
    CREATE TABLE IF NOT EXISTS wmi_subscriptions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        name            TEXT,
        event_filter    TEXT,
        event_consumer  TEXT,
        binding_type    TEXT,
        risk_level      TEXT,
        collected_at    TEXT
    )
    """,
    # registry_keys — 注册表键值表（数据采集增强 P1-6）
    """
    CREATE TABLE IF NOT EXISTS registry_keys (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        key_path        TEXT,
        value_name      TEXT,
        value_type      TEXT,
        value_data      TEXT,
        last_write_time TEXT,
        collected_at    TEXT
    )
    """,
    # process_events — 进程实时事件表（T15 实时事件管道，快照并行检测）
    """
    CREATE TABLE IF NOT EXISTS process_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        event_type      TEXT,        -- process_start / process_exit / remote_thread / etw / amsi ...
        pid             INTEGER,
        ppid            INTEGER,
        process_name    TEXT,
        process_path    TEXT,
        command_line    TEXT,
        parent_name     TEXT,
        session         INTEGER,
        start_time      TEXT,
        event_time      TEXT,        -- 事件时间戳（用于注入窗口/快照间消失判定）
        detail          TEXT,         -- JSON：memory_sections / etw_events / remote_thread_events 等
        collected_at    TEXT
    )
    """,
    # webshells — WebShell 文件型检测命中表（融合扩充 A §2.2）
    """
    CREATE TABLE IF NOT EXISTS webshells (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        path            TEXT,
        name            TEXT,
        sha256          TEXT,
        severity        TEXT,
        risk_score      INTEGER DEFAULT 0,
        matched_rules   TEXT,        -- JSON：命中规则列表
        suspicious_funcs TEXT,       -- JSON：危险函数列表
        obfuscation_score REAL,
        behinder_godzilla_signal INTEGER,
        details         TEXT,        -- JSON：完整 webshell 证据（audit/取证）
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # memory_shells — 内存码（Java 内存马 / PHP 扩展）检测命中表（融合扩充 A §2.2）
    """
    CREATE TABLE IF NOT EXISTS memory_shells (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        pid             INTEGER,
        process_name    TEXT,
        type            TEXT,        -- java_filter | java_agent | php | unknown
        evidence        TEXT,
        severity        TEXT,
        risk_score      INTEGER DEFAULT 0,
        matched_rules   TEXT,        -- JSON：命中规则列表
        details         TEXT,        -- JSON：完整内存马证据（audit/取证）
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # remediation_checklist — 处置清单（任务⑤ 处置闭环）
    """
    CREATE TABLE IF NOT EXISTS remediation_checklist (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id     INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        case_id     INTEGER,
        items       TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # knowledge_drafts — AI 自动知识草稿（AI 自动知识入库）
    """
    CREATE TABLE IF NOT EXISTS knowledge_drafts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id             TEXT,
        analysis_report_id  INTEGER,
        title               TEXT NOT NULL,
        description         TEXT NOT NULL,
        category            TEXT DEFAULT 'auto',
        severity            TEXT DEFAULT 'medium',
        mitre_attack        TEXT,
        pattern             TEXT,
        status              TEXT DEFAULT 'pending',
        source              TEXT DEFAULT 'ai_suggest',
        raw_ioc             TEXT,
        created_at          TEXT,
        reviewed_at         TEXT
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


def _alter_rules_table(conn: sqlite3.Connection) -> None:
    """检测并添加 rules 表新增列：label / source / mitre_attack（F-1）.

    使用 PRAGMA table_info 检测列是否已存在，不存在才 ALTER ADD COLUMN，
    保证旧行不被破坏、可重复执行。
    """
    cursor = conn.execute("PRAGMA table_info(rules)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("label", "TEXT"),
        ("source", "TEXT DEFAULT 'default'"),
        ("mitre_attack", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE rules ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to rules table", col_name)


def _import_default_rules(conn: sqlite3.Connection) -> dict:
    """导入默认规则集（source 隔离 upsert by name）.

    - 仅对 source='default' 的行按 name 更新；source='user' 的行绝不覆盖。
    - 写入 label 与顶层 mitre_attack 列（T-P2-3 归一化来源）。
    - 通过 loader 聚合读取 rules/*.json 并逐条校验 schema。
    """
    from app.rules import loader

    rules_data = loader.load_default_rules()
    if not rules_data:
        logger.warning("默认规则加载为空，跳过导入")
        return {"updated": 0, "inserted": 0, "preserved": 0, "total": 0}

    cursor = conn.execute("SELECT name, source FROM rules")
    existing: dict[str, str] = {row["name"]: row["source"] for row in cursor.fetchall()}

    updated = 0
    inserted = 0
    preserved = 0

    for rule in rules_data:
        name = rule.get("name", "")
        description = rule.get("description", "")
        category = rule.get("category", "")
        rule_type = rule.get("rule_type", "")
        raw_condition = rule.get("condition", {})
        condition = raw_condition if isinstance(raw_condition, dict) else {}
        condition_str = json.dumps(raw_condition, ensure_ascii=False)
        severity = rule.get("severity", "medium")
        enabled = 1 if rule.get("enabled", True) else 0
        label = rule.get("label")
        meta = condition.get("_meta", {}) if isinstance(condition, dict) else {}
        mitre_attack = (
            (meta.get("mitre_attack") if isinstance(meta, dict) else None)
            or (condition.get("mitre_attack") if isinstance(condition, dict) else None)
        )

        if name in existing:
            if existing[name] == "user":
                # 用户自定义规则，绝不覆盖
                preserved += 1
                continue
            conn.execute(
                """
                UPDATE rules
                SET description = ?, category = ?, rule_type = ?, condition = ?,
                    severity = ?, enabled = ?, label = ?, source = 'default', mitre_attack = ?
                WHERE name = ?
                """,
                (description, category, rule_type, condition_str, severity, enabled,
                 label, mitre_attack, name),
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO rules
                    (name, description, category, rule_type, condition, severity, enabled, label, source, mitre_attack)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'default', ?)
                """,
                (name, description, category, rule_type, condition_str, severity, enabled,
                 label, mitre_attack),
            )
            inserted += 1

    logger.info(
        "Default rules import: updated=%d, inserted=%d, preserved(user)=%d, total_default=%d",
        updated, inserted, preserved, len(rules_data),
    )
    return {"updated": updated, "inserted": inserted, "preserved": preserved, "total": len(rules_data)}


def reset_default_rules() -> dict:
    """重置默认规则（管理员功能，T-P1-6）.

    仅对 source='default' 的行重新 upsert，保留 source='user' 的用户规则。
    """
    with get_connection() as conn:
        stats = _import_default_rules(conn)
    logger.info("Reset default rules: %s", stats)
    return stats


def _import_default_iocs(conn: sqlite3.Connection) -> None:
    """种子默认 IOC 示例（source='default'），已存在则跳过（T-P1-4）.

    复用传入的 conn，避免与 init_db 主连接产生跨连接写锁（database is locked）。
    """
    seed = [
        {"ioc_type": "domain", "ioc_value": "malware-c2.example.com",
         "description": "已知恶意 C2 域名（示例种子）", "source": "default"},
        {"ioc_type": "domain", "ioc_value": "botnet-cc.example.net",
         "description": "已知僵尸网络 C2 域名（示例种子）", "source": "default"},
        {"ioc_type": "url", "ioc_value": "http://185.220.101.1/loader",
         "description": "已知恶意下载 URL（示例种子）", "source": "default"},
        {"ioc_type": "ip", "ioc_value": "185.220.101.1",
         "description": "Tor 出口节点（示例种子）", "source": "default"},
    ]
    cursor = conn.execute("SELECT ioc_type, ioc_value FROM iocs")
    seen: set = {(r["ioc_type"], r["ioc_value"]) for r in cursor.fetchall()}
    inserted = 0
    for it in seed:
        key = (it["ioc_type"], it["ioc_value"])
        if key in seen:
            continue
        conn.execute(
            """
            INSERT INTO iocs (ioc_type, ioc_value, source, description, enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (it["ioc_type"], it["ioc_value"], it["source"], it["description"], 1),
        )
        seen.add(key)
        inserted += 1
    logger.info("Default iocs seeded: inserted=%d", inserted)


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


def _alter_network_connections_table(conn: sqlite3.Connection) -> None:
    """检测并添加 network_connections 表的威胁情报列."""
    cursor = conn.execute("PRAGMA table_info(network_connections)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
    new_columns: list[tuple[str, str]] = [
        ("threat_level", "TEXT"),
        ("threat_score", "INTEGER"),
        ("threat_tags", "TEXT"),
        ("enriched_at", "TIMESTAMP"),
    ]
    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(f"ALTER TABLE network_connections ADD COLUMN {col_name} {col_type}")
            logger.info("Added column '%s' to network_connections table", col_name)


def _alter_suspicious_connections_table(conn: sqlite3.Connection) -> None:
    """检测并添加 suspicious_connections 表的新增威胁情报列（一键检测增强）.

    新增列:
      - threat_level  TEXT      # 派生威胁等级 high/medium/low/None
      - threat_score   INTEGER   # 风险评分 0-100
      - threat_tags    TEXT      # JSON 字符串数组
      - enriched_at    TIMESTAMP # 最近一次 enrichment 时间

    使用 PRAGMA table_info 检测列是否已存在，不存在才 ALTER ADD COLUMN，
    保证旧行不被破坏、可重复执行（兼容已存在的库）。
    """
    cursor = conn.execute("PRAGMA table_info(suspicious_connections)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("threat_level", "TEXT"),
        ("threat_score", "INTEGER"),
        ("threat_tags", "TEXT"),
        ("enriched_at", "TIMESTAMP"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE suspicious_connections ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to suspicious_connections table", col_name)


def _alter_ai_analysis_reports_table(conn: sqlite3.Connection) -> None:
    """检测并添加 ai_analysis_reports 表的新增列."""
    cursor = conn.execute("PRAGMA table_info(ai_analysis_reports)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("version", "INTEGER DEFAULT 1"),
        ("profile_id", "INTEGER"),
        ("is_latest", "INTEGER DEFAULT 1"),
        ("masked_mode", "INTEGER DEFAULT 0"),
        ("prompt_tokens", "INTEGER DEFAULT 0"),
        ("completion_tokens", "INTEGER DEFAULT 0"),
        ("data_hash", "TEXT"),
        ("cached_at", "TEXT"),
        ("conversation_id", "TEXT"),
        ("analysis_type", "TEXT DEFAULT 'full'"),
        ("module_type", "TEXT"),
        ("ai_payload", "TEXT"),
        ("audience", "TEXT"),
        ("mitre_attack", "TEXT"),
        ("attack_chain_hits", "TEXT"),
        ("rare_high_signals", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE ai_analysis_reports ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to ai_analysis_reports table", col_name)


def _alter_threat_intel_table(conn: sqlite3.Connection) -> None:
    """检测并添加 threat_intel 表的多源聚合新列（任务④）."""
    cursor = conn.execute("PRAGMA table_info(threat_intel)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("providers", "TEXT"),
        ("consensus", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE threat_intel ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to threat_intel table", col_name)


def _alter_ai_tasks_table(conn: sqlite3.Connection) -> None:
    """检测并添加 ai_tasks 表的新增列（mode, focus_area）."""
    cursor = conn.execute("PRAGMA table_info(ai_tasks)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("mode", "TEXT DEFAULT 'standard'"),
        ("focus_area", "TEXT"),
        ("base_report_id", "INTEGER"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE ai_tasks ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to ai_tasks table", col_name)


def _alter_ai_audit_log_table(conn: sqlite3.Connection) -> None:
    """检测并添加 ai_audit_log 表的新增列（prompt, response）."""
    cursor = conn.execute("PRAGMA table_info(ai_audit_log)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("prompt", "TEXT"),
        ("response", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE ai_audit_log ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to ai_audit_log table", col_name)


def _alter_ai_config_profiles_table(conn: sqlite3.Connection) -> None:
    """检测并添加 ai_config_profiles 表的新增列（owner_user_id, is_public）."""
    cursor = conn.execute("PRAGMA table_info(ai_config_profiles)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("owner_user_id", "INTEGER DEFAULT 1"),
        ("is_public", "INTEGER DEFAULT 1"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE ai_config_profiles ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to ai_config_profiles table", col_name)


def _create_agent_baselines_table(conn: sqlite3.Connection) -> None:
    """创建 agent_baselines 表（v1.3.0 支柱③ 差分基线）."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_baselines (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id       INTEGER NOT NULL,
            baseline_json TEXT NOT NULL,
            source        TEXT DEFAULT 'uploaded',
            note          TEXT,
            created_at    TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_baselines_host ON agent_baselines(host_id)"
    )


def _create_ai_evidence_refills_table(conn: sqlite3.Connection) -> None:
    """创建 ai_evidence_refills 表（v1.3.0 R2-3 只读派发回填证据）."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_evidence_refills (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id         INTEGER NOT NULL,
            dispatch_task_id INTEGER NOT NULL,
            action_type     TEXT,
            target          TEXT,
            evidence_json   TEXT,
            status          TEXT DEFAULT 'completed',
            created_at      TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_evidence_refills_host ON ai_evidence_refills(host_id)"
    )


def _migrate_old_ai_config(conn: sqlite3.Connection) -> None:
    """将旧 ai_config 表数据迁移到 ai_config_profiles.

    检查旧 ai_config 表是否有数据，若有则迁移到 ai_config_profiles 的首条记录。
    迁移后设置 is_active=1（如果旧 enabled=1）.
    """
    # 检查 ai_config 表是否存在且有数据
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_config'"
    )
    if cursor.fetchone() is None:
        return

    old_row = conn.execute("SELECT * FROM ai_config ORDER BY id DESC LIMIT 1").fetchone()
    if old_row is None:
        return

    # 检查 ai_config_profiles 是否已有迁移记录
    existing_profile = conn.execute(
        "SELECT id FROM ai_config_profiles WHERE profile_name = '默认配置' LIMIT 1"
    ).fetchone()
    if existing_profile is not None:
        return

    old = dict(old_row)
    is_active = old.get("enabled", 0)
    conn.execute(
        """
        INSERT INTO ai_config_profiles
        (profile_name, provider, api_base_url, api_key, model_name,
         max_tokens, temperature, system_prompt, is_active)
        VALUES (?, 'openai', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "默认配置",
            old.get("api_base_url", ""),
            old.get("api_key", ""),
            old.get("model_name", "gpt-4o"),
            old.get("max_tokens", 4096),
            old.get("temperature", 0.3),
            old.get("system_prompt", ""),
            is_active,
        ),
    )
    logger.info("Migrated old ai_config data to ai_config_profiles")


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


def _alter_timeline_events_table(conn: sqlite3.Connection) -> None:
    """检测并添加 timeline_events 表的新增列（V1-5 时间线增强）.

    新增 6 列:
      - kill_chain_stage      TEXT     MITRE ATT&CK 战术阶段
      - mitre_technique_id    TEXT     MITRE ATT&CK 技术 ID
      - status                TEXT     处置状态，默认 'new'
      - assigned_to           TEXT     指派给
      - resolution            TEXT     处置备注
      - ioc_hit_id            INTEGER  IOC 命中外键 REFERENCES ioc_hits(id)

    使用 try/except 包裹逐列 ALTER，列已存在则跳过（兼容重复执行）.
    """
    cursor = conn.execute("PRAGMA table_info(timeline_events)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("kill_chain_stage", "TEXT"),
        ("mitre_technique_id", "TEXT"),
        ("status", "TEXT DEFAULT 'new'"),
        ("assigned_to", "TEXT"),
        ("resolution", "TEXT"),
        ("ioc_hit_id", "INTEGER REFERENCES ioc_hits(id)"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            try:
                conn.execute(
                    f"ALTER TABLE timeline_events ADD COLUMN {col_name} {col_type}"
                )
                logger.info("Added column '%s' to timeline_events table", col_name)
            except Exception as exc:
                logger.warning("Failed to add column '%s' to timeline_events: %s", col_name, exc)


def _create_timeline_event_audit_table(conn: sqlite3.Connection) -> None:
    """创建 timeline_event_audit 处置审计表（V3-2）.

    记录事件状态变更历史，包含 old_status/new_status/operator/comment.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS timeline_event_audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER NOT NULL REFERENCES timeline_events(id) ON DELETE CASCADE,
            old_status  TEXT,
            new_status  TEXT,
            operator    TEXT,
            comment     TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_timeline_event_audit_event ON timeline_event_audit(event_id)"
    )
    logger.info("timeline_event_audit table ready")


def _alter_ai_analysis_reports_table_v2(conn: sqlite3.Connection) -> None:
    """检测并添加 ai_analysis_reports 表的 source_event_id 列（V2-6）.

    source_event_id 存储 JSON 数组字符串，用于将 AI key_events 与 timeline_events 建立关联.
    """
    cursor = conn.execute("PRAGMA table_info(ai_analysis_reports)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    if "source_event_id" not in existing_columns:
        try:
            conn.execute(
                "ALTER TABLE ai_analysis_reports ADD COLUMN source_event_id TEXT"
            )
            logger.info("Added column 'source_event_id' to ai_analysis_reports table")
        except Exception as exc:
            logger.warning("Failed to add column 'source_event_id': %s", exc)


def _init_knowledge_drafts(conn: sqlite3.Connection) -> None:
    """确保 knowledge_drafts 表存在（幂等：DDL 中用 IF NOT EXISTS）.

    依赖 DDL_STATEMENTS 中的 CREATE TABLE IF NOT EXISTS knowledge_drafts。
    此函数作为显式钩子，方便将来在此处添加知识草稿相关的迁移逻辑。
    """
    # DDL 已通过 DDL_STATEMENTS 执行，此处仅做日志记录
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_drafts'"
    )
    if cursor.fetchone():
        logger.info("knowledge_drafts table ready")


def init_db() -> None:
    """初始化数据库：创建目录、执行建表语句、迁移旧数据、ALTER表、创建默认用户、导入默认规则、导入默认白名单."""
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
        # 迁移旧 ai_config 数据到 ai_config_profiles
        _migrate_old_ai_config(conn)
        # ALTER ai_analysis_reports 添加新列
        _alter_ai_analysis_reports_table(conn)
        # ALTER ai_analysis_reports 添加 source_event_id 列（V2-6）
        _alter_ai_analysis_reports_table_v2(conn)
        # ALTER ai_tasks 添加 mode/focus_area/base_report_id 列
        _alter_ai_tasks_table(conn)
        # ALTER ai_config_profiles 添加权限隔离列
        _alter_ai_config_profiles_table(conn)
        # ALTER threat_intel 添加多源聚合列（任务④）
        _alter_threat_intel_table(conn)
        # ALTER ai_audit_log 添加 prompt/response 列（审计记录用户提示词与响应原文）
        _alter_ai_audit_log_table(conn)
        # ALTER timeline_events 添加 6 个新列（时间线增强 V1-5）
        _alter_timeline_events_table(conn)
        # 创建 timeline_event_audit 处置审计表（V3-2）
        _create_timeline_event_audit_table(conn)
        conn.commit()
        _create_default_admin(conn)
        _alter_rules_table(conn)
        _import_default_rules(conn)
        _alter_abnormal_processes_table(conn)
        _alter_suspicious_connections_table(conn)
        _alter_network_connections_table(conn)
        _import_default_whitelist(conn)
        _import_default_iocs(conn)
        # v1.3.0 作战化新表
        _create_agent_baselines_table(conn)
        _create_ai_evidence_refills_table(conn)
        # AI 自动知识入库（knowledge_drafts 已通过 DDL 幂等创建）
        _init_knowledge_drafts(conn)
        conn.commit()
        logger.info("Database initialized successfully at %s", settings.DB_PATH)
    except Exception:
        conn.rollback()
        logger.exception("Database initialization failed")
        raise
    finally:
        conn.close()
