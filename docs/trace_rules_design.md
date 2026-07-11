# 应急溯源规则设计 + 落库与实现方案（IR Platform · 需求 #2）

> **视角**：架构师（高见远）｜**输入**：`docs/trace_rules_analysis.md`（PM 许清楚，需求 #1）
> **依据代码**（已实读）：
> - `backend/app/rules/rule_engine.py`（`evaluate` / `_match_attack_chain` / `_build_host_events` / `_match_attack_chain_step` / `_summarize_event` / `_C2_FRAMEWORK_SIGNATURES` / `FIELD_TO_IOC_TYPE`）
> - `backend/app/schemas/analysis.py`（`RULE_TYPE_ENUM` / `ConditionModel` / `validate_condition`）
> - `backend/app/models/rule.py`（`Rule.create/list_enabled`）
> - `backend/app/services/analysis_service.py`（第 8.5 节 attack_chain 评估 + `details.attack_chains`）
> - `backend/app/services/ai_task_service.py`（`get_attack_chain_hits` → `normalize_and_guard(attack_chain_hits=...)` → `AiAnalysisReport.attack_chain_hits`）
> - `backend/app/services/knowledge_retriever.py`（`_load_rules` 读 `default_rules.json` / `_build_index` 幂等 / `rule_{i}_{name}` 同序契约）
> - `backend/app/services/explainability_service.py`（`build_evidence_trace`）
> - `backend/app/database.py`（`_import_default_rules` / `reset_default_rules` / `rules` 表 DDL）
> - `backend/app/rules/default_rules.json`（102 条现状规则，0 条 `attack_chain`）

---

## 0. 关键结论（落地前的"真相"）

读完真实代码后，第一个重大发现是：**`attack_chain` 引擎与全链路联动已经完整实现并接线，缺口仅仅是 `rules` 表里一条 `attack_chain` 规则都没有。**

| 环节 | 现状（实读代码确认） | 结论 |
|---|---|---|
| `attack_chain` 引擎 | `rule_engine.py:_match_attack_chain` 已实现主机级贪心顺序匹配 + 时间窗；`evaluate()` 末尾已按 `rule_type=="attack_chain"` 分桶并下钻 `_build_host_events` | **引擎就绪，0 改动** |
| 分析流水线接线 | `analysis_service.py:144-149` 已 `RuleEngine.evaluate([], attack_chain_rules, global_context={"host_id": host_id})`；命中写入 `details.attack_chains` | **接线就绪，0 改动** |
| AI / 可解释性联动 | `ai_task_service.py:238` `get_attack_chain_hits(host_id)` → `normalize_and_guard(attack_chain_hits=...)` → `AiAnalysisReport.attack_chain_hits` + AI 叙述上下文 | **联动就绪，0 改动** |
| 落库形态 | `Rule.create` 将 `condition` 整个 `json.dumps` 进 `rules.condition` 列；`RULE_TYPE_ENUM` 已含 `attack_chain`；`validate_condition` 已校验 `ordered_steps`/`window_minutes` | **无需改表结构** |
| RAG `rule_{i}_{name}` 契约 | `knowledge_retriever._load_rules()` 读的是**静态文件** `default_rules.json`（进程级缓存），与 DB `rules` 表完全无关；`_build_index` 幂等（`count()>0` 直接跳过） | **只要不动 `default_rules.json`，契约 100% 不受影响** |

> **一句话**：本轮工作的 90% 是"把规则作为数据写进 `rules` 表"，不是写引擎代码。需要新写代码的只有 **1 处最小集成**（`TI_malware_hash` 的文件哈希匹配，见 §3.3）。

---

## 1. 8 项待确认问题决策

