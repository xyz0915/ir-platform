# IR 平台数据库架构参考文档

> 版本: v1.0 | 日期: 2026-07-20 | 引擎: SQLite 3（WAL 模式，外键启用）

---

## 一、数据库总览

| # | 模块组 | 表数量 | 核心表 |
|---|--------|--------|--------|
| 1 | 用户与鉴权 | 2 | users, system_settings |
| 2 | 案件与主机 | 3 | cases, hosts, host_profiles |
| 3 | 数据导入 | 4 | import_records, import_results, agent_imports, agent_imports_fts(v) |
| 4 | 检测规则与策略 | 7 | rules, rule_audit_log, rule_history, detection_policies, policy_rules, rule_suppression, rule_drafts |
| 5 | 安全事件与归并 | 6 | security_events, status_history, event_disposition_log, incident_correlations, incident_clusters, alerts |
| 6 | 分析结果与发现 | 14 | analysis_results, abnormal_processes, suspicious_connections, suspicious_startup_items, persistence_items, timeline_events, ioc_hits, network_connections, file_hashes, wmi_subscriptions, registry_keys, webshells, memory_shells, process_events |
| 7 | 范式化日志 | 1 | normalized_logs |
| 8 | 白名单与误报 | 2 | whitelist, false_positive_patterns |
| 9 | IOC 与威胁情报 | 2 | iocs, threat_intel |
| 10 | Agent 注册与基线 | 2 | agents, agent_baselines |
| 11 | AI 分析系统 | 7 | ai_config, ai_config_profiles, ai_audit_log, ai_tasks, ai_analysis_reports, ai_prompt_versions, ai_evidence_refills |
| 12 | 多智能体编排 | 3 | agent_runs, agent_run_steps, hitl_approvals |
| 13 | 处置与报告 | 3 | remediation_checklist, incident_reports, incident_report_audit |
| 14 | 知识管理与反馈 | 2 | knowledge_drafts, kb_feedback |
| 15 | 数据治理 | 2 | data_purge_log, nl_query_audit |
| 16 | 审计日志 | 1 | audit_logs |
| | **总计** | **48 表 + 1 FTS5 虚拟表** | |

---

## 二、功能模块与表映射

### 2.1 用户与鉴权

| 功能点 | 涉及表 |
|--------|--------|
| 用户注册/登录 | users |
| JWT Token 验证 | users |
| 角色权限控制 | users |
| 系统参数配置 | system_settings |
| 操作审计 | audit_logs |

### 2.2 案件管理

| 功能点 | 涉及表 |
|--------|--------|
| 案件 CRUD | cases |
| 案件关联主机 | cases → hosts |
| 案件关联安全事件 | cases → hosts → security_events |
| 案件清案/归档 | data_purge_log |

### 2.3 主机管理

| 功能点 | 涉及表 |
|--------|--------|
| 主机 CRUD | hosts |
| 主机画像 | host_profiles |
| 主机 Agent 注册 | agents |
| 差分基线 | agent_baselines |
| 导入记录 | import_records |

### 2.4 数据导入

| 功能点 | 涉及表 |
|--------|--------|
| Agent JSON 全量导入 | agent_imports, agent_imports_fts |
| Agent JSON 全文检索 | agent_imports_fts (FTS5) |
| 手工日志导入 | import_records, import_results |
| 事件归一化 → 写入 | security_events |

### 2.5 分析中心（核心）

| 功能点 | 涉及表 |
|--------|--------|
| 安全事件列表/筛选/搜索 | security_events |
| 事件状态变更 | security_events, status_history |
| 事件处置 | event_disposition_log |
| 事件归并（规则级） | incident_correlations |
| 事件归并（语义级） | incident_clusters |
| 事件书签/收藏 | security_events.assignee |
| AI 研判 | security_events.ai_verdict |

### 2.6 规则管理

| 功能点 | 涉及表 |
|--------|--------|
| 规则 CRUD | rules |
| 规则分类筛选 | rules |
| 规则导入导出 | rules |
| 规则变更审计 | rule_audit_log |
| 规则历史版本 | rule_history |
| 规则抑制 | rule_suppression |
| 规则草稿/AI 生成 | rule_drafts |
| 检测策略 | detection_policies |
| 策略-规则关联 | policy_rules |
| 误报模式 | false_positive_patterns |

### 2.7 规则匹配引擎

| 功能点 | 涉及表 |
|--------|--------|
| 实时事件规则匹配 | rules, security_events |
| 规则缓存 | rules（内存缓存） |
| 攻击链匹配 | rules, security_events.attack_stage |
| 抑制/误报/白名单闭环 | rule_suppression, false_positive_patterns, whitelist |

### 2.8 数据采集增强

| 功能点 | 涉及表 |
|--------|--------|
| 网络连接 | network_connections |
| 文件哈希 | file_hashes |
| WMI 订阅 | wmi_subscriptions |
| 注册表键值 | registry_keys |
| 进程实时事件 | process_events |

### 2.9 安全分析发现

| 功能点 | 涉及表 |
|--------|--------|
| 分析结果汇总 | analysis_results |
| 异常进程 | abnormal_processes |
| 可疑外连 | suspicious_connections |
| 可疑启动项 | suspicious_startup_items |
| 持久化痕迹 | persistence_items |
| 时间线事件 | timeline_events |
| IOC 命中 | ioc_hits |
| WebShell 检测 | webshells |
| 内存马检测 | memory_shells |

### 2.10 AI 分析

| 功能点 | 涉及表 |
|--------|--------|
| AI 配置 | ai_config_profiles, ai_config（旧） |
| AI 分析报告 | ai_analysis_reports |
| AI 异步任务 | ai_tasks |
| AI 调用审计 | ai_audit_log |
| AI 反馈 | ai_feedback |
| 提示词版本 | ai_prompt_versions |
| 证据回填 | ai_evidence_refills |
| 预案模板 | playbook_presets |

### 2.11 多智能体编排

| 功能点 | 涉及表 |
|--------|--------|
| Agent 运行主记录 | agent_runs |
| 单步审计 | agent_run_steps |
| 人在回路审批 | hitl_approvals |

### 2.12 处置与报告

| 功能点 | 涉及表 |
|--------|--------|
| 处置清单 | remediation_checklist |
| 安全事件报告 | incident_reports |
| 报表审计 | incident_report_audit |

### 2.13 知识管理与反馈

