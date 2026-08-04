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
        attack_path     TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        severity        TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        severity        TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        details         TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        severity        TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        version         INTEGER DEFAULT 1,  -- #17 规则版本
        engine_type     TEXT    NOT NULL DEFAULT 'rule_engine',
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
        endpoint            TEXT,
        intent              TEXT,
        audit_log_id        INTEGER,
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
        collected_at    TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        collected_at    TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        collected_at    TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        collected_at    TEXT,
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
        source_timestamp TEXT    -- 原始事件时间戳 ISO 8601
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
    # tools — 应急工具主表
    """
    CREATE TABLE IF NOT EXISTS tools (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        description     TEXT DEFAULT '',
        category        TEXT NOT NULL DEFAULT 'other',
        os_type         TEXT DEFAULT 'windows',
        author_id       INTEGER NOT NULL REFERENCES users(id),
        current_version TEXT NOT NULL DEFAULT '1.0.0',
        download_count  INTEGER NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'active',
        tags            TEXT DEFAULT '[]',
        created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tools_category ON tools(category)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tools_status ON tools(status)
    """,
    # tool_versions — 工具版本表
    """
    CREATE TABLE IF NOT EXISTS tool_versions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_id         INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
        version         TEXT NOT NULL,
        file_name       TEXT NOT NULL,
        file_path       TEXT NOT NULL,
        file_size       INTEGER DEFAULT 0,
        file_hash       TEXT DEFAULT '',
        doc_file_name   TEXT DEFAULT '',
        doc_file_path   TEXT DEFAULT '',
        doc_file_type   TEXT DEFAULT '',
        change_log      TEXT DEFAULT '',
        created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tool_versions_tool_id ON tool_versions(tool_id)
    """,
    # tool_downloads — 下载日志表
    """
    CREATE TABLE IF NOT EXISTS tool_downloads (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_id         INTEGER NOT NULL REFERENCES tools(id),
        version_id      INTEGER REFERENCES tool_versions(id),
        user_id         INTEGER REFERENCES users(id),
        ip_address      TEXT DEFAULT '',
        downloaded_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tool_downloads_tool_id ON tool_downloads(tool_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tool_downloads_user_id ON tool_downloads(user_id)
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
    # rule_suppression — 规则抑制表（#18）
    """
    CREATE TABLE IF NOT EXISTS rule_suppression (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name       TEXT    NOT NULL,
        host_id         INTEGER DEFAULT 0,
        suppressed_until TEXT   NOT NULL,
        reason          TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # alerts — 实时告警表
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        case_id         INTEGER REFERENCES cases(id),
        rule_name       TEXT NOT NULL,
        rule_label      TEXT,
        severity        TEXT NOT NULL DEFAULT 'medium',
        status          TEXT NOT NULL DEFAULT 'open',
        title           TEXT NOT NULL,
        detail          TEXT,
        source_pid      INTEGER,
        source_process  TEXT,
        source_path     TEXT,
        source_ip       TEXT,
        count           INTEGER DEFAULT 1,
        first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
        last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
        acknowledged_by TEXT,
        acknowledged_at TEXT,
        resolved_at     TEXT,
        dismissed_reason TEXT
    )
    """,
    # agents — Agent 注册表
    """
    CREATE TABLE IF NOT EXISTS agents (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL UNIQUE REFERENCES hosts(id) ON DELETE CASCADE,
        agent_id        TEXT NOT NULL UNIQUE,
        agent_version   TEXT,
        os_type         TEXT,
        collectors      TEXT,
        status          TEXT DEFAULT 'offline',
        last_heartbeat  TEXT,
        ip_address      TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # normalized_logs — 范式化日志表
    """
    CREATE TABLE IF NOT EXISTS normalized_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        host_id         INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
        hostname        TEXT,
        log_source      TEXT NOT NULL,
        event_id        INTEGER DEFAULT 0,
        event_type      TEXT NOT NULL,
        event_label     TEXT,
        mitre_attack    TEXT,
        severity        TEXT DEFAULT 'info',
        timestamp       TEXT NOT NULL,
        source_ip       TEXT,
        source_hostname TEXT,
        target_ip       TEXT,
        target_hostname TEXT,
        user_name       TEXT,
        user_domain     TEXT,
        logon_session   TEXT,
        process_name    TEXT,
        process_pid     INTEGER,
        parent_process_name TEXT,
        parent_process_pid  INTEGER,
        command_line    TEXT,
        object_name     TEXT,
        tags            TEXT,
        description     TEXT,
        raw_data        TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # detection_policies — 检测策略表
    """
    CREATE TABLE IF NOT EXISTS detection_policies (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        description     TEXT DEFAULT '',
        is_active       INTEGER DEFAULT 0,
        enable_rag      INTEGER DEFAULT 0,
        enable_attack_chain INTEGER DEFAULT 0,
        parent_id       INTEGER REFERENCES detection_policies(id),
        rule_count      INTEGER DEFAULT 0,
        tags            TEXT DEFAULT '',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # policy_rules — 策略-规则关联表
    """
    CREATE TABLE IF NOT EXISTS policy_rules (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_id       INTEGER NOT NULL REFERENCES detection_policies(id) ON DELETE CASCADE,
        rule_id         INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
        enabled         INTEGER DEFAULT 1,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(policy_id, rule_id)
    )
    """,
    # false_positive_patterns — 误报自学习模式表
    """
    CREATE TABLE IF NOT EXISTS false_positive_patterns (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name       TEXT,
        source_process  TEXT,
        source_ip       TEXT,
        host_id         INTEGER,
        reason          TEXT,
        created_by      TEXT,
        hit_count       INTEGER DEFAULT 0,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # security_events — 安全事件表（分析中心核心表）
    """
    CREATE TABLE IF NOT EXISTS security_events (
        id                  TEXT    PRIMARY KEY,
        timestamp           TEXT    NOT NULL,
        host_id             INTEGER NOT NULL,
        event_type          TEXT    NOT NULL,
        severity            TEXT    NOT NULL DEFAULT 'info',
        source_collector    TEXT    NOT NULL DEFAULT '',
        event_key           TEXT    NOT NULL,
        attack_chain_id     TEXT,
        attack_stage        TEXT,
        ioc_matches         TEXT    DEFAULT '[]',
        evidence            TEXT    DEFAULT '{}',
        ai_verdict          TEXT    DEFAULT '{}',
        status              TEXT    NOT NULL DEFAULT 'pending',
        assignee            TEXT,
        related_events      TEXT    DEFAULT '[]',
        matched_rules       TEXT    DEFAULT '[]',
        matched_at          TEXT    DEFAULT NULL,
        created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # security_events 索引
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_timestamp ON security_events(timestamp)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_host_id ON security_events(host_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_event_type ON security_events(event_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_severity ON security_events(severity)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_status ON security_events(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_attack_stage ON security_events(attack_stage)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_attack_chain_id ON security_events(attack_chain_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_assignee ON security_events(assignee)
    """,
    # 性能优化：matched_rules 查询 + hosts 复合索引
    """
    CREATE INDEX IF NOT EXISTS idx_security_events_matched ON security_events(matched_rules)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_hosts_case_status ON hosts(case_id, status)
    """,
    # status_history — 状态变更审计表
    """
    CREATE TABLE IF NOT EXISTS status_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id        TEXT    NOT NULL REFERENCES security_events(id) ON DELETE CASCADE,
        old_status      TEXT,
        new_status      TEXT    NOT NULL,
        operator        TEXT    NOT NULL DEFAULT '',
        comment         TEXT    DEFAULT '',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_status_history_event_id ON status_history(event_id)
    """,
    # incident_correlations — 事件归并表
    """
    CREATE TABLE IF NOT EXISTS incident_correlations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        title           TEXT NOT NULL,
        description     TEXT,
        severity        TEXT DEFAULT 'medium',
        host_ids        TEXT,
        alert_ids       TEXT,
        timeline_json   TEXT,
        kill_chain      TEXT,
        mitre_ids       TEXT,
        recommendations TEXT,
        status          TEXT DEFAULT 'open',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # agent_imports — Agent JSON 导入记录表（日志检索模块 v2）
    """
    CREATE TABLE IF NOT EXISTS agent_imports (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        import_batch_id TEXT    NOT NULL DEFAULT (''),
        case_id         INTEGER DEFAULT NULL,
        host_id         INTEGER NOT NULL,
        collector_type  TEXT    NOT NULL,
        collector_name  TEXT    DEFAULT '',
        raw_json        TEXT    NOT NULL,
        item_count      INTEGER DEFAULT 1,
        imported_at     TEXT    NOT NULL DEFAULT (datetime('now')),
        event_id        TEXT    DEFAULT NULL,
        event_created   INTEGER DEFAULT 0
    )
    """,
    # agent_imports 索引
    """
    CREATE INDEX IF NOT EXISTS idx_agent_imports_host ON agent_imports(host_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_imports_collector ON agent_imports(collector_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_imports_time ON agent_imports(imported_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_imports_batch ON agent_imports(import_batch_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_imports_event ON agent_imports(event_id)
    """,
    # agent_imports_fts — FTS5 全文索引虚拟表
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS agent_imports_fts USING fts5(
        raw_json, content='agent_imports', content_rowid='id', tokenize='unicode61'
    )
    """,
    # 自动同步触发器：新增 → FTS5 插入
    """
    CREATE TRIGGER IF NOT EXISTS agent_imports_ai AFTER INSERT ON agent_imports BEGIN
        INSERT INTO agent_imports_fts(rowid, raw_json) VALUES (new.id, new.raw_json);
    END
    """,
    # 自动同步触发器：删除 → FTS5 删除
    """
    CREATE TRIGGER IF NOT EXISTS agent_imports_ad AFTER DELETE ON agent_imports BEGIN
        INSERT INTO agent_imports_fts(agent_imports_fts, rowid, raw_json) VALUES('delete', old.id, old.raw_json);
    END
    """,
    # 自动同步触发器：更新 → FTS5 先删后插
    """
    CREATE TRIGGER IF NOT EXISTS agent_imports_au AFTER UPDATE ON agent_imports BEGIN
        INSERT INTO agent_imports_fts(agent_imports_fts, rowid, raw_json) VALUES('delete', old.id, old.raw_json);
        INSERT INTO agent_imports_fts(rowid, raw_json) VALUES (new.id, new.raw_json);
    END
    """,
    # audit_logs — 审计日志表
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER REFERENCES users(id),
        username        TEXT NOT NULL,
        action_type     TEXT NOT NULL,
        detail          TEXT,
        target_type     TEXT,
        target_id       TEXT,
        ip_address      TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action_type)
    """,
    # system_settings — 系统参数表
    """
    CREATE TABLE IF NOT EXISTS system_settings (
        key             TEXT PRIMARY KEY,
        value           TEXT NOT NULL,
        description     TEXT,
        value_type      TEXT DEFAULT 'string',
        updated_at      TEXT
    )
    """,
    # import_results — 手工日志导入结果明细表
    """
    CREATE TABLE IF NOT EXISTS import_results (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id       INTEGER NOT NULL REFERENCES import_records(id) ON DELETE CASCADE,
        log_source      TEXT NOT NULL,
        parsed_line     INTEGER NOT NULL,
        event_type      TEXT NOT NULL,
        severity        TEXT DEFAULT 'info',
        event_key_hash  TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_import_results_import_id ON import_results(import_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_import_results_key_hash ON import_results(event_key_hash)
    """,
    # data_purge_log — 清案（被遗忘权）操作留痕表（永不参与任何清除）
    """
    CREATE TABLE IF NOT EXISTS data_purge_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id         INTEGER NOT NULL,
        case_number     TEXT,
        case_name       TEXT,
        operator_id     INTEGER,
        operator_name   TEXT,
        purged_at       TEXT NOT NULL DEFAULT (datetime('now')),
        total_rows      INTEGER,
        table_counts    TEXT,
        snapshot_path   TEXT,
        client_ip       TEXT,
        status          TEXT DEFAULT 'done'
    )
    """,
    # ── ① 多智能体运行主表（第①批 T-F1）──
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT    NOT NULL UNIQUE,
        event_id      TEXT,
        case_id       INTEGER,
        title         TEXT,
        stage         TEXT    NOT NULL DEFAULT 'triage',
        status        TEXT    NOT NULL DEFAULT 'pending',
        current_agent TEXT,
        priority      TEXT    DEFAULT 'P2',
        confidence    REAL    DEFAULT 0.0,
        result_json   TEXT    DEFAULT '{}',
        ctx_json      TEXT    DEFAULT NULL,
        user_id       INTEGER,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_runs_event ON agent_runs(event_id)
    """,
    # ── ② 单步执行审计表（第①批 T-F1）──
    """
    CREATE TABLE IF NOT EXISTS agent_run_steps (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT    NOT NULL,
        stage         TEXT,
        agent         TEXT,
        status        TEXT,
        input_json    TEXT    DEFAULT '{}',
        output_json   TEXT    DEFAULT '{}',
        confidence    REAL    DEFAULT 0.0,
        evidence_json TEXT    DEFAULT '[]',
        audit_log_id  INTEGER,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_run_steps_run ON agent_run_steps(run_id)
    """,
    # ── ③ 人在回路审批表（第①批 T-F1）──
    """
    CREATE TABLE IF NOT EXISTS hitl_approvals (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id              TEXT    NOT NULL,
        step_id             INTEGER,
        action              TEXT    NOT NULL,
        target_json         TEXT    DEFAULT '{}',
        requested_by        INTEGER,
        status              TEXT    NOT NULL DEFAULT 'pending',
        decided_by          INTEGER,
        decided_at          TEXT,
        auto_rollback_plan  TEXT    DEFAULT '{}',
        reason              TEXT,
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_hitl_status ON hitl_approvals(status)
    """,
    # ── ④ NL 查询审计表（第①批 T-C1）──
    """
    CREATE TABLE IF NOT EXISTS nl_query_audit (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER,
        nl_text         TEXT,
        intent_json     TEXT    DEFAULT '{}',
        executed_sql_json TEXT  DEFAULT '{}',
        row_count       INTEGER DEFAULT 0,
        masked          INTEGER DEFAULT 1,
        status          TEXT    DEFAULT 'ok',
        error_message   TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_nl_audit_user ON nl_query_audit(user_id)
    """,
    # ── ⑤ 语义级事件归并簇表（第③批 T-D1 / P1-D）──
    """
    CREATE TABLE IF NOT EXISTS incident_clusters (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        cluster_id        TEXT NOT NULL UNIQUE,
        title             TEXT,
        severity          TEXT DEFAULT 'medium',
        confidence        REAL DEFAULT 0.0,
        member_event_ids  TEXT DEFAULT '[]',
        host_ids          TEXT DEFAULT '[]',
        summary           TEXT,
        ai_verdict_agg    TEXT DEFAULT '{}',
        created_at        TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_incident_clusters_sev ON incident_clusters(severity)
    """,
    # ── ⑥ 知识库自进化反馈表（第⑤批 T-H1 / P2-H）──
    """
    CREATE TABLE IF NOT EXISTS kb_feedback (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        feedback_type      TEXT NOT NULL DEFAULT 'false_positive',
        is_false_positive  INTEGER DEFAULT 0,
        rule_id            INTEGER,
        alert_id           INTEGER,
        event_id           TEXT,
        rule_name          TEXT,
        host_id            INTEGER,
        content            TEXT,
        source_user        TEXT,
        applied_to_kb      INTEGER DEFAULT 0,
        kb_entry_id        TEXT,
        suppression_id     INTEGER,
        knowledge_draft_id INTEGER,
        entry_ref          TEXT,
        summary            TEXT,
        created_at         TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_kb_feedback_type ON kb_feedback(feedback_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_kb_feedback_applied ON kb_feedback(applied_to_kb)
    """,
    # ── Agent 管理 Phase 2: agent_definitions 表 ──
    """
    CREATE TABLE IF NOT EXISTS agent_definitions (
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
        tools           TEXT DEFAULT '[]',
        model_profile   TEXT DEFAULT '',
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT DEFAULT (datetime('now'))
    )
    """,
    # ── Agent 管理 Phase 2: pipeline_presets 表 ──
    """
    CREATE TABLE IF NOT EXISTS pipeline_presets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        agents      TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT DEFAULT (datetime('now')),
        author      TEXT DEFAULT '',
        category    TEXT DEFAULT 'other',
        tags        TEXT DEFAULT '[]',      -- JSON 数组
        usage_count INTEGER NOT NULL DEFAULT 0,
        last_used_at TEXT
    )
    """,
    # ── F8 护栏门禁（§3）──
    """
    CREATE TABLE IF NOT EXISTS guardrail_policies (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_id       TEXT    NOT NULL UNIQUE,
        name            TEXT    NOT NULL,
        action_pattern  TEXT    NOT NULL,
        whitelist       TEXT    DEFAULT '[]',
        risk_level      TEXT    NOT NULL DEFAULT 'medium',
        require_confirm BOOLEAN DEFAULT 0,
        rollback_plan   TEXT    DEFAULT '',
        enabled         BOOLEAN DEFAULT 1,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guardrail_hits (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_id   TEXT,
        run_id      TEXT,
        action      TEXT    NOT NULL,
        passed      BOOLEAN DEFAULT 0,
        timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── F7 MCP 工具服务端（§2）──
    """
    CREATE TABLE IF NOT EXISTS mcp_servers (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id       TEXT    NOT NULL UNIQUE,
        name            TEXT    NOT NULL,
        transport       TEXT    NOT NULL DEFAULT 'stdio',
        status          TEXT    NOT NULL DEFAULT 'offline',
        command         TEXT,
        args_json       TEXT    DEFAULT '[]',
        url             TEXT,
        env_json        TEXT    DEFAULT '{}',
        tools_count     INTEGER DEFAULT 0,
        last_heartbeat  TEXT,
        schema_json     TEXT    DEFAULT '{}',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_tools (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_id         TEXT    NOT NULL UNIQUE,
        server_id       TEXT    NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
        name            TEXT    NOT NULL,
        description     TEXT    DEFAULT '',
        schema_json     TEXT    DEFAULT '{}',
        idempotency_key TEXT    DEFAULT '',
        timeout_ms      INTEGER DEFAULT 30000,
        retries         INTEGER DEFAULT 0,
        category        TEXT    DEFAULT 'general',
        status          TEXT    NOT NULL DEFAULT 'available',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── 默认闭环规则表（config-default-pipeline：pipeline + 场景条件解耦） ──
    """
    CREATE TABLE IF NOT EXISTS pipeline_default_rules (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        preset_id       INTEGER NOT NULL REFERENCES pipeline_presets(id) ON DELETE CASCADE,
        name            TEXT,
        scene_condition TEXT NOT NULL DEFAULT '{}',
        is_global       INTEGER NOT NULL DEFAULT 0,
        priority_order  INTEGER NOT NULL DEFAULT 0,
        created_by      TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pdr_preset  ON pipeline_default_rules(preset_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_pdr_global ON pipeline_default_rules(is_global)
    """,
    # ── 长期记忆表（P2：agent_memories）────────────────────────
    # 幂等建表 + 5 单列索引（event/host/type/agent/created），对新库旧库均自动生效，
    # 无需 ALTER 迁移；记忆是独立留痕，不建 FK（agent_runs/security_events/hosts
    # 可能被清案/删除，记忆不应被级联删除）。
    """
    CREATE TABLE IF NOT EXISTS agent_memories (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT,                          -- agent_runs.run_id（整管路径）；手动写入/调试可为空
        event_id     TEXT,                          -- security_events.id（关联事件，可为空）
        host_id      INTEGER,                       -- hosts.id（关联主机，可为空）
        agent_name   TEXT    NOT NULL DEFAULT '',   -- 来源 Agent/节点名（root_cause / responder / reporter / llm / <custom>）
        memory_type  TEXT    NOT NULL DEFAULT 'summary',  -- conclusion | summary | action | disposition
        content      TEXT    NOT NULL,              -- 记忆正文（结论/摘要/处置记录）
        source_node  TEXT    DEFAULT '',            -- 来源节点类型（root_cause / action / report / llm ...）
        tags         TEXT    DEFAULT '[]',          -- JSON 数组字符串（如 ["powershell","C2"]）
        created_by   TEXT    DEFAULT 'system',      -- 写入人（API 手动=用户名；自动沉淀=system）
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_memories_event  ON agent_memories(event_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_memories_host   ON agent_memories(host_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_memories_type   ON agent_memories(memory_type)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_memories_agent  ON agent_memories(agent_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_memories_created ON agent_memories(created_at)
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
        timeout=5,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
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
                    severity = ?, enabled = ?, label = ?, source = 'default',
                    mitre_attack = ?, engine_type = 'rule_engine'
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
                    (name, description, category, rule_type, condition, severity, enabled,
                     label, source, mitre_attack, engine_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'default', ?, 'rule_engine')
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


def _alter_security_events_add_matched_rules(conn: sqlite3.Connection) -> None:
    """检测并添加 security_events 表的 matched_rules 列（分析中心规则匹配降噪）."""
    cursor = conn.execute("PRAGMA table_info(security_events)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
    if 'matched_rules' not in existing_columns:
        conn.execute("ALTER TABLE security_events ADD COLUMN matched_rules TEXT DEFAULT '[]'")
        logger.info("Migrated: security_events.matched_rules")
    if 'matched_at' not in existing_columns:
        conn.execute("ALTER TABLE security_events ADD COLUMN matched_at TEXT DEFAULT NULL")
        logger.info("Migrated: security_events.matched_at")


def _alter_security_events_add_ai_verdict(conn: sqlite3.Connection) -> None:
    """检测并添加 security_events 表的 ai_verdict 列（AI 降噪研判结果）.

    ai_verdict 存储 AI 对原始事件的研判 JSON，形如 {"label": "suspicious",
    "confidence": 0.9, ...}。该列此前仅在 ai_noise_reduce 服务首次运行时
    通过 ALTER 懒添加，导致未跑过 AI 研判的库（含全新/空库）缺少该列，
    进而使 event_stats / ai_label 筛选等只读接口引用 se.ai_verdict 时抛出
    `no such column: se.ai_verdict` 的 500。

    此处将其提升为规范 schema 的一部分（与 matched_rules 一致），保证任意库
    在 init_db 阶段即具备该列，避免分析中心统计接口崩溃。
    """
    cursor = conn.execute("PRAGMA table_info(security_events)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
    if 'ai_verdict' not in existing_columns:
        conn.execute("ALTER TABLE security_events ADD COLUMN ai_verdict TEXT DEFAULT '{}'")
        logger.info("Migrated: security_events.ai_verdict")


def _alter_security_events_add_ai_analysis(conn: sqlite3.Connection) -> None:
    """检测并添加 security_events 表的 ai_analysis 列（AI 研判详细分析，可选）.

    该列用于承载 LLM 原始分析文本，仅作详情展示（消费者 IncidentCorrelator
    不读取）。使用 PRAGMA 守卫 ALTER，列缺失才添加，可重复执行。
    服务层写回 ai_analysis 用 try/except 包裹，列缺失不阻断 ai_verdict 写回。
    """
    cursor = conn.execute("PRAGMA table_info(security_events)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
    if "ai_analysis" not in existing_columns:
        conn.execute("ALTER TABLE security_events ADD COLUMN ai_analysis TEXT DEFAULT NULL")
        logger.info("Migrated: security_events.ai_analysis")


def _alter_events_create_disposition_log(conn: sqlite3.Connection) -> None:
    """创建 event_disposition_log 表（处置日志，幂等）. """
    cursor = conn.execute("PRAGMA table_info(event_disposition_log)")
    cols = [r[1] for r in cursor.fetchall()]
    if not cols:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_disposition_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                action TEXT NOT NULL,
                operator TEXT NOT NULL DEFAULT '',
                comment TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES security_events(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_disposition_event_id ON event_disposition_log(event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_disposition_created_at ON event_disposition_log(created_at)")
        logger.info("Created table: event_disposition_log")


def _alter_security_events_add_index(conn: sqlite3.Connection) -> None:
    """添加 security_events 的 (host_id, timestamp) 联合索引（时间线查询优化）. """
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_security_events_host_time ON security_events(host_id, timestamp)")
        logger.info("Created index: idx_security_events_host_time")
    except Exception:
        pass


def _alter_cases_priority(conn: sqlite3.Connection) -> None:
    """检测并添加 cases 表的 priority 列."""
    cursor = conn.execute("PRAGMA table_info(cases)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
    if 'priority' not in existing_columns:
        conn.execute("ALTER TABLE cases ADD COLUMN priority TEXT DEFAULT 'medium'")
        logger.info("Migrated: cases.priority")


def _alter_agent_definitions_add_tools_model_profile(conn: sqlite3.Connection) -> None:
    """为存量 agent_definitions 表追加 tools / model_profile 列（Fix A）.

    新库由 DDL_STATEMENTS 的 CREATE TABLE 直接建好；此处仅补齐升级前的旧库。
    使用 PRAGMA table_info 守卫，列缺失才 ALTER ADD COLUMN，可重复执行。
    SQLite 的 ALTER TABLE 不支持 IF NOT EXISTS，必须显式探测。
    """
    cursor = conn.execute("PRAGMA table_info(agent_definitions)")
    existing: set[str] = {row["name"] for row in cursor.fetchall()}
    if "tools" not in existing:
        conn.execute("ALTER TABLE agent_definitions ADD COLUMN tools TEXT DEFAULT '[]'")
        logger.info("Migrated: agent_definitions.tools")
    if "model_profile" not in existing:
        conn.execute("ALTER TABLE agent_definitions ADD COLUMN model_profile TEXT DEFAULT ''")
        logger.info("Migrated: agent_definitions.model_profile")


def _migrate_pipeline_presets_meta(conn: sqlite3.Connection) -> None:
    """检测并添加 pipeline_presets 表的元数据列（幂等）.

    新增 5 列（预设卡片选择器所需）:
      - author        TEXT DEFAULT ''       # 创建人
      - category      TEXT DEFAULT 'other'  # 分类：取证 / 分析 / 处置 / 其他
      - tags          TEXT DEFAULT '[]'     # JSON 数组标签
      - usage_count   INTEGER NOT NULL DEFAULT 0   # 使用次数
      - last_used_at  TEXT                  # 最近使用时间

    新库由 DDL_STATEMENTS 的 CREATE TABLE 直接建好；此处仅补齐升级前的旧库。
    使用 PRAGMA table_info 守卫模式（参考 _migrate_source_timestamp），
    列缺失才 ALTER TABLE ADD COLUMN，可重复执行。
    """
    cursor = conn.execute("PRAGMA table_info(pipeline_presets)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("author", "TEXT DEFAULT ''"),
        ("category", "TEXT DEFAULT 'other'"),
        ("tags", "TEXT DEFAULT '[]'"),
        ("usage_count", "INTEGER NOT NULL DEFAULT 0"),
        ("last_used_at", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE pipeline_presets ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to pipeline_presets table", col_name)


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


def _ensure_index(table: str, name: str, column: str) -> None:
    """安全创建索引（幂等）."""
    try:
        with get_connection() as conn:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({column})")
    except Exception:
        logger.debug("Failed to create index %s on %s(%s)", name, table, column)


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


def _init_agent_memories(conn: sqlite3.Connection) -> None:
    """确保 agent_memories 表存在（幂等：DDL 中用 IF NOT EXISTS）.

    依赖 DDL_STATEMENTS 中的 CREATE TABLE IF NOT EXISTS agent_memories。
    此函数作为显式钩子，方便将来在此处添加长期记忆相关的迁移逻辑
    （例如：P2 之后的 updated_at / 向量化扩展位）。
    """
    # DDL 已通过 DDL_STATEMENTS 执行，此处仅做日志记录
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_memories'"
    )
    if cursor.fetchone():
        logger.info("agent_memories table ready")


def _alter_rules_table_stats(conn: sqlite3.Connection) -> None:
    """检测并添加 rules 表效能统计列：hit_count / last_hit_at / avg_risk_score (#10/#16)."""
    cursor = conn.execute("PRAGMA table_info(rules)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("hit_count", "INTEGER DEFAULT 0"),
        ("last_hit_at", "TEXT"),
        ("avg_risk_score", "REAL DEFAULT 0.0"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE rules ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to rules table", col_name)


def _alter_add_column(table: str, column: str, col_type: str) -> None:
    """安全地追加列（SQLite 不支持 IF NOT EXISTS for ALTER TABLE）."""
    with get_connection() as db:
        cursor = db.execute(f"PRAGMA table_info({table})")
        existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
        if column not in existing_columns:
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                logger.info("Added column %s.%s", table, column)
            except Exception:
                logger.debug("Column %s.%s already exists", table, column)


def _alter_incident_reports_table(conn: sqlite3.Connection) -> None:
    """检测并添加 incident_reports 表的新增报告扩展列（T-01）.

    新增 6 列：
      - risk_score              INTEGER DEFAULT 0     # 风险评分
      - confidence_metadata     TEXT                   # 各段落置信度 JSON
      - version                 INTEGER DEFAULT 1      # 报告版本号
      - ai_report_id            INTEGER                # 关联的 AI 分析报告 ID
      - mode                    TEXT DEFAULT 'auto'    # 生成模式
      - report_label            TEXT                   # 额外标签
    """
    # 检查表是否存在，不存在则创建
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='incident_reports'"
    )
    if not cursor.fetchone():
        conn.execute(
            """CREATE TABLE IF NOT EXISTS incident_reports (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id           INTEGER REFERENCES hosts(id) ON DELETE SET NULL,
                case_id           INTEGER,
                title             TEXT,
                content           TEXT,
                report_type       TEXT DEFAULT 'analysis',
                audience          TEXT DEFAULT 'leader',
                status            TEXT DEFAULT 'draft',
                risk_level        TEXT,
                risk_score        INTEGER DEFAULT 0,
                summary           TEXT DEFAULT '',
                impact_scope      TEXT DEFAULT '{}',
                timeline_json     TEXT DEFAULT '[]',
                mitre_cover       TEXT DEFAULT '[]',
                evidence          TEXT DEFAULT '',
                evidence_meta     TEXT,
                recommendations   TEXT DEFAULT '{}',
                confidence_metadata TEXT,
                version           INTEGER DEFAULT 1,
                ai_report_id      INTEGER,
                mode              TEXT DEFAULT 'auto',
                report_label      TEXT,
                created_by        TEXT DEFAULT '',
                created_at        TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        logger.info("Created incident_reports table")

    cursor = conn.execute("PRAGMA table_info(incident_reports)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("risk_score", "INTEGER DEFAULT 0"),
        ("confidence_metadata", "TEXT"),
        ("version", "INTEGER DEFAULT 1"),
        ("ai_report_id", "INTEGER"),
        ("mode", "TEXT DEFAULT 'auto'"),
        ("report_label", "TEXT"),
        ("evidence_meta", "TEXT"),
        # T-05: 报告 API 所需字段（与 app/api/report.py DDL 对齐）
        ("audience", "TEXT DEFAULT 'leader'"),
        ("summary", "TEXT DEFAULT ''"),
        ("impact_scope", "TEXT DEFAULT '{}'"),
        ("timeline_json", "TEXT DEFAULT '[]'"),
        ("mitre_cover", "TEXT DEFAULT '[]'"),
        ("evidence", "TEXT DEFAULT ''"),
        ("recommendations", "TEXT DEFAULT '{}'"),
        ("case_id", "INTEGER"),
        ("created_by", "TEXT DEFAULT ''"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE incident_reports ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to incident_reports table", col_name)


def _fix_incident_reports_host_id_nullable(conn: sqlite3.Connection) -> None:
    """修复 incident_reports.host_id 的 NOT NULL 约束为可空.

    旧版 DDL 创建了 `host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE`，
    但报告 API 新建报告时支持 host_id=0（表示"案件级报告，不关联特定主机"），
    此时应插入 NULL 而非 0。SQLite 不支持 ALTER TABLE DROP NOT NULL，
    因此需要重建表。

    该函数幂等：仅当 host_id 仍为 NOT NULL 时执行重建。
    """
    cursor = conn.execute("PRAGMA table_info(incident_reports)")
    rows = cursor.fetchall()
    col_info: dict[str, sqlite3.Row] = {r["name"]: r for r in rows}
    host_row = col_info.get("host_id")
    if host_row is None or host_row["notnull"] != 1:
        return  # 已为可空或不存在，无需处理

    logger.info("Fixing incident_reports.host_id NOT NULL → nullable ...")

    # 构建完整列定义（从当前 schema 获取，跳过 host_id 的 NOT NULL）
    cols_def: list[str] = []
    for row in rows:
        name = row["name"]
        col_type = row["type"]
        notnull = "NOT NULL" if (row["notnull"] and name != "host_id") else ""
        default_val = row["dflt_value"]
        default = ""
        if default_val is not None:
            # 函数表达式（如 datetime('now')）需要括号包裹
            if "(" in str(default_val):
                default = f"DEFAULT ({default_val})"
            else:
                default = f"DEFAULT {default_val}"
        pk = "PRIMARY KEY AUTOINCREMENT" if row["pk"] else ""
        col_def = f"{name} {col_type}"
        if notnull:
            col_def += f" {notnull}"
        if default:
            col_def += f" {default}"
        if pk:
            col_def += f" {pk}"
        cols_def.append(col_def)

    cols_sql = ",\n                ".join(cols_def)

    # 暂存外键状态，开始重建
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS incident_reports_v2 (
                {cols_sql}
            )
        """)
        col_names = [r["name"] for r in rows]
        col_list = ", ".join(col_names)
        conn.execute(f"INSERT INTO incident_reports_v2 ({col_list}) SELECT {col_list} FROM incident_reports")
        conn.execute("DROP TABLE incident_reports")
        conn.execute("ALTER TABLE incident_reports_v2 RENAME TO incident_reports")
        logger.info("Successfully recreated incident_reports with nullable host_id")
    except Exception:
        conn.execute("DROP TABLE IF EXISTS incident_reports_v2")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _create_incident_report_audit_table(conn: sqlite3.Connection) -> None:
    """创建 incident_report_audit 报表审计表（T-01）.

    记录 incident_reports 的所有修改操作，支持字段级追踪.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_report_audit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id     INTEGER NOT NULL REFERENCES incident_reports(id) ON DELETE CASCADE,
            action        TEXT NOT NULL,
            field_name    TEXT,
            old_value     TEXT,
            new_value     TEXT,
            operator      TEXT DEFAULT '',
            comment       TEXT DEFAULT '',
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_incident_report_audit_report ON incident_report_audit(report_id)"
    )
    logger.info("incident_report_audit table ready")


def _migrate_users_table(conn: sqlite3.Connection) -> None:
    """为 users 表追加 is_active / last_login / display_name 列（幂等）."""
    for col, col_type, default in [
        ("is_active", "INTEGER", 1),
        ("last_login", "TEXT", None),
        ("display_name", "TEXT", None),
    ]:
        try:
            if default is not None:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type} DEFAULT {default}")
            else:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except Exception:
            pass


def _migrate_source_timestamp(conn: sqlite3.Connection) -> None:
    """检测并添加 CM 分析表的 source_timestamp TEXT 列（幂等）.

    对 11 张 CM 分析表逐表使用 PRAGMA table_info 守卫模式，
    列缺失才 ALTER TABLE ADD COLUMN，可重复执行。
    """
    tables = [
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
    for table in tables:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
        if "source_timestamp" not in existing_columns:
            try:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN source_timestamp TEXT"
                )
                logger.info("Added column 'source_timestamp' to %s table", table)
            except Exception as exc:
                logger.warning("Failed to add source_timestamp to %s: %s", table, exc)


def _migrate_users_table(conn: sqlite3.Connection) -> None:
    """为 users 表追加 is_active / last_login / display_name 列（幂等）."""
    for col, col_type, default in [
        ("is_active", "INTEGER", 1),
        ("last_login", "TEXT", None),
        ("display_name", "TEXT", None),
    ]:
        try:
            if default is not None:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type} DEFAULT {default}")
            else:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except Exception:
            pass


def _seed_system_settings(conn: sqlite3.Connection) -> None:
    """预置 system_settings 种子数据."""
    defaults = [
        ("ai_auto_analysis", "false", "主机导入后自动触发 AI 分析", "bool"),
        ("alert_aggregation_window", "5", "告警聚合窗口（分钟）", "int"),
        ("events_page_size", "50", "分析中心事件列表默认分页条数", "int"),
        ("max_upload_file_mb", "500", "手工上传日志单文件大小上限", "int"),
        ("log_retention_days", "90", "安全事件保留天数", "int"),
        ("upload_file_retention_days", "7", "上传日志文件保留天数", "int"),
    ]
    for key, value, desc, vtype in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO system_settings (key, value, description, value_type) VALUES (?, ?, ?, ?)",
            (key, value, desc, vtype),
        )


def _migrate_import_records() -> None:
    """为 import_records 表追加手工日志导入相关列（幂等）."""
    with get_connection() as conn:
        for col, col_type in [
            ("log_type", "TEXT"),
            ("file_size", "INTEGER"),
            ("parsed_count", "INTEGER"),
            ("event_count", "INTEGER"),
            ("task_id", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE import_records ADD COLUMN {col} {col_type}")
            except Exception:
                pass  # 列已存在则忽略
        conn.commit()


def _create_rule_drafts_table(conn: sqlite3.Connection) -> None:
    """创建规则草稿表（P0-B）：AI 生成的候选检测规则，经影子运行与人审后启用."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rule_drafts (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            name                 TEXT    NOT NULL UNIQUE,
            category             TEXT,
            rule_type            TEXT,
            condition_json       TEXT    DEFAULT '{}',
            severity             TEXT    DEFAULT 'medium',
            label                TEXT,
            status               TEXT    NOT NULL DEFAULT 'draft',
            shadow_hit_count     INTEGER DEFAULT 0,
            sample_hits_json     TEXT,
            source               TEXT    DEFAULT 'ai',
            generated_by         INTEGER,
            reviewed_by          INTEGER,
            reject_reason        TEXT,
            rationale            TEXT,
            expected_fields      TEXT,
            confidence           REAL,
            dsl                  TEXT,
            hit_count            INTEGER DEFAULT 0,
            false_positive_count INTEGER DEFAULT 0,
            tuned_version        INTEGER DEFAULT 0,
            tuning_history_json  TEXT,
            parent_draft_id      INTEGER,
            created_at           TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _alter_rules_table_for_shadow(conn: sqlite3.Connection) -> None:
    """为 rules 表追加影子运行支持列（P0-B），幂等."""
    for col, col_type in [
        ("is_shadow", "INTEGER DEFAULT 0"),
        ("shadow_hit_count", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE rules ADD COLUMN {col} {col_type}")
        except Exception:
            pass  # 列已存在则忽略


def _alter_rules_add_engine_type(conn: sqlite3.Connection) -> None:
    """检测并添加 rules 表 engine_type 列（T02），幂等."""
    cursor = conn.execute("PRAGMA table_info(rules)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}
    if "engine_type" not in existing_columns:
        conn.execute(
            "ALTER TABLE rules ADD COLUMN engine_type TEXT NOT NULL DEFAULT 'rule_engine'"
        )
        logger.info("Added column 'engine_type' to rules table")


def _migrate_rules_governance(conn: sqlite3.Connection) -> None:
    """检测并添加 rules 表生命周期治理列 + 创建 rule_history 表（T-P1-1）.

    使用 PRAGMA table_info 检测列是否已存在，不存在才 ALTER ADD COLUMN，
    保证旧行不被破坏、可重复执行。
    """
    cursor = conn.execute("PRAGMA table_info(rules)")
    existing_columns: set[str] = {row["name"] for row in cursor.fetchall()}

    new_columns: list[tuple[str, str]] = [
        ("owner", "TEXT"),
        ("created_by", "TEXT"),
        ("status", "TEXT DEFAULT 'active'"),
        ("deprecated_at", "TEXT"),
        ("approved_by", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE rules ADD COLUMN {col_name} {col_type}"
            )
            logger.info("Added column '%s' to rules table", col_name)

    # 创建 rule_history 表（版本快照 + 审批留痕，回滚用）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rule_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id     INTEGER NOT NULL,
            version     INTEGER NOT NULL,
            snapshot    TEXT NOT NULL,
            action      VARCHAR(8) NOT NULL,
            operator    VARCHAR(64) NOT NULL,
            comment     TEXT DEFAULT '',
            approved_by VARCHAR(64) DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rule_id) REFERENCES rules(id)
        )
        """
    )
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rule_history_rule_id ON rule_history(rule_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rule_history_version ON rule_history(rule_id, version)"
        )
    except Exception:
        pass
    logger.info("rule_history table ready")


def _init_guardrail_mcp(conn: sqlite3.Connection) -> None:
    """F7/F8 表建立后的辅助索引（DDL 已通过 DDL_STATEMENTS 幂等创建）。

    与既有 _ensure_index 模式一致：安全创建索引，失败仅记录日志，可重复执行。
    """
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_guardrail_hits_policy "
            "ON guardrail_hits(policy_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_guardrail_hits_ts "
            "ON guardrail_hits(timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_guardrail_policies_enabled "
            "ON guardrail_policies(enabled)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mcp_tools_server "
            "ON mcp_tools(server_id)"
        )
        logger.info("F7/F8 guardrail & mcp tables/indexes ready")
    except Exception as exc:
        logger.debug("F7/F8 index init skipped: %s", exc)


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
        # 手工日志导入：import_records 表迁移（追加列）
        _migrate_import_records()
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
        _alter_rules_table_stats(conn)
        _alter_rules_add_engine_type(conn)
        # 规则草稿表 + 影子运行列（P0-B）
        _create_rule_drafts_table(conn)
        _alter_rules_table_for_shadow(conn)
        # 规则版本管理（P2 #17）
        _alter_add_column("rules", "version", "INTEGER DEFAULT 1")
        # T-P1-1: 规则生命周期治理列 + rule_history 表
        _migrate_rules_governance(conn)
        # T-P2-1: 多租户脚手架 — 幂等加 tenant_id 列
        _alter_add_column("rules", "tenant_id", "INTEGER DEFAULT 0")
        _import_default_rules(conn)
        _alter_abnormal_processes_table(conn)
        _alter_suspicious_connections_table(conn)
        _alter_network_connections_table(conn)
        _import_default_whitelist(conn)
        _import_default_iocs(conn)
        # T-01: incident_reports 扩展列 + 审计表 + host_id 可空修复
        _alter_incident_reports_table(conn)
        _fix_incident_reports_host_id_nullable(conn)
        _create_incident_report_audit_table(conn)
        # v1.3.0 作战化新表
        _create_agent_baselines_table(conn)
        _create_ai_evidence_refills_table(conn)
        # 分析中心规则匹配降噪：security_events 加 matched_rules 列
        _alter_security_events_add_matched_rules(conn)
        # AI 降噪研判结果列：security_events 加 ai_verdict 列（避免 event_stats 等接口 500）
        _alter_security_events_add_ai_verdict(conn)
        # AI 研判详细分析列（P1 可选，缺失不阻断 ai_verdict 写回）
        _alter_security_events_add_ai_analysis(conn)
        # event_disposition_log 表 + security_events 联合索引
        _alter_events_create_disposition_log(conn)
        _alter_security_events_add_index(conn)
        # cases 表扩展（优先级）
        _alter_cases_priority(conn)
        # Fix A: agent_definitions 增加 tools / model_profile 列（兼容存量库）
        _alter_agent_definitions_add_tools_model_profile(conn)
        # 预设选择器元数据：pipeline_presets 增加 author/category/tags/usage_count/last_used_at 列
        _migrate_pipeline_presets_meta(conn)
        # AI 自动知识入库（knowledge_drafts 已通过 DDL 幂等创建）
        _init_knowledge_drafts(conn)
        # 长期记忆表（agent_memories 已通过 DDL 幂等创建，P2）
        _init_agent_memories(conn)
        # 系统设置一期：users 表迁移 + 预置系统参数
        _migrate_users_table(conn)
        _seed_system_settings(conn)
        conn.commit()
        # v3.1: ai_feedback / playbook_presets 表 + ai_audit_log 扩展列
        conn.execute("CREATE TABLE IF NOT EXISTS ai_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, query TEXT, reply TEXT, rating INTEGER, comment TEXT, created_at TEXT DEFAULT (datetime('now')))")
        conn.execute("CREATE TABLE IF NOT EXISTS playbook_presets (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT, steps TEXT, tags TEXT, created_at TEXT DEFAULT (datetime('now')))")
        # ai_audit_log 补齐 endpoint / intent 列（DLL已有 total_tokens/latency_ms/model_name）
        for col in [("endpoint", "TEXT"), ("intent", "TEXT"), ("audit_log_id", "INTEGER")]:
            try:
                conn.execute(f"ALTER TABLE ai_audit_log ADD COLUMN {col[0]} {col[1]}")
            except Exception:
                pass  # 列已存在
        conn.commit()
        # 实时告警与 Agent 索引
        _ensure_index("alerts", "idx_alerts_host", "host_id")
        _ensure_index("alerts", "idx_alerts_status", "status")
        _ensure_index("alerts", "idx_alerts_severity", "severity")
        _ensure_index("alerts", "idx_alerts_last_seen", "last_seen_at")
        _ensure_index("agents", "idx_agents_host", "host_id")
        _ensure_index("agents", "idx_agents_agent_id", "agent_id")
        # source_timestamp 迁移：CM 分析表追加列
        _migrate_source_timestamp(conn)
        # F7/F8 护栏与 MCP 表索引（DDL 已建表，此处补索引）
        _init_guardrail_mcp(conn)
        logger.info("Database initialized successfully at %s", settings.DB_PATH)
    except Exception:
        conn.rollback()
        logger.exception("Database initialization failed")
        raise
    finally:
        conn.close()