| # | 待确认问题（来自 PM 分析 §4） | 决策 | 理由 |
|---|---|---|---|
| 1 | 规则落库形态：`rules` 表 vs seed/RAG | **统一写入 `rules` 表**（生成 `rule_*`，由 `RuleEngine` 实时匹配） | 与现有「规则引擎 → `details.attack_chains` → `get_attack_chain_hits` → AI」证据链路一致；`attack_chain` 配置直接存于 `condition` JSON 列，零表结构变更。C2 IP/域名/哈希**情报**走既有的 `iocs` 表（动态引用，`FIELD_TO_IOC_TYPE` 自动并入 `list` 规则），不进 `rules` 也不进 `seed`。 |
| 2 | （PM 原文 §4-第 2 项）是否需新增匹配维度/采集 | **本轮只交付纯引擎内可实现的规则**；标注【需新增采集】的规则（`EXF_usb`=USB 介质、`TI_c2_ja3`=JA3、`TI_dns_tunnel_vol`=DNS 查询计数）列为 **P2/未来项**，不本轮建设采集。文件哈希：`analysis_service` 已落 `FileHash` 表，仅差"把 `FileHash` 作为 `data_items` 送入 `RuleEngine.evaluate`"的最小集成（见 §3.3），不算新增采集维度。 | 避免范围蔓延与破坏现有契约；新增采集需改 Agent，超出本轮。 |
| 3 | 跨主机关联是否本轮做 | **本轮不做**，保持单主机溯源链；列为 **P2 未来项**（`host_scope` 已预留 `single`，未来扩展 `cluster` 才需新增 case 级关联模型）。 | 现状 `_build_host_events` 严格按 `host_id`；跨主机需新增数据模型与关联算法，投入大、风险高，非本需求核心增量。 |
| 4 | 规则触发时机：实时 vs 离线重算 | **分析时实时匹配**（沿用现有 retrieve/engine 流程），**不新增离线管线**。 | 现有 `analysis_service.run_analysis` 已实时执行；历史报告重算可由用户重跑分析触发，无需新增离线 job。 |
| 5 | RAG 种子 Bug | **已修，划掉**。该 Bug（`knowledge_retriever._build_seed_index` 早退、reject/recall 未触发重建）已在早前迭代（knowledge index + auth 修复）解决，种子知识已正常向量化。本设计不针对此点做任何改动，且新规则也不进 `default_rules.json`（进一步规避任何索引一致性风险）。 | 团队-lead 已确认过时结论。 |
| 6 | 误报治理与证据强度 | 规则加**置信阈值/证据强度**机制：① 普通规则用 `composite(AND)` 复合条件 + 上下文限定（Web 进程上下文、动态 IOC 名单）降 FP；② 链规则命中强制 `severity=critical`（引擎内定）；③ 白名单 `whitelist_service` 已对进程类规则生效，新进程类规则自动受益；④ 情报升级沿用 `threat_intel` 回灌（`_record_ti_hit` → `severity` 升 `high` + 标记）。 | 复用既有机制，零新增基础设施。 |
| 7 | AI 与链规则联动 | 链规则命中后**作为高权重确定性证据**进入 explainability：命中写入 `details.attack_chains` → `get_attack_chain_hits` → `normalize_and_guard` 注入 AI 报告 `attack_chain_hits` 字段 + AI 叙述上下文。AI 仍"只叙述、不重判"。**可选增强**：在 `build_evidence_trace` 中把 `attack_chains` 也并入 `local_evidence`（本设计标记为可选 T5 增强，非必须）。 | 现有链路已打通，无需改 `rule_engine`；仅确认数据流。 |
| 8 | MITRE 映射扩展 | 沿用现有 `MitreTacticMapper`（逐事件映射），**不改动**。新增规则通过 `condition._meta.mitre_attack`（或顶层 `mitre_attack`）携带 T 码（如 `T1190`/`T1021`/`T1071`/`T1041`），泳道图按 `mitre_attack` 归位即可；引擎对 `mitre_attack` 为自由字符串，无枚举约束，无需扩枚举。 | 零改动；仅数据层赋值。 |

> 说明：团队-lead 已直接给出 1–7 的决策口径（落库表 / 不做跨主机 / 实时 / Bug 划掉 / 证据强度 / AI 联动 / MITRE），其中第 2 项（是否新增匹配维度/采集）即 PM 原文未获团队-lead 复述的"其余 1 项"，由本设计补全决策（见上表 #2）。

---

## 2. 具体规则设计

### 2.0 设计约束（必须遵守，来自真实代码）

**维度可用字段**（`_build_host_events` 把各表 `dict(r)` 作为统一事件 `data`，`attack_chain` 步骤 `match` 命中的是这些字段，不是原始采集字段）：

| dimension | 事件来源表 | `data` 可用关键字段 |
|---|---|---|
| `process` | `AbnormalProcess` | `process_name`, `command_line`, `process_path`, `parent_pid`, `parent_name`, `pid` ⚠️**无 `name` 字段** |
| `connection` | `SuspiciousConnection` | `remote_address`, `remote_port`, `protocol`, `local_address`, `process_name`, `pid` |
| `persistence` | `PersistenceItem` | `type`, `name`, `command`, `location`, `user`, `is_suspicious` |
| `ioc` | `IocHit` | `ioc_type`, `ioc_value`, `matched_in`, `context` |
| `registry` | `RegistryKey` | `key_path`, `value_name`, `value_data`, `last_write_time` |
| `timeline` | `TimelineEvent` | `event_type`, `timestamp`, `source`, `description`, `severity` |