| 功能点 | 涉及表 |
|--------|--------|
| 知识草稿 | knowledge_drafts |
| 知识库自进化反馈 | kb_feedback |

### 2.14 白名单与误报

| 功能点 | 涉及表 |
|--------|--------|
| 白名单管理 | whitelist |
| 误报自学习 | false_positive_patterns |

### 2.15 IOC 与威胁情报

| 功能点 | 涉及表 |
|--------|--------|
| IOC 指标管理 | iocs |
| 外联威胁情报查询 | threat_intel |

### 2.16 范式化日志

| 功能点 | 涉及表 |
|--------|--------|
| 范式化日志检索 | normalized_logs |
| NL 自然语言查询 | normalized_logs, nl_query_audit |

### 2.17 仪表盘

| 功能点 | 涉及表 |
|--------|--------|
| 全局态势统计 | cases, hosts, security_events, rules, analysis_results |
| 实时告警 | alerts |

---

## 三、表说明

### 3.1 用户与鉴权

#### users — 平台用户表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| username | TEXT UNIQUE NN | 用户名 |
| password_hash | TEXT NN | bcrypt 密码哈希 |
| role | TEXT | 角色: admin / analyst / viewer |
| is_active | INTEGER | 是否激活（迁移追加） |
| last_login | TEXT | 最后登录时间（迁移追加） |
| display_name | TEXT | 显示名（迁移追加） |
| created_at | TEXT NN | 创建时间 |

#### system_settings — 系统参数表（KV 存储）

| 字段 | 类型 | 说明 |
|------|------|------|
| key | TEXT PK | 参数键 |
| value | TEXT NN | 参数值 |
| description | TEXT | 参数说明 |
| value_type | TEXT | 值类型: string / int / bool / json |
| updated_at | TEXT | 更新时间 |

### 3.2 案件与主机

#### cases — 案件表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| name | TEXT NN | 案件名称 |
| case_number | TEXT UNIQUE | 案件编号（自动生成） |
| description | TEXT | 案件描述 |
| status | TEXT | open / closed |
| priority | TEXT | 优先级（迁移追加） |
| created_at / updated_at | TEXT NN | 时间戳 |

#### hosts — 主机表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| case_id | INTEGER FK → cases | 归属案件（级联删除） |
| hostname | TEXT NN | 主机名 |
| ip_address | TEXT | IP 地址 |
| os_type / os_version | TEXT | 操作系统 |
| status | TEXT | pending / analyzing / done |
| agent_version | TEXT | Agent 版本 |
| raw_json_path | TEXT | 原始导入 JSON 路径 |
| created_at / updated_at | TEXT NN | 时间戳 |

索引: `idx_hosts_case_status ON hosts(case_id, status)`

#### host_profiles — 主机画像表（1:1）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK UNIQUE → hosts | 关联主机（级联删除） |
| cpu_info / memory_info / disk_info / network_info | TEXT | JSON 硬件信息 |
| installed_software | TEXT | 已安装软件 JSON |
| user_accounts | TEXT | 用户账户 JSON |
| security_products | TEXT | 安全产品 JSON |
| system_summary | TEXT | 系统摘要 |
| created_at | TEXT NN | 创建时间 |

### 3.3 数据导入

#### import_records — 导入记录表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机（级联删除） |
| file_name / file_path | TEXT | 文件信息 |
| status | TEXT | pending / importing / done / error |
| error_message | TEXT | 错误信息 |
| data_summary | TEXT | 导入摘要 JSON |
| log_type / file_size / parsed_count / event_count / task_id | TEXT/INT | 迁移追加列 |
| imported_at | TEXT NN | 导入时间 |

#### import_results — 手工日志导入结果明细

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| import_id | INTEGER FK → import_records | 关联导入记录（级联删除） |
| log_source | TEXT NN | 日志来源 |
| parsed_line | INTEGER NN | 解析行数 |
| event_type | TEXT NN | 生成事件类型 |
| severity | TEXT | 严重度 |
| event_key_hash | TEXT | 去重哈希 |
| created_at | TEXT NN | 创建时间 |

索引: `idx_import_results_import_id`, `idx_import_results_key_hash`

#### agent_imports — Agent JSON 导入记录

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| import_batch_id | TEXT | 导入批次 ID |
| case_id | INTEGER | 关联案件 |
| host_id | INTEGER NN | 关联主机 |
| collector_type | TEXT NN | 采集器类型（processes/services/...） |
| collector_name | TEXT | 采集器名称 |
| raw_json | TEXT NN | 原始 JSON 数据 |
| item_count | INTEGER | 条目数 |
| imported_at | TEXT NN | 导入时间 |
| event_id | TEXT | 关联事件 ID |
| event_created | INTEGER | 是否已生事件 |

索引: 5 个索引（host_id, collector_type, imported_at, import_batch_id, event_id）

#### agent_imports_fts — FTS5 全文索引虚拟表

| 字段 | 类型 | 说明 |
|------|------|------|
| raw_json | FTS5 content | 基于 agent_imports.raw_json 的全文索引 |

> 通过 3 个触发器（INSERT/DELETE/UPDATE）与 agent_imports 保持同步。
> 分词器: `unicode61`，支持中文等 Unicode 字符。

### 3.4 检测规则与策略

#### rules — 分析规则表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| name | TEXT NN | 规则名（英文键） |
| description | TEXT | 规则描述 |
| category | TEXT | 分类: process/network/persistence/behavior/... |
| rule_type | TEXT | 类型: regex/list/threshold/behavior/composite |
| condition | TEXT | 条件 JSON |
| severity | TEXT | severity: critical/high/medium/low/info |
| enabled | INTEGER | 是否启用 |
| label | TEXT | 中文标签（迁移追加） |
| source | TEXT | 来源: default / user / ai（迁移追加） |
| mitre_attack | TEXT | MITRE ATT&CK 编号（迁移追加） |
| hit_count | INTEGER | 命中次数（迁移追加） |
| last_hit_at | TEXT | 最后命中时间（迁移追加） |
| avg_risk_score | REAL | 平均风险分（迁移追加） |
| version | INTEGER | 版本号 |
| created_at / updated_at | TEXT NN | 时间戳 |

#### rule_audit_log — 规则变更审计表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| rule_id | INTEGER NN | 关联规则 ID |
| action | TEXT NN | 操作: create/update/delete/import |
| changed_by | TEXT | 操作人 |
| old_val / new_val | TEXT | 变更前后 JSON |
| created_at | TEXT NN | 操作时间 |