> ⚠️ **关键坑**：`process` 维 `data` 里进程名是 `process_name` 而**非** `name`。因此 `attack_chain` 步骤若用 `behavior` 类型（如 `webshell_activity` 读 `name`），在 `process` 维度会**失效**。本设计步骤一律用 `regex`/`list`/`composite`/`threshold`/`exists`（读 `command_line`/`process_name`/`remote_address` 等真实字段），仅在单事件 `behavior` 逻辑只依赖 `command_line` 时（如 `discovery_recon`/`credential_dump` 的命令行分支）才谨慎使用 `behavior`。

**时间窗说明**：`process/connection/persistence/ioc` 维度在 `_build_host_events` 中**时间戳为 None**（仅顺序、无时序），只有 `registry`/`timeline` 有真实时间戳。因此链规则的"时间窗"实际只约束含 `registry`/`timeline` 步骤的跨度；纯 `process→connection` 链的时间窗判定会被跳过（仅顺序）。故 `window_minutes` 对纯进程/连接链主要起"语义文档化"作用，跨 host 真实时序还原需待采集补全时间戳（见 P2）。本设计对纯进程/连接链设较大 `window_minutes`（如 1440）以兼容排序退化。

---

### 2.1 四条 `attack_chain` 链规则（本需求最大增量价值）

> 优先级：前 3 条为 PM 标注 P0，第 4 条 `AC_persist_to_beacon` PM 标 P1，但团队-lead 要求"重点设计 4 条"，故 4 条全部完整设计并纳入本轮种子。

#### 规则 1：`AC_webshell_to_c2`（Web→C2，P0）

- **攻击场景**：公网 Web 服务被入侵，Web 进程上下文出现 WebShell 特征命令 → 派生命令执行 → 外连已知 C2。
- **触发条件（ConditionModel / `attack_chain`）**：
  ```json
  {
    "rule_type": "attack_chain",
    "category": "web",
    "severity": "critical",
    "condition": {
      "window_minutes": 1440,
      "host_scope": "single",
      "ordered_steps": [
        { "dimension": "process",
          "match": { "type": "composite", "logic": "AND", "sub_rules": [
            {"type":"regex","field":"process_name","pattern":"(w3wp|httpd|apache|nginx|php|php-cgi|tomcat|java)","flags":"ignorecase"},
            {"type":"regex","field":"command_line","pattern":"(eval\\(|system\\(|passthru|shell_exec|base64_decode|assert\\(|preg_replace|cmd\\.exe|powershell\\.exe|whoami|ipconfig)","flags":"ignorecase"}
          ]}},
        { "dimension": "process",
          "match": {"type":"regex","field":"command_line","pattern":"(powershell|certutil|curl|wget|bitsadmin|cmd\\.exe|/bin/sh|bash)","flags":"ignorecase"}},
        { "dimension": "connection",
          "match": {"type":"list","field":"remote_address","values":[],"match_mode":"exact"} }
      ]
    }
  }
  ```
  > 第 3 步 `remote_address` 的 `values:[]` + `FIELD_TO_IOC_TYPE["remote_address"]="ip"` → 运行时并入 `iocs` 表 `ip` 类指标（既有的 `known_bad_ip_1/2/3` + 运营补充的 C2 IP）。`match_mode:"exact"` 命中即链闭合。
- **匹配逻辑（对接现有引擎）**：`evaluate` 分桶后调用 `_match_attack_chain` → `_build_host_events` 聚合本机 process/connection 事件 → 按 `ordered_steps` 贪心顺序（step1 必须在 step2 前、step2 在 step3 前）命中 → 因无时间戳，仅顺序判定 → 命中强制 `severity=critical`，`reason` 含三步摘要。
- **预期输出**：溯源结论 =「Web 服务进程 `<process_name>` 执行 WebShell 特征命令 → 派生 `<child>` 命令执行 → 外连已知 C2 `<remote_address>`」；生成 `details.attack_chains` 条目（`rule_name=AC_webshell_to_c2`、`severity=critical`、`steps=[...]`）；经 `get_attack_chain_hits` 进入 AI 报告成为高权重证据。
- **误报/漏报平衡**：step1 用 `composite(AND)` 限定"Web 进程上下文 + WebShell 指示词"双命中，避免普通 Web 日志误报；step3 用 C2 情报名单（动态 IOC）而非任意外连，强降 FP；`window_minutes=1440` 放宽时序退化。漏报面：若 WebShell 落盘文件未产生 `AbnormalProcess`（如仅在 web 日志中），step1 可能缺失 → 由 `WEB_upload_exec` 单点规则 + 未来文件采集补充。

#### 规则 2：`AC_lateral_to_cred`（横向→凭据，P0）

- **攻击场景**：攻击者用显式凭据/远程登录 → 远程执行工具（Impacket/PsExec/WMI）→ 远程进程/服务创建 → 凭据窃取（LSASS dump）。
- **触发条件（ConditionModel / `attack_chain`）**：
  ```json
  {
    "rule_type": "attack_chain", "category": "lateral", "severity": "critical",
    "condition": {
      "window_minutes": 240, "host_scope": "single",
      "ordered_steps": [
        {"dimension":"process","match":{"type":"regex","field":"command_line","pattern":"(net use \\\\\\|wmic /node:|/user:|runas |psexec|winrm|invoke-command|enter-pssession|new-pssession|schtasks /run /s)","flags":"ignorecase"}},
        {"dimension":"process","match":{"type":"regex","field":"command_line","pattern":"(psexec|wmiexec|smbexec|atexec|schtasks /create /s|sc \\\\\\\\\\w+ create|wmic process call create|winrs -r:)","flags":"ignorecase"}},
        {"dimension":"process","match":{"type":"regex","field":"command_line","pattern":"(lsass|mimikatz|procdump|sekurlsa|comsvcs\\.dll|rundll32|reg save.*(sam|system)|ntds\\.dit|secretsdump)","flags":"ignorecase"}}
      ]
    }
  }
  ```
  > 三步全 `process` 维度（`command_line` 真实存在）。允许 Impacket/PsExec/WMI 任一即 step2 命中（OR 已内联进单个正则的 `|`），防漏报；step3 凭据窃取用命令行关键词（不依赖 `name`，规避 process 维度无 `name` 的坑）。
- **匹配逻辑**：同 `_match_attack_chain` 顺序贪心；240 分钟内三阶顺序命中即链成。
- **预期输出**：「`<host>` 上显式凭据/远程登录 → 远程执行 `<tool>` → 凭据窃取 `<tool2>` 命中 LSASS」溯源链 + `details.attack_chains` 条目。
- **误报/漏报平衡**：三步 AND 顺序，且 step1 限定横向动作关键字；白名单 `whitelist_service` 可排除合法运维的 `psexec`（如 SCCM 推送）。漏报：跨主机横向（A→B）不在本轮（见决策 #3）。

#### 规则 3：`AC_collect_to_exfil`（收集→渗出，P0）

- **攻击场景**：侦察（whoami/netstat/ipconfig/systeminfo）→ 数据暂存压缩 → 外连上传/回传 C2。
- **触发条件（ConditionModel / `attack_chain`）**：
  ```json
  {
    "rule_type": "attack_chain", "category": "exfiltration", "severity": "critical",
    "condition": {
      "window_minutes": 1440, "host_scope": "single",
      "ordered_steps": [
        {"dimension":"process","match":{"type":"behavior","pattern":"discovery_recon"}},
        {"dimension":"process","match":{"type":"regex","field":"command_line","pattern":"(7z|winrar|rar\\.exe|makecab|tar|gzip|zip|compress-archive)","flags":"ignorecase"}},
        {"dimension":"connection","match":{"type":"list","field":"remote_address","values":[],"match_mode":"exact"}}
      ]
    }
  }
  ```
  > step1 用 `behavior:discovery_recon`（仅依赖 `command_line` 计数 ≥3 侦察命令，**在 process 维度有效**）；step3 同 `AC_webshell_to_c2` 复用 C2 情报名单。
- **匹配逻辑**：顺序贪心；侦察 → 压缩 → C2 外连三阶成链（强制 critical）。
- **预期输出**：「侦察 `<cmds>` → 压缩暂存 → 外传 C2 `<ip>`」溯源链 + `attack_chains` 条目。
- **误报/漏报平衡**：侦察必须 ≥3 侦察命令（behavior 内置阈值）降 FP；压缩 + C2 外连双命中强约束；漏报：若渗出走云盘/邮件（非 IP C2），step3 不命中 → 由 `EXF_cloud_drive`/`EXF_email` 单点补。

#### 规则 4：`AC_persist_to_beacon`（持久化→beacon，P1，本轮一并设计落地）

- **攻击场景**：安装计划任务/服务持久化 → 窗口内 beacon 外连已知 C2。
- **触发条件（ConditionModel / `attack_chain`）**：
  ```json
  {
    "rule_type": "attack_chain", "category": "persistence", "severity": "critical",
    "condition": {
      "window_minutes": 1440, "host_scope": "single",
      "ordered_steps": [
        {"dimension":"persistence","match":{"type":"composite","logic":"OR","sub_rules":[
          {"type":"regex","field":"type","pattern":"(scheduled_task|service|startup|wmi|registry_run)","flags":"ignorecase"},
          {"type":"regex","field":"command","pattern":"(schtasks|sc create|New-Service|regsvr32|wmic /namespace)","flags":"ignorecase"}
        ]}},
        {"dimension":"connection","match":{"type":"list","field":"remote_address","values":[],"match_mode":"exact"}}
      ]
    }
  }
  ```
  > step1 用 `persistence` 维度 `type`/`command` 真实字段；step2 复用 C2 名单。