#### rule_history — 规则历史版本表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| rule_id | INTEGER NN | 关联规则 |
| version | INTEGER NN | 版本号 |
| snapshot | TEXT NN | 规则快照 JSON |
| created_at | TEXT NN | 创建时间 |

#### detection_policies — 检测策略表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| name | TEXT NN | 策略名 |
| description | TEXT | 描述 |
| is_active | INTEGER | 是否激活 |
| enable_rag / enable_attack_chain | INTEGER | 特性开关 |
| parent_id | INTEGER FK self-ref | 父策略（策略继承） |
| rule_count | INTEGER | 关联规则数 |
| tags | TEXT | 标签 |
| created_at / updated_at | TEXT NN | 时间戳 |

#### policy_rules — 策略-规则关联表（M:N）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| policy_id | INTEGER FK → detection_policies | 策略 ID（级联删除） |
| rule_id | INTEGER FK → rules | 规则 ID（级联删除） |
| enabled | INTEGER | 是否启用 |
| created_at | TEXT NN | 创建时间 |

> UNIQUE(policy_id, rule_id)

#### rule_suppression — 规则抑制表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| rule_name | TEXT NN | 规则名 |
| host_id | INTEGER | 抑制主机（0=全局） |
| suppressed_until | TEXT NN | 抑制截止时间 |
| reason | TEXT | 抑制原因 |
| created_at | TEXT NN | 创建时间 |

#### rule_drafts — 规则草稿表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| name | TEXT UNIQUE NN | 草稿名 |
| category / rule_type | TEXT | 分类/类型 |
| condition_json | TEXT | 条件 JSON |
| severity | TEXT | 严重度 |
| status | TEXT | draft/active/rejected |
| shadow_hit_count | INTEGER | 影子模式命中数 |
| sample_hits_json | TEXT | 样本命中 JSON |
| source | TEXT | 来源: ai / manual |
| generated_by / reviewed_by | INTEGER | 生成/审核人 |
| rationale | TEXT | AI 推理逻辑 |
| dsl | TEXT | DSL 规则表达式 |
| confidence | REAL | AI 置信度 |
| tuning_history_json | TEXT | 调优历史 |
| parent_draft_id | INTEGER | 父草稿（迭代） |
| created_at / updated_at | TEXT NN | 时间戳 |

#### false_positive_patterns — 误报自学习模式表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| rule_name | TEXT | 规则名 |
| source_process / source_ip | TEXT | 源进程/IP 模式 |
| host_id | INTEGER | 关联主机 |
| reason | TEXT | 误报原因 |
| created_by | TEXT | 创建者 |
| hit_count | INTEGER | 命中次数 |
| created_at | TEXT NN | 创建时间 |

### 3.5 安全事件与归并（核心）

#### security_events — 安全事件表（核心表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK | UUID（SHA256 哈希） |
| timestamp | TEXT NN | 事件时间 |
| host_id | INTEGER NN | 关联主机 |
| event_type | TEXT NN | 类型: process_start/network_outbound/service_operation/... |
| severity | TEXT NN | 严重度: critical/high/medium/low/info |
| source_collector | TEXT NN | 来源采集器: osquery/cm/filebeat/... |
| event_key | TEXT NN | 事件去重键 |
| attack_chain_id | TEXT | 攻击链 ID |
| attack_stage | TEXT | 攻击阶段: initial_access/persistence/... |
| ioc_matches | TEXT（JSON） | IOC 匹配结果 |
| evidence | TEXT（JSON） | 事件证据详情（含路径/命令行等） |
| matched_rules | TEXT（JSON） | 命中规则列表（迁移追加） |
| matched_at | TEXT | 规则匹配时间（迁移追加） |
| ai_verdict | TEXT（JSON） | AI 研判结果（迁移追加） |
| ai_analysis | TEXT（JSON） | AI 分析详情（迁移追加） |
| status | TEXT NN | pending / investigating / resolved / dismissed |
| assignee | TEXT | 指派人 |
| related_events | TEXT（JSON） | 关联事件 ID 列表 |
| created_at / updated_at | TEXT NN | 时间戳 |

> **索引**: timestamp, host_id, event_type, severity, status, attack_stage, attack_chain_id, assignee, matched_rules, host_id+timestamp（复合）
> 
> **数据量**: 核心表，事件列表、筛选、统计、归并全部围绕此表

#### status_history — 安全事件状态变更审计

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| event_id | TEXT FK → security_events | 关联事件（级联删除） |
| old_status / new_status | TEXT | 状态变更前后 |
| operator | TEXT NN | 操作人 |
| comment | TEXT | 备注 |
| created_at | TEXT NN | 操作时间 |

索引: `idx_status_history_event_id`

#### event_disposition_log — 事件处置日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| event_id | TEXT FK → security_events | 关联事件 |
| action | TEXT NN | 处置动作 |
| operator | TEXT NN | 处置人 |
| comment | TEXT | 备注 |
| created_at | TEXT | 处置时间 |

索引: `idx_disposition_event_id`, `idx_disposition_created_at`

#### alerts — 实时告警表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机（级联删除） |
| case_id | INTEGER FK → cases | 关联案件 |
| rule_name / rule_label | TEXT | 命中规则 |
| severity | TEXT NN | 严重度 |
| status | TEXT NN | open / acknowledged / resolved / dismissed |
| title / detail | TEXT | 告警标题/详情 |
| source_pid / source_process / source_path / source_ip | TEXT/INT | 源信息 |
| count | INTEGER | 聚合计数 |
| first_seen_at / last_seen_at | TEXT NN | 首次/最后见到时间 |
| acknowledged_by / acknowledged_at | TEXT | 确认信息 |
| resolved_at / dismissed_reason | TEXT | 解决信息 |

#### incident_correlations — 事件归并表（规则级）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| title | TEXT NN | 归并标题 |
| description | TEXT | 描述 |
| severity | TEXT | 严重度 |
| host_ids | TEXT（JSON） | 关联主机 ID 列表 |
| alert_ids | TEXT（JSON） | 关联告警 ID 列表 |
| timeline_json | TEXT（JSON） | 时间线 |
| kill_chain | TEXT（JSON） | 杀伤链 |
| mitre_ids | TEXT（JSON） | MITRE ATT&CK ID 列表 |
| recommendations | TEXT | 建议 |
| status | TEXT | open / closed |
| created_at / updated_at | TEXT NN | 时间戳 |