- **匹配逻辑**：持久化痕迹 → C2 beacon 顺序成链。
- **预期输出**：「安装 `<persist_type>` 持久化 → 周期 beacon 外连 C2 `<ip>`」溯源链。
- **误报/漏报平衡**：持久化 + C2 双命中；`window_minutes=1440` 适配长周期 beacon；漏报：beacon 走域名 C2 需 `iocs` 域名类命中（已支持 `domain`/`host`/`url` 映射），运营补充域名情报即可覆盖。

---

### 2.2 数据外泄补全（4 类各 ≥1 条，P0）

| 规则名 | 类型 | 触发条件（ConditionModel） | 匹配逻辑 | 预期输出 / 证据 | FP/FN 平衡 |
|---|---|---|---|---|---|
| `EXF_cloud_drive` | `composite`(AND) | sub_rules: ① `regex` `command_line` `(rclone|megacmd|megacli|mega-|onedrive|onedrivecmd|baidunetdisk|百度网盘|"drive.google.com"\|"mega.nz")`；② `regex` `command_line` `(upload|sync|copyto|move|--upload)` | 单 `AbnormalProcess` 事件内双重命中云盘工具 + 上传动词 | "检测到 `<tool>` 向外部云存储 `<target>` 上传" + `AbnormalProcess` 证据 | 白名单排除正常备份软件（如企业 `rclone` 备份账号进程名）；动词 AND 防偶发 |
| `EXF_encrypted_archive` | `composite`(AND) | ① `regex` `command_line` `(7z\|winrar\|rar\.exe\|makecab\|tar\|gzip\|zip\|gpg\|openssl enc)`；② `regex` `command_line` `(-p\s+\S+|-crypt|-e\s|enc -aes|--passphrase|password)` | 单事件内"压缩/加密工具 + 加密参数"双命中（加密包创建） | "检测到加密压缩包创建 `<cmd>`（疑似规避检测的外传载荷）" | **三重降 FP**：压缩工具 + 加密参数 AND；外连上传环节由 `AC_collect_to_exfil` 链规则覆盖，避免单规则误报正常压缩 |
| `EXF_email` | `regex` | `command_line` `(swaks|blat\.exe|sendemail|sendmail|mutt\s|mailx|"curl.*smtp"|"openssl s_client -connect.*:25"|imap_upload|"thunderbird.*-compose")` | 邮件客户端/脚本外发特征 | "检测到邮件外发工具 `<tool>` 发送（疑似邮件信道外泄）" | 白名单排除正常邮件网关（exchange/smtp 中继进程）；限定发送类动词 |
| `EXF_c2_staging` | `composite`(AND) | ① `list` `field=remote_address` `values=[]`（C2 情报名单，动态 IOC）；② `threshold` 或 `regex` 外传体积（`FIELD_TO_IOC_TYPE` 已映射） | 命中已知 C2 IP/域名 + 大体积外传 | "暂存数据回传已知 C2 `<ip>`" | 用 C2 名单限定的 OR（仅命中情报名单才报），避免把正常业务大包误报 |

> USB 外传（`EXF_usb`）标注【需新增采集】，列 **P2 未来项**（需 Agent 采集可移动介质事件维度），本轮不交付。

---

### 2.3 横向移动 / Web 入侵 / 初始访问 / 威胁情报（P0 单点规则）

| 规则名 | 类型 | 触发条件（ConditionModel） | 优先级 | 说明 / FP-FN |
|---|---|---|---|---|
| `LAT_impacket` | `regex` | `command_line` `(psexec\.py\|wmiexec\.py\|smbexec\.py\|atexec\.py\|secretsdump\.py\|impacket\.|dcomexec\.py\|mmcexec\.py)` `flags=ignorecase` | P0 | 覆盖 Impacket 脚本版横向（与既有 `psexec_lateral_movement` 互补）；命令行关键字精确匹配，FP 低 |
| `WEB_upload_exec` | `composite`(AND) | ① `regex` `command_line` `(\.php\|\.aspx\|\.jsp\|\.jspx\|\.war)`；② `regex` `process_name` `(php\|php-cgi\|w3wp\|tomcat\|httpd\|nginx\|java)` `flags=ignorecase` | P0 | Web 运行时执行脚本文件 = WebShell 被执行；写盘+执行的时间链由 `AC_webshell_to_c2` 补全 |
| `IA_edge_exploit` | `regex` | `command_line` `(\$\{jndi:|\${(.*)}|\$\{\s*jndi|proxylogon|proxyshell|"class\.module\.classLoader"|spring4shell|log4j|"jndi:ldap"|"jndi:rmi"|cve-2021-44228|cve-2022-1388|cve-2022-22965)` `flags=ignorecase` | P0 | 公网漏洞利用指纹；维护为可更新列表（指纹串集中在一处便于运营）；FP 低。**限制**：依赖 web 请求落入 `command_line`（若仅在 HTTP 访问日志则需未来日志采集） |
| `TI_malware_hash` | `list` | `field=file_hash`, `values=[]`, `match_mode=exact` | P0 | `FIELD_TO_IOC_TYPE["file_hash"]="hash"` → 并入 `iocs` 表 `hash` 类情报；**需 §3.3 最小集成**（当前 `FileHash` 未送入 `RuleEngine.evaluate`） |