#### incident_clusters — 语义级事件归并簇表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| cluster_id | TEXT UNIQUE NN | 归并簇 ID |
| title | TEXT | 标题 |
| severity | TEXT | 严重度 |
| confidence | REAL | AI 置信度 |
| member_event_ids | TEXT（JSON） | 成员事件 ID 列表 |
| host_ids | TEXT（JSON） | 关联主机 ID 列表 |
| summary | TEXT | AI 摘要 |
| ai_verdict_agg | TEXT（JSON） | AI 研判聚合 |
| created_at / updated_at | TEXT NN | 时间戳 |

索引: `idx_incident_clusters_sev`

### 3.6 分析结果与发现

#### analysis_results — 分析结果汇总表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机（级联删除） |
| risk_level / risk_score | TEXT/INT | 风险等级/分数 |
| total_findings | INTEGER | 发现总数 |
| summary | TEXT | 摘要 |
| details | TEXT（JSON） | 分析详情 |
| analyzed_at | TEXT NN | 分析时间 |

#### abnormal_processes — 异常进程表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| pid | INTEGER | 进程 PID |
| process_name / process_path | TEXT | 进程名/路径 |
| command_line | TEXT | 命令行 |
| parent_pid / parent_name | TEXT/INT | 父进程 |
| reason / rule_name | TEXT | 异常原因/命中规则 |
| severity | TEXT | 严重度 |
| risk_score | INTEGER | 风险分 |
| matched_rules | TEXT（JSON） | 命中规则列表 |
| attack_path | TEXT | 攻击路径 |

#### suspicious_connections — 可疑外连表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| protocol | TEXT | 协议 |
| local_address / local_port | TEXT/INT | 本地地址端口 |
| remote_address / remote_port | TEXT/INT | 远程地址端口 |
| state | TEXT | 连接状态 |
| process_name / pid | TEXT/INT | 关联进程 |
| reason / rule_name | TEXT | 可疑原因 |
| severity | TEXT | 严重度 |
| threat_level / threat_score / threat_tags | TEXT/INT | 威胁情报字段（迁移追加） |
| enriched_at | TEXT | 情报丰富时间（迁移追加） |

#### suspicious_startup_items — 可疑启动项表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| name / command | TEXT | 启动项名/命令 |
| location | TEXT | 位置（注册表路径/文件路径） |
| type | TEXT | 类型: registry/startup_folder |
| user | TEXT | 作用用户 |
| reason / rule_name | TEXT | 可疑原因 |
| severity | TEXT | 严重度 |

#### persistence_items — 持久化痕迹表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| type | TEXT | 持久化类型: run_keys/services/startup_folder/... |
| name / command | TEXT | 名称/命令 |
| location | TEXT | 注册表位置 |
| user | TEXT | 用户 |
| is_suspicious | INTEGER | 是否可疑 |
| reason | TEXT | 原因 |
| details | TEXT | 详情 |

#### timeline_events — 时间线事件表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| timestamp | TEXT NN | 事件时间 |
| event_type | TEXT | 事件类型 |
| source | TEXT | 来源 |
| description | TEXT | 描述 |
| severity | TEXT | 严重度 |
| details | TEXT（JSON） | 详情 |
| kill_chain_stage | TEXT | 杀伤链阶段（迁移追加） |
| mitre_technique_id | TEXT | MITRE ID（迁移追加） |
| status | TEXT | 处置状态（迁移追加） |
| ioc_hit_id | INTEGER FK → ioc_hits | IOC 关联（迁移追加） |

#### ioc_hits — IOC 命中表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| ioc_type | TEXT | IOC 类型: ip/domain/hash/... |
| ioc_value | TEXT | IOC 值 |
| matched_in | TEXT | 匹配位置 |
| context | TEXT | 上下文 |
| severity | TEXT | 严重度 |

#### network_connections — 网络连接表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| protocol | TEXT | 协议 |
| local_addr / local_port | TEXT/INT | 本地地址/端口 |
| remote_addr / remote_port | TEXT/INT | 远程地址/端口 |
| state | TEXT | 状态 |
| pid / process_name | INT/TEXT | 关联进程 |
| collected_at | TEXT | 采集时间 |
| threat_level / threat_score / threat_tags | TEXT/INT | 威胁情报字段（迁移追加） |
| enriched_at | TEXT | 丰富时间（迁移追加） |

#### file_hashes — 文件哈希表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| file_path / file_name | TEXT | 文件路径/名 |
| sha256 | TEXT | SHA256 哈希 |
| is_signed / signer | INTEGER/TEXT | 数字签名 |
| file_size | INTEGER | 文件大小 |
| product_name / product_version | TEXT | 产品信息 |
| collected_at | TEXT | 采集时间 |

#### wmi_subscriptions — WMI 订阅表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| name | TEXT | 订阅名 |
| event_filter | TEXT | 事件过滤 |
| event_consumer | TEXT | 事件消费者 |
| binding_type | TEXT | 绑定类型 |
| risk_level | TEXT | 风险等级 |
| collected_at | TEXT | 采集时间 |

#### registry_keys — 注册表键值表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| key_path | TEXT | 键路径 |
| value_name / value_type | TEXT | 值名/类型 |
| value_data | TEXT | 值数据 |
| last_write_time | TEXT | 最后写入时间 |
| collected_at | TEXT | 采集时间 |

#### process_events — 进程实时事件表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| event_type | TEXT | process_start/process_exit/remote_thread/... |
| pid / ppid | INTEGER | 进程 PID/父 PID |
| process_name / process_path | TEXT | 进程名/路径 |
| command_line | TEXT | 命令行 |
| parent_name | TEXT | 父进程名 |
| session | INTEGER | 会话 ID |
| start_time / event_time | TEXT | 时间 |
| detail | TEXT（JSON） | 详情 |
| collected_at | TEXT | 采集时间 |

#### webshells — WebShell 检测命中表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| path / name | TEXT | 文件路径/名 |
| sha256 | TEXT | 哈希 |
| severity | TEXT | 严重度 |
| risk_score | INTEGER | 风险分 |
| matched_rules | TEXT（JSON） | 命中规则 |
| suspicious_funcs | TEXT（JSON） | 可疑函数 |
| obfuscation_score | REAL | 混淆评分 |
| behinder_godzilla_signal | INTEGER | 冰蝎/哥斯拉特征 |
| details | TEXT（JSON） | 详情 |
| created_at | TEXT NN | 创建时间 |

#### memory_shells — 内存马检测命中表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| pid | INTEGER | 进程 PID |
| process_name | TEXT | 进程名 |
| type | TEXT | 类型: java_filter/java_agent/php/unknown |
| evidence | TEXT（JSON） | 证据 |
| severity | TEXT | 严重度 |
| risk_score | INTEGER | 风险分 |
| matched_rules | TEXT（JSON） | 命中规则 |
| details | TEXT（JSON） | 详情 |
| created_at | TEXT NN | 创建时间 |

### 3.7 范式化日志

#### normalized_logs — 范式化日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| hostname | TEXT | 主机名 |
| log_source | TEXT NN | 日志来源: security/eventlog/syslog/... |
| event_id | INTEGER | 原始事件 ID |
| event_type | TEXT NN | 事件类型 |
| event_label | TEXT | 事件标签 |
| mitre_attack | TEXT | MITRE 编号 |
| severity | TEXT | 严重度 |
| timestamp | TEXT NN | 时间戳 |
| source_ip / target_ip | TEXT | 源/目标 IP |
| user_name / user_domain | TEXT | 用户信息 |
| logon_session | TEXT | 登录会话 |
| process_name / process_pid | TEXT/INT | 进程信息 |
| parent_process_name / parent_process_pid | TEXT/INT | 父进程信息 |
| command_line | TEXT | 命令行 |
| object_name | TEXT | 对象名 |
| tags | TEXT（JSON） | 标签 |
| description | TEXT | 描述 |
| raw_data | TEXT | 原始日志 |
| created_at | TEXT NN | 创建时间 |

### 3.8 白名单与误报

#### whitelist — 白名单表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| category | TEXT NN | 分类: process_name/path/signature/... |
| pattern | TEXT NN | 匹配模式 |
| source | TEXT | 来源: default/user |
| description | TEXT | 描述 |
| enabled | INTEGER | 是否启用 |
| created_at | TEXT NN | 创建时间 |

### 3.9 IOC 与威胁情报

#### iocs — IOC 指标表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| ioc_type | TEXT NN | 类型: ip/domain/url/md5/sha1/sha256 |
| ioc_value | TEXT NN | IOC 值 |
| source | TEXT | 来源 |
| description | TEXT | 描述 |
| enabled | INTEGER | 是否启用 |
| created_at | TEXT NN | 创建时间 |

#### threat_intel — 威胁情报查询结果表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| ioc_id | INTEGER FK → iocs | 关联 IOC（SET NULL） |
| ioc_type / ioc_value | TEXT NN | IOC 信息 |
| provider | TEXT NN | 情报提供商 |
| risk_score | INTEGER | 风险分 |
| judgments / tags | TEXT（JSON） | 研判/标签 |
| confidence | INTEGER | 置信度 |
| attck | TEXT（JSON） | MITRE ATT&CK 映射 |
| company / threat_level | TEXT | 关联厂商/威胁等级 |
| queried_at / created_at | TEXT NN | 查询/创建时间 |
| raw_summary | TEXT | 原始摘要 |
| providers | TEXT（JSON） | 多个提供商（迁移追加） |
| consensus | TEXT | 共识（迁移追加） |

### 3.10 Agent 注册与基线

#### agents — Agent 注册表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK UNIQUE → hosts | 关联主机（级联删除） |
| agent_id | TEXT UNIQUE NN | Agent 唯一 ID |
| agent_version | TEXT | Agent 版本 |
| os_type | TEXT | 操作系统 |
| collectors | TEXT（JSON） | 支持的采集器列表 |
| status | TEXT | offline / online |
| last_heartbeat | TEXT | 最后心跳时间 |
| ip_address | TEXT | IP |
| created_at | TEXT NN | 注册时间 |

#### agent_baselines — 主机差分基线表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER NN | 关联主机 |
| baseline_json | TEXT NN | 基线快照 JSON |
| source | TEXT | 来源: uploaded/auto |
| note | TEXT | 备注 |
| created_at | TEXT | 创建时间 |

### 3.11 AI 分析系统

#### ai_config — 旧版 AI 配置表（保留兼容）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| api_base_url / api_key | TEXT | API 配置 |
| model_name | TEXT | 模型名（默认 gpt-4o）|
| enabled | INTEGER | 启用 |
| max_tokens / temperature | INT/REAL | 参数 |
| system_prompt | TEXT | 系统提示词 |
| created_at / updated_at | TEXT NN | 时间戳 |

#### ai_config_profiles — AI 配置多 Profile 表（新）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| profile_name | TEXT NN | 配置名称 |
| provider | TEXT NN | 提供商: openai/azure/deepseek/... |
| api_base_url / api_key | TEXT | API 配置 |
| model_name | TEXT NN | 模型名 |
| max_tokens / temperature | INT/REAL | 参数 |
| system_prompt | TEXT | 系统提示词 |
| is_active | INTEGER | 是否激活 |
| owner_user_id | INTEGER | 归属用户（迁移追加） |
| is_public | INTEGER | 是否公开（迁移追加） |
| created_at / updated_at | TEXT NN | 时间戳 |

#### ai_audit_log — AI 调用审计日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id / host_name | INT/TEXT | 关联主机 |
| profile_id / profile_name | INT/TEXT | 使用的配置 |
| model_name | TEXT | 模型名 |
| status | TEXT NN | success / error |
| prompt_tokens / completion_tokens / total_tokens | INTEGER | Token 使用量 |
| latency_ms | INTEGER | 延迟 |
| masked_mode | INTEGER | 脱敏模式 |
| prompt / response | TEXT | 输入输出（迁移追加） |
| error_message | TEXT | 错误信息 |
| ip_address | TEXT | 请求 IP |
| user_id | INTEGER | 请求用户 |
| created_at | TEXT NN | 创建时间 |

#### ai_tasks — AI 异步任务状态表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER NN | 关联主机 |
| profile_id | INTEGER | 使用的配置 |
| status | TEXT NN | pending/running/done/error |
| progress / progress_message | INT/TEXT | 进度 |
| report_id | INTEGER | 生成的报告 ID |
| error_message | TEXT | 错误 |
| masked_mode | INTEGER | 脱敏模式 |
| mode | TEXT | 模式: standard/focus（迁移追加）|
| focus_area | TEXT | 聚焦领域（迁移追加）|
| base_report_id | INTEGER | 基报告 ID（迁移追加）|
| created_at / updated_at / started_at / completed_at | TEXT | 时间戳 |