---

### 2.4 P1 / P2 规则要点（本轮设计规格，落地优先级见 §4）

**P1（要点，工程师可直接按规格实现）**
- `AC_persist_to_beacon`：见 §2.1 规则 4（已完整设计，本轮一并种子）。
- `EXF_c2_staging`：见 §2.2。
- `EXF_usb`：【需新增采集】可移动介质拷贝 volume 阈值，P2。
- `LAT_remote_service`：`composite`(AND) `regex command_line "(sc \\\\\\\\w+ create|sc \\\\\\\\w+ start)"` + 远程 UNC 主机名。
- `LAT_dcom`：`regex command_line "(MMC20\.Application|ShellWindows|__NCService|GetObject.*\"winmgmts:\")"`。
- `WEB_sqli_rce`：`composite`(AND) 限定 Web 进程父上下文 + ≥2 指示词（`union select`/`sql syntax error` + `cmd`/`powershell`）。
- `WEB_reverse_shell`：`regex command_line "(bash -i >& /dev/tcp/|nc -e /bin/sh|python -c 'import socket.*reverse|/dev/tcp/\d+/\d+)"` + Web 进程上下文。
- `IA_brute_force`：`threshold` 登录失败计数（`4625`/`4648` 事件频次）+ 时间窗；白名单排除已知扫描器 IP。
- `CRED_browser_vault`：`composite`(AND) 进程名 ≠ 浏览器 + 访问浏览器配置路径（`Login Data`/`Cookies`/`key4.db`）。
- `PER_linux_persist`：`regex command_line "(/etc/systemd/system/.*\.service|/etc/rc\.local|/etc/ld\.so\.preload|crontab -e|@reboot)"`。
- `TL_off_hours`：【需时间解析支持】事件时间戳 `0–5 点`/周末 + `threshold` 进程/外连突增。

**P2（方向，多需新增采集/离线基线，本轮不交付）**
- `PRIV_token_manip_chain`：`behavior:token_manipulation` + 高权子进程上下文。
- `PER_bits_job` / `PER_office_template`：BITS/COM 模板劫持，regex 特征。
- `TL_dormant_burst`：【需基线/跨分析】离线对比历史首现时间。
- `TI_c2_ja3` / `TI_dns_tunnel_vol`：【需网络采集新增 JA3 / DNS 查询计数字段】。
- `LAT_pass_the_ticket`：Kerberos PtT 复用检测（复用 `kerberoasting`/`dcsync` 同族）。

---

## 3. 落库与实现方案

### 3.1 落库形态（无表结构变更）

- **存储位置**：`rules` 表。`attack_chain` 与普通规则**共用同一张表、同一 `condition` JSON 列**，仅靠 `rule_type` 字段区分。
- **字段对齐**（`Rule.create` 签名）：`name`(唯一键，被引擎/测试引用)、`category`、`rule_type`、`condition`(dict→JSON)、`severity`、`enabled`、`label`(中文展示)、`source`(本批用 `'default'`，见下)、`mitre_attack`。
- **`attack_chain` 配置存哪**：`ordered_steps` / `window_minutes` / `host_scope` 全部写在 `condition` JSON 内（`validate_condition` 已支持）。**不需要新增 `chain_config` 列**。
- **`source` 取值决策**：本批新规则 `source='default'`（视作平台内置默认规则）。由于**不修改 `default_rules.json`**，未来执行 `reset_default_rules()` 时 `_import_default_rules` 只 upsert `default_rules.json` 中的规则、保留 DB 中既有 `source='default'` 但不在 json 里的行（不删除）→ **新规则在重置后依然存活**。同时 `Rule.delete` 仅允许删 `source='user'`，本批规则受保护。
- **`mitre_attack`**：链规则在 `condition._meta.mitre_attack` 写 T 码（如 `T1190`/`T1021`/`T1071`/`T1041`），`Rule._normalize_mitre` / `_import_default_rules` 会自动提取到顶层 `mitre_attack` 列供泳道图使用。