#### ai_analysis_reports — AI 分析报告表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机（级联删除）|
| case_id | INTEGER FK → cases | 关联案件（级联删除）|
| risk_assessment / threat_analysis | TEXT | 风险评估/威胁分析 |
| timeline_analysis / recommendations | TEXT | 时间线/建议 |
| raw_response | TEXT | 原始 AI 响应 |
| model_used | TEXT | 使用模型 |
| tokens_used | INTEGER | Token 用量 |
| version / profile_id | INTEGER | 版本/配置（迁移追加）|
| is_latest | INTEGER | 是否最新版（迁移追加）|
| masked_mode | INTEGER | 脱敏模式（迁移追加）|
| prompt_tokens / completion_tokens | INTEGER | Token 明细（迁移追加）|
| data_hash | TEXT | 数据哈希（迁移追加）|
| cached_at | TEXT | 缓存时间（迁移追加）|
| conversation_id | TEXT | 对话 ID（迁移追加）|
| analysis_type | TEXT | full/incremental（迁移追加）|
| module_type | TEXT | 报告模块类型（迁移追加）|
| ai_payload | TEXT（JSON） | AI 载荷（迁移追加）|
| audience | TEXT | 报告受众（迁移追加）|
| mitre_attack / attack_chain_hits | TEXT（JSON） | MITRE 覆盖（迁移追加）|
| rare_high_signals | TEXT（JSON） | 高价值信号（迁移追加）|
| source_event_id | TEXT | 源事件 ID（迁移追加）|
| created_at | TEXT NN | 创建时间 |

#### ai_prompt_versions — AI 提示词优化版本表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| profile_id | INTEGER NN | 关联配置 |
| version | INTEGER NN | 版本号（自增） |
| content | TEXT NN | 提示词内容 |
| created_at | TEXT NN | 创建时间 |

#### ai_evidence_refills — AI 只读派发回填证据表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER NN | 关联主机 |
| dispatch_task_id | INTEGER NN | 派发任务 ID |
| action_type | TEXT | 操作类型 |
| target | TEXT | 目标 |
| evidence_json | TEXT（JSON） | 证据 JSON |
| status | TEXT | completed / failed |
| created_at | TEXT | 创建时间 |

### 3.12 多智能体编排

#### agent_runs — 多智能体运行主表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| run_id | TEXT UNIQUE NN | 运行 ID |
| event_id | TEXT | 关联事件 |
| case_id | INTEGER | 关联案件 |
| title | TEXT | 运行标题 |
| stage | TEXT NN | triage/investigation/response/report |
| status | TEXT NN | pending/running/done/error |
| current_agent | TEXT | 当前执行 Agent |
| priority | TEXT | P0/P1/P2 |
| confidence | REAL | 置信度 |
| result_json | TEXT（JSON）| 结果 JSON |
| user_id | INTEGER | 请求用户 |
| created_at / updated_at | TEXT NN | 时间戳 |

索引: `idx_agent_runs_status`, `idx_agent_runs_event`

#### agent_run_steps — 单步执行审计表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| run_id | TEXT NN | 关联运行 |
| stage | TEXT | 阶段 |
| agent | TEXT | Agent 名 |
| status | TEXT | 状态 |
| input_json / output_json | TEXT（JSON） | 输入/输出 |
| confidence | REAL | 置信度 |
| evidence_json | TEXT（JSON） | 证据引用 |
| audit_log_id | INTEGER | 审计日志 ID |
| created_at | TEXT NN | 创建时间 |

索引: `idx_agent_run_steps_run`

#### hitl_approvals — 人在回路审批表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| run_id | TEXT NN | 关联运行 |
| step_id | INTEGER | 关联步骤 |
| action | TEXT NN | 审批动作 |
| target_json | TEXT（JSON） | 目标载荷 |
| requested_by | INTEGER | 请求用户 |
| status | TEXT NN | pending/approved/rejected |
| decided_by / decided_at | INT/TEXT | 决策信息 |
| auto_rollback_plan | TEXT（JSON） | 自动回滚方案 |
| reason | TEXT | 原因 |
| created_at / updated_at | TEXT NN | 时间戳 |

索引: `idx_hitl_status`

### 3.13 处置与报告

#### remediation_checklist — 处置清单表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机 |
| case_id | INTEGER | 关联案件 |
| items | TEXT（JSON） | 处置项列表 |
| created_at / updated_at | TEXT NN | 时间戳 |

#### incident_reports — 安全事件报告表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | INTEGER FK → hosts | 关联主机（SET NULL）|
| case_id | INTEGER | 关联案件 |
| title | TEXT | 报告标题 |
| content | TEXT（Markdown/HTML）| 报告内容 |
| report_type | TEXT | analysis / summary / forensics |
| audience | TEXT | leader / analyst / auditor |
| status | TEXT | draft / published / archived |
| risk_level / risk_score | TEXT/INT | 风险评级 |
| summary | TEXT | 报告摘要 |
| impact_scope | TEXT（JSON） | 影响范围 |
| timeline_json | TEXT（JSON） | 时间线 |
| mitre_cover | TEXT（JSON） | MITRE 覆盖矩阵 |
| evidence | TEXT（JSON） | 证据 |
| recommendations | TEXT（JSON） | 处置建议 |
| confidence_metadata | TEXT | 置信度元数据 |
| version | INTEGER | 版本 |
| ai_report_id | INTEGER | 关联 AI 报告 |
| mode | TEXT | auto / manual |
| report_label | TEXT | 报告标签 |
| created_by | TEXT | 创建者 |
| created_at / updated_at | TEXT NN | 时间戳 |

#### incident_report_audit — 报表审计表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| report_id | INTEGER FK → incident_reports | 关联报告（级联删除）|
| action | TEXT NN | 操作: create/update/publish/archive |
| field_name | TEXT | 变更字段 |
| old_value / new_value | TEXT | 变更前后 |
| operator | TEXT | 操作人 |
| comment | TEXT | 备注 |
| created_at | TEXT NN | 操作时间 |

### 3.14 知识管理与反馈