### 3.2 可执行种子数据（交付物）

- **`docs/seed_rules.json`**：11 条本轮规则的结构化定义（4 条 `attack_chain` + 7 条单点 `EXF_cloud_drive`/`EXF_encrypted_archive`/`EXF_email`/`LAT_impacket`/`WEB_upload_exec`/`IA_edge_exploit`/`TI_malware_hash`），字段对齐 `Rule` 模型与 `ConditionModel`，已通过 `validate_condition` 语义校验（设计期自检）。
- **`docs/seed_rules.py`**：幂等插入脚本（见 §3.4），读取 `seed_rules.json`，跳过已存在的 `name`，调用 `Rule.create`；可直接由工程师运行。
- **SQL INSERT 参考**（节选，完整见脚本生成）：
  ```sql
  INSERT INTO rules (name, description, category, rule_type, condition, severity, enabled, label, source, mitre_attack)
  VALUES ('AC_webshell_to_c2', 'Web 入侵→WebShell→C2 链', 'web', 'attack_chain',
          '{"window_minutes":1440,"host_scope":"single","ordered_steps":[...]}',
          'critical', 1, 'Web 入侵到 C2 攻击链', 'default', 'T1190/T1071');
  -- 其余 10 条同理；condition 为完整 JSON 字符串。
  ```

### 3.3 唯一需要的代码改动点（最小集成）

**仅 `TI_malware_hash` 需要 1 处小集成**：当前 `FileHash` 数据落库（analysis_service step 8）后**没有作为 `data_items` 送入 `RuleEngine.evaluate`**，导致 `file_hash` 类 `list` 规则永不执行。

最小改动（`analysis_service.py`，在 `FileHash.batch_create` 之后、`# 8.5` 之前追加）：
```python
# 文件哈希情报匹配（TI_malware_hash：list 规则 field=file_hash，动态并入 iocs.hash）
from app.models.analysis import FileHash
hash_rules = [r for r in rules
              if r.get("rule_type") == "list"
              and (r.get("condition") or {}).get("field") == "file_hash"]
if hash_rules:
    fh_rows = FileHash.list_by_host(host_id) or []
    fh_items = [{"file_hash": (r.get("sha256") or r.get("hash") or ""),
                 "pid": r.get("pid"), "process_name": r.get("process_name")}
                for r in fh_rows if (r.get("sha256") or r.get("hash"))]
    if fh_items:
        hash_matches = RuleEngine.evaluate(fh_items, hash_rules,
                                            global_context={"host_id": host_id})
        # 复用 ioc_hits 落库通道（ioc_type 归一为 hash），供前端与 explainability 消费
        IocHit.batch_create(host_id, [{
            "ioc_type": "hash",
            "ioc_value": m["item"].get("file_hash"),
            "matched_in": m["rule_name"],
            "context": m["reason"],
            "severity": m["severity"],
        } for m in hash_matches])
```
> 该改动**不触碰 `rule_engine`/`knowledge_retriever`/表结构**，仅把既有采集接入既有引擎，符合"最小改动"原则。其余 10 条规则为纯 `condition` 数据，零代码改动。

**`attack_chain` 规则是否需要改 `rule_engine`？—— 不需要。** `_match_attack_chain` 已从 `rule.get("condition")` 读取 `ordered_steps`/`window_minutes`，且 `analysis_service` 已在 `# 8.5` 按 `host_id` 下钻评估。新增链规则只要 `condition` 合法即自动被加载执行。

### 3.4 契约保护声明（entry_ref=`rule_{i}_{name}`）

- `knowledge_retriever._load_rules()` 读取的是**静态 `default_rules.json`**（进程级缓存），与 DB `rules` 表完全解耦。
- `_build_index` 幂等：首次 `collection.count()>0` 即跳过重建。
- `retrieve` 的 `rule_{i}_{name}` 与 `_build_index` 均遍历同一个 `_load_rules()` 列表 → 二者 `i` 始终同序。
- **本设计不修改 `default_rules.json`**（新规则只进 DB），因此 chroma 索引与 `rule_{i}_{name}` 顺序**完全不变，契约 100% 不受影响**。✅

### 3.5 `seed_rules.py` 关键逻辑（伪码，工程师照此实现）

```python
import json, sqlite3
from app.database import get_connection
from app.rules.rule_engine import RuleEngine  # 复用（其 import 链含 models.rule）
# 或直接 from app.models.rule import Rule
def seed(path="docs/seed_rules.json"):
    rules = json.load(open(path, encoding="utf-8"))
    created = skipped = 0
    for r in rules:
        existing = Rule.get_by_id_or_name(r["name"])  # 幂等：存在则跳过
        if existing:
            skipped += 1; continue
        Rule.create(name=r["name"], category=r["category"], rule_type=r["rule_type"],
                    condition=r["condition"], severity=r["severity"],
                    description=r.get("description"), enabled=r.get("enabled", True),
                    label=r.get("label"), source=r.get("source", "default"))
        created += 1
    print(f"created={created} skipped={skipped}")
```
> 幂等要点：`name` 是唯一技术键；重复运行安全。`validate_condition(rule_type, condition)` 建议在 `Rule.create` 前调用一次（API 层已校验，脚本侧再加一道更稳）。

---

## 4. 任务分解（有序，供工程师寇豆码 + QA 严过关）

| 任务 | 名称 | 源文件 | 依赖 | 优先级 | 说明 |
|---|---|---|---|---|---|
| **T1** | 种子规则数据 + 幂等插入脚本 | `docs/seed_rules.json`、`docs/seed_rules.py` | — | P0 | 产出 11 条规则结构化定义与插入脚本；设计期已按 `validate_condition` 自检 `attack_chain` 结构合法 |
| **T2** | `TI_malware_hash` 文件哈希匹配集成 | `backend/app/services/analysis_service.py`（step 8 后追加）、`backend/app/models/analysis.py`(FileHash) | — | P0 | §3.3 最小改动：把 `FileHash` 接入 `RuleEngine.evaluate`；其余 10 条零代码 |
| **T3** | 落库与引擎联调（attack_chain 端到端） | `rules` 表（DB）、`rule_engine.py`（仅验证）、`analysis_service.py` | T1,T2 | P0 | 运行 `seed_rules.py` → 确认 `RuleEngine.load_rules()` 能加载 11 条 → 跑一次真实/样例分析确认 4 条链规则在 `details.attack_chains` 产出；验证 `entry_ref=rule_{i}_{name}` 契约未被破坏（`default_rules.json` 未改） |
| **T4** | AI / 可解释性联动验证 | `ai_task_service.py`、`explainability_service.py`、前端 `AttackChainDag.vue` | T3 | P0 | 确认 `get_attack_chain_hits` → `normalize_and_guard` → `AiAnalysisReport.attack_chain_hits` 全链路；前端 DAG 有数据；可选：在 `build_evidence_trace` 把 `attack_chains` 并入 `local_evidence`（增强） |
| **T5** | 测试钩子 + QA（严过关） | `test_rules_qa.py`（既有回归）、新增 `tests/test_trace_rules.py` | T3,T4 | P0/P1 | ① 单测：每条规则用合成 `host_events` 跑 `_match_attack_chain`/`match_rule` 验证命中与 FP（白名单/上下文）；② 回归：确保 102 条既有规则 + 11 条新规则总数与匹配数无退化；③ 契约测试：`rule_{i}_{name}` 索引顺序与 `default_rules.json` 完全一致；④ `TI_malware_hash` 集成测试（造 `FileHash` + `iocs` hash 命中） |

> 依赖说明：T1（数据）与 T2（唯一代码改动）相互独立，可并行；T3 依赖两者完成落库；T4 依赖 T3 有链命中；T5 依赖 T3/T4。无过长线性链。

---

## 5. 类图（规则/引擎/落库/证据关系）

见 `docs/trace_rules_class.mermaid`。

## 6. 时序图（attack_chain 规则从落库到 AI 证据的端到端）

见 `docs/trace_rules_sequence.mermaid`。

---

## 7. 风险与未决项

1. **进程/连接维度无真实时间戳**：`attack_chain` 链的时间窗对纯 `process→connection` 链实际只做顺序判定（`_build_host_events` 注释确认）。跨维真实时序还原需待 Agent 补全时间戳采集（P2）。
2. **`EXF_usb` / `TI_c2_ja3` / `TI_dns_tunnel_vol` 依赖新采集**：本轮不交付，列为 P2；不影响 P0 链规则与外泄 4 类（云盘/邮件/加密压缩/C2 回传）。
3. **WebShell 落盘检测靠 `AbnormalProcess`**：若攻击者仅写文件不触发进程异常，链路 step1 可能缺失；由 `WEB_upload_exec` 单点 + 未来文件采集补充。
4. **`TI_malware_hash` 依赖 `iocs` 表 hash 情报运营**：`values:[]` 设计意味"靠动态 IOC 命中"，需运营在 `iocs` 表维护恶意哈希清单（或脚本预置几条示例，同 `_import_default_iocs` 风格）。