#### knowledge_drafts — AI 自动知识草稿表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| host_id | TEXT | 关联主机 |
| analysis_report_id | INTEGER | 关联分析报告 |
| title | TEXT NN | 知识标题 |
| description | TEXT NN | 知识描述 |
| category | TEXT | 分类: auto/ioc/pattern/... |
| severity | TEXT | 严重度 |
| mitre_attack | TEXT | MITRE ATT&CK |
| pattern | TEXT | 检测模式（YARA/Sigma） |
| status | TEXT | pending / approved / rejected |
| source | TEXT | ai_suggest / manual |
| raw_ioc | TEXT（JSON） | 原始 IOC |
| created_at / reviewed_at | TEXT | 创建/审核时间 |

#### kb_feedback — 知识库自进化反馈表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| feedback_type | TEXT NN | false_positive / true_positive / ... |
| is_false_positive | INTEGER | 是否误报 |
| rule_id / alert_id / event_id / rule_name | INT/INT/TEXT/TEXT | 关联信息 |
| host_id | INTEGER | 关联主机 |
| content | TEXT | 反馈内容 |
| source_user | TEXT | 反馈用户 |
| applied_to_kb | INTEGER | 是否已应用 |
| kb_entry_id | TEXT | 知识库条目 ID |
| suppression_id | INTEGER | 关联抑制 |
| knowledge_draft_id | INTEGER | 关联知识草稿 |
| entry_ref | TEXT | 条目引用 |
| summary | TEXT | 反馈摘要 |
| created_at | TEXT NN | 创建时间 |

### 3.15 数据治理

#### data_purge_log — 清案操作留痕表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| case_id | INTEGER NN | 关联案件 |
| case_number / case_name | TEXT | 案件信息 |
| operator_id / operator_name | INT/TEXT | 操作人 |
| purged_at | TEXT NN | 清理时间 |
| total_rows | INTEGER | 总删除行数 |
| table_counts | TEXT（JSON） | 各表删除行数 |
| snapshot_path | TEXT | 快照路径 |
| client_ip | TEXT | 客户端 IP |
| status | TEXT | done |

#### nl_query_audit — NL 查询审计表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| user_id | INTEGER | 查询用户 |
| nl_text | TEXT | 自然语言查询 |
| intent_json | TEXT（JSON） | 意图解析结果 |
| executed_sql_json | TEXT（JSON） | 执行 SQL |
| row_count | INTEGER | 返回行数 |
| masked | INTEGER | 脱敏标记 |
| status | TEXT | ok / error |
| error_message | TEXT | 错误信息 |
| created_at | TEXT NN | 查询时间 |

### 3.16 审计日志

#### audit_logs — 操作审计日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| user_id | INTEGER FK → users | 操作用户 |
| username | TEXT NN | 用户名 |
| action_type | TEXT NN | 操作类型: login/logout/create/update/delete/import |
| detail | TEXT | 操作详情 |
| target_type | TEXT | 目标类型: case/host/rule/event/... |
| target_id | TEXT | 目标 ID |
| ip_address | TEXT | 请求 IP |
| created_at | TEXT NN | 操作时间 |

索引: `idx_audit_logs_created`, `idx_audit_logs_user`, `idx_audit_logs_action`

---

## 四、表间关系

### 4.1 核心关系图

```
cases (1)
  │
  └── hosts (N) — 案件下有多个主机
        │
        ├── host_profiles (1) — 主机画像 1:1
        ├── agents (1) — Agent 注册 1:1
        │
        ├── import_records (N) — 导入记录
        │     └── import_results (N)
        │
        ├── agent_imports (N) — Agent 原始数据
        │     └── agent_imports_fts (1) — FTS5 虚拟表
        │
        ├── security_events (N) — 核心事件表
        │     ├── status_history (N)
        │     └── event_disposition_log (N)
        │
        ├── analysis_results (N) — 分析结果
        ├── abnormal_processes (N) — 异常进程
        ├── suspicious_connections (N) — 可疑连接
        ├── suspicious_startup_items (N) — 可疑启动项
        ├── persistence_items (N) — 持久化痕迹
        ├── timeline_events (N) — 时间线
        │     └── timeline_event_audit (N)
        ├── network_connections (N) — 网络连接
        ├── file_hashes (N) — 文件哈希
        ├── wmi_subscriptions (N) — WMI 订阅
        ├── registry_keys (N) — 注册表
        ├── process_events (N) — 进程事件
        ├── alerts (N) — 实时告警
        ├── webshells (N) — WebShell 检测
        ├── memory_shells (N) — 内存马检测
        ├── remediation_checklist (1) — 处置清单
        ├── ai_analysis_reports (N) — AI 报告
        └── agent_baselines (N) — 差分基线
```

### 4.2 关键外键路径

| 源表 | 目标表 | 关联方式 | 说明 |
|------|--------|---------|------|
| hosts.case_id | cases.id | FK: CASCADE | 案件-主机 一对多 |
| host_profiles.host_id | hosts.id | FK UNIQUE: CASCADE | 主机-画像 一对一 |
| agents.host_id | hosts.id | FK UNIQUE: CASCADE | 主机-Agent 一对一 |
| security_events.host_id | hosts.id | 逻辑关联（无 FK 约束） | 事件归属主机 |
| status_history.event_id | security_events.id | FK: CASCADE | 事件-状态审计 |
| event_disposition_log.event_id | security_events.id | FK | 事件-处置日志 |
| import_records.host_id | hosts.id | FK: CASCADE | 主机-导入记录 |
| import_results.import_id | import_records.id | FK: CASCADE | 导入-明细 |
| analysis_results.host_id | hosts.id | FK: CASCADE | 主机-分析结果 |
| policy_rules.policy_id | detection_policies.id | FK: CASCADE | 策略-规则 M:N |
| policy_rules.rule_id | rules.id | FK: CASCADE | 策略-规则 M:N |
| threat_intel.ioc_id | iocs.id | FK: SET NULL | IOC-威胁情报 |
| incident_reports.host_id | hosts.id | FK: SET NULL | 报告关联主机 |
| incident_report_audit.report_id | incident_reports.id | FK: CASCADE | 报告-审计 |
| agent_runs.event_id | security_events.id | 逻辑关联 | AI 运行-事件 |
| ai_analysis_reports.host_id | hosts.id | FK: CASCADE | AI 报告-主机 |
| ai_analysis_reports.case_id | cases.id | FK: CASCADE | AI 报告-案件 |
| kb_feedback.rule_id | rules.id | 逻辑关联 | 反馈-规则 |
| detection_policies.parent_id | detection_policies.id | FK self-ref | 策略层级 |
| agent_imports_fts | agent_imports | FTS5 content sync | 全文索引同步 |

### 4.3 M:N 关系

- **detection_policies** ↔ **rules**：通过 `policy_rules` 多对多关联
- **cases** ↔ **incident_reports**：案件可以有多个报告，报告关联案件
- **security_events** ↔ **incident_correlations**：事件通过 event_ids 逻辑关联到归并
- **security_events** ↔ **incident_clusters**：事件通过 member_event_ids 逻辑关联到语义簇

### 4.4 自引用关系

- **detection_policies.parent_id** → detection_policies.id：策略继承层级

---

## 五、索引策略

| 表 | 索引 | 查询场景 |
|----|------|---------|
| security_events | timestamp | 时间范围筛选 |
| security_events | host_id | 按主机筛选事件 |
| security_events | event_type | 按事件类型筛选 |
| security_events | severity | 按严重度筛选 |
| security_events | status | 按状态筛选 |
| security_events | attack_stage | 按攻击阶段筛选 |
| security_events | attack_chain_id | 攻击链查询 |
| security_events | assignee | 指派查询 |
| security_events | host_id, timestamp | 主机时间线（复合索引） |
| hosts | case_id, status | 案件下主机筛选 |
| status_history | event_id | 事件审计查询 |
| agent_imports | host_id | 主机原始数据查询 |
| agent_imports | collector_type | 采集器筛选 |
| agent_imports | import_batch_id | 按批次查询 |
| agent_imports | event_id | 事件数据源反查 |
| audit_logs | created_at | 时间排序 |
| audit_logs | user_id | 用户操作查询 |
| audit_logs | action_type | 操作类型筛选 |
| agent_runs | status | 运行状态查询 |
| agent_runs | event_id | 事件关联查询 |
| agent_run_steps | run_id | 运行步骤查询 |
| hitl_approvals | status | 审批队列查询 |
| threat_intel | ioc_id | IOC 关联查询 |
| threat_intel | ioc_value, provider | 情报查重 |
| threat_intel | provider, queried_at | 提供商查询 |
| kb_feedback | feedback_type | 反馈分类筛选 |
| kb_feedback | applied_to_kb | 未应用反馈查询 |

---

## 六、数据库特性

### 6.1 SQLite 配置

```sql
PRAGMA journal_mode=WAL;         -- 写前日志（并发读性能）
PRAGMA foreign_keys=ON;           -- 外键约束
PRAGMA busy_timeout=5000;         -- 忙等待超时
```

### 6.2 JSON 存储策略

- JSON 数组/对象统一用 **TEXT** 类型存储
- 在 Python 侧通过 `json.dumps()` / `json.loads()` 序列化/反序列化
- 使用 SQLite `json_extract()` 函数做部分查询过滤（如 `json_extract(evidence, '$.path')`）
- 不支持 JSON 索引（SQLite 限制），复杂 JSON 过滤需全表扫描

### 6.3 时间字段策略

- 所有时间字段使用 ISO 8601 文本格式（TEXT 类型）
- 优点：可读性高、Python 直接解析、排序正确
- 缺点：比 INTEGER 时间戳存储空间稍大、查询效率略低

### 6.4 FTS5 全文索引

- `agent_imports_fts`：基于 `agent_imports.raw_json` 的全文索引
- 使用 `unicode61` 分词器（支持中文）
- 通过 3 个触发器与源表保持同步（INSERT/DELETE/UPDATE）
- 用于日志检索的全文搜索功能

### 6.5 迁移策略

- 无版本化迁移工具
- 采用**条件建表 + 尝试 ADD COLUMN** 的方式在线迁移
- 迁移代码在 `database.py` 中集中管理（约从第 1381 行开始）
- 迁移追加列导致部分表字段较多（如 `ai_analysis_reports` 有 27 列）

---

## 七、数据库拓扑概览

```
┌─────────────────────────────────────────────────────────────┐
│                    用户与鉴权层                               │
│   users ← audit_logs                                         │
│   system_settings                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   案件与主机层                               │
│   cases → hosts → host_profiles                              │
│   hosts → agents, agent_baselines                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   数据导入层                                  │
│   import_records → import_results                            │
│   agent_imports ─→ agent_imports_fts (FTS5)                  │
└──────────────────────┬──────────────────────────────────────┘
                       │ 归一化
┌──────────────────────▼──────────────────────────────────────┐
│                 安全事件与分析层（核心）                      │
│                                                             │
│   security_events ──→ status_history                        │
│   security_events ──→ event_disposition_log                 │
│   security_events ──→ incident_correlations                  │
│   security_events ──→ incident_clusters                     │
│                                                             │
│   analysis_results, abnormal_processes,                      │
│   suspicious_connections, startup_items, persistence_items, │
│   timeline_events, ioc_hits, network_connections,            │
│   file_hashes, wmi_subscriptions, registry_keys,             │
│   process_events, webshells, memory_shells, alerts           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   检测规则层                                  │
│   rules → rule_audit_log, rule_history                       │
│   rules ── policy_rules ── detection_policies                │
│   rule_suppression, rule_drafts                              │
│   false_positive_patterns                                    │
│   whitelist                                                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   AI 分析层                                   │
│   ai_config_profiles → ai_prompt_versions                    │
│   ai_tasks → ai_analysis_reports → incident_reports          │
│   ai_audit_log, ai_evidence_refills                          │
│   knowledge_drafts → kb_feedback                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  智能编排层                                   │
│   agent_runs → agent_run_steps → hitl_approvals              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  输出与治理层                                 │
│   incident_reports → incident_report_audit                   │
│   remediation_checklist                                      │
│   data_purge_log, nl_query_audit, audit_logs                 │
│   normalized_logs                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 八、数据生命周期

```
Agent 采集 JSON
    │
    ▼
agent_imports ────────────────────────────── 原始数据落库
    │
    ▼ (归一化)
security_events ──── 规则匹配 ──── 安全事件
    │
    ├── 手动研判 → status_history
    ├── AI 研判 → security_events.ai_verdict
    ├── 归并 → incident_correlations / incident_clusters
    ├── 处置 → event_disposition_log
    └── 报告 → incident_reports
    │
    ▼ (处置完成)
data_purge_log ──── 案件清空 ──── 快照留痕
```

---

*文档结束。读者阅读本文档后应能完整理解 IR 平台的 48 张表的用途、字段、关系及数据流。*
