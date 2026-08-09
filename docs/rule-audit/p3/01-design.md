# P3 设计文档 — 检测点增强与 exists 扩展

> 阶段：P3（#106）｜ 环节：设计（01-design）
> 配套文档：02-dev.md（开发）· 03-test.md（测试）· 04-verify.md（验证）
> 基准：`backend/app/rules/*` · `backend/app/rules/rule_engine.py` · 真实库 `data/ir_platform.db`

本阶段交付 2 个子项：**P3-1 新增检测点（Top 20 缺口填补）**、**P3-2 `exists` 类持久化兜底扩展**。
设计严格遵循一条铁律：**不引入"死规则"**——任何 active 规则必须对应后端已有采集器/事件字段（避免重蹈 P0-3 `service_image_path`/`scheduled_task_xml` 覆辙）。

---

## 0. 可行性校正（代码实证）

依据 `optimized-feasibility-v2.md` P3 章节 + 真实代码核查：

| P3 检测点（原清单） | 后端采集器/字段现状 | 本阶段决策 |
|---|---|---|
| 暴力破解 4625 / DCSync 4662 / Kerberoasting 4769 / PtH 4624 / 特权 4672 / 显式凭据 4648 | **已落地**（P0-2 `event_log_rules.json` 6 条） | ✅ 已交付，本文档列为"前置已覆盖"，不重复 |
| 实时 TI | `iocs` 表动态 IOC 引用（P0-1 已就绪） | ✅ 已具备，跨引用 |
| 勒索批量加密 | `ransomware_behavior_pattern`（behavior，已存在） | ✅ 已存在 |
| 卷影副本删除 | `command_line` 正则（进程事件已有） | 🆕 新增（composite） |
| RMM 工具滥用 | `name` 列表（进程事件已有） | 🆕 新增（list） |
| LOLBin 下载（certutil/bitsadmin/curl） | `command_line` 正则 | 🆕 新增（regex） |
| PowerShell 混淆执行 | `command_line` 正则 | 🆕 新增（regex） |
| 本地账户创建 / 日志清除 / NTDS 窃取 | `command_line` 正则 | 🆕 新增（regex） |
| 计划任务/注册表 Run/WMI 持久化 | `command_line` 正则 | 🆕 新增（regex/composite） |
| 数据外发云存储 | `remote_address`/`domain` 列表（网络事件已有） | 🆕 新增（list/composite） |
| WebShell 落地 | `file_create` 事件 `path`（已有类型映射） | 🆕 新增（composite） |
| 可疑服务创建 | `command_line` 正则 | 🆕 新增（regex） |
| **C2 JA3·信标·DGA** | 无 JA3/流量元数据采集器 | ⏸️ 不实现（会成死规则），`dns_c2_beaconing` 维持 disabled 标注 |
| **Sysmon·ETW** | 无 Sysmon/ETW 采集器 | ⏸️ 不实现 |
| **黄金票据** | 需 4769 + 加密类型明细，summary 无 etype | ⏸️ 不实现（无法判定） |
| **MFA 疲劳·不可能旅行** | 无身份/SSO 采集器 | ⏸️ 不实现 |
| **Linux systemd·cron·SSH** | 采集器为 Windows 导向 | ⏸️ 不实现 |
| **容器·K8s 逃逸 / 云身份·Exchange·OAuth** | 无对应采集器 | ⏸️ 不实现 |
| **钓鱼 URL·附件 / 蜜罐诱饵** | 无邮件/诱饵采集器 | ⏸️ 不实现 |
| **P3-2 `exists` 持久化兜底**（wmi_subscribe/scheduled_task/service/registry） | canonical 模型有字段映射，但**后端零采集器产出**（P0-3 已确认） | 🆕 新增但 `enabled:false` + `_meta.pending_collector` 标注（待采集接线后激活） |

> **核心原则**：标 ⏸️ 的项若强行落规则，其检测字段永不被任何采集器填充 → `_match_exists`/`regex` 永不命中 → 等同 P0-3 死规则，运维会误判"已覆盖"。故一律**不写 active 规则**，仅在设计/验证文档中登记为"已识别缺口 + 阻塞依赖"，待采集器补齐后由 P3-2 同款模板激活。

---

## 1. P3-1 新增检测点（`advanced_detections.json`）

### 1.1 文件与装载
新增 `backend/app/rules/advanced_detections.json`（顶层数组）。`loader.load_default_rules()` 已 glob `app/rules/*.json` 全部数组文件 → 自动装载，无需改 loader。

### 1.2 规则清单（全部 active，字段均来自现有 canonical 事件）

> 字段取值约束：进程类用 `command_line`/`name`；网络类用 `remote_address`/`domain`；文件类用 `path`/`name`；均隶属 `canonical_adapter.EVENT_TYPE_CATEGORY_MAP` 已映射的事件类型，保证 matcher 能消费。

| # | 规则名 | 类型 | 关键条件 | 严重度 | MITRE |
|---|---|---|---|---|---|
| 1 | `adv_shadow_copy_delete` | composite(AND) | `command_line` ~ `(vssadmin.*delete.*shadows\|wbadmin.*delete.*catalog\|wmic.*shadowcopy.*delete)` | high | T1490 |
| 2 | `adv_rmm_tool_abuse` | list | `name` ∈ {anydesk,teamviewer,tacticalrmm,meshagent,screenconnect,hiren*} | high | T1219 |
| 3 | `adv_lolbin_certutil_download` | regex | `command_line` ~ `certutil.*(-urlcache\|-f).*http` | medium | T1105 |
| 4 | `adv_lolbin_bitsadmin_transfer` | regex | `command_line` ~ `bitsadmin.*/transfer` | medium | T1105 |
| 5 | `adv_powershell_obfuscated` | regex | `command_line` ~ `(powershell\|pwsh).*(-enc\|-encodedcommand\|-w\s*hidden\|-nop)` | high | T1059.001 |
| 6 | `adv_local_account_create` | regex | `command_line` ~ `net\s+user\s+(\S+)\s+/add` | high | T1136.001 |
| 7 | `adv_eventlog_clear` | regex | `command_line` ~ `(wevtutil.*\bcl\b\|Clear-EventLog\|powershell.*Clear-EventLog)` | high | T1070.001 |
| 8 | `adv_ntds_dit_access` | regex | `command_line` ~ `(ntds\.dit\|vssadmin.*create.*shadow.*copy.*ntds)` | critical | T1003.003 |
| 9 | `adv_schtasks_persistence` | regex | `command_line` ~ `schtasks.*/create.*/sc` | medium | T1053.005 |
| 10 | `adv_registry_run_persistence` | regex | `command_line` ~ `(reg\s+add.*\\Software\\Microsoft\\Windows\\CurrentVersion\\Run|Set-ItemProperty.*-Path.*'HKLM.*Run')` | high | T1547.001 |
| 11 | `adv_wmi_persistence` | regex | `command_line` ~ `(wmic.*/(?:namespace\|subscription)\|Register-WmiEvent\|__EventFilter)` | high | T1546.003 |
| 12 | `adv_cloud_exfil_domain` | list | `domain` ∈ {drive.google.com,dropbox.com,mega.nz,1fichier.com,box.com} | medium | T1567.002 |
| 13 | `adv_reverse_shell_listen` | composite(AND) | `event_type` exists 网络监听 + `command_line` ~ `(nc\s+-[el]|-lvp\|ncat\|powershell.*System.Net.Sockets)` | high | T1571/T1572 |
| 14 | `adv_lolbin_script_host` | regex | `command_line` ~ `(mshta.*http\|regsvr32.*/i:?http\|rundll32.*http)` | medium | T1218 |
| 15 | `adv_suspicious_service_create` | regex | `command_line` ~ `(sc\s+create\|New-Service\s+-Name)` | high | T1543.003 |
| 16 | `adv_webshell_drop` | composite(AND) | `file_create` 事件 + `path` ~ `(wwwroot\|webapps\|htdocs).*\.(aspx?\|php\|jsp)` | high | T1505.003 |

> 注：`#1/#13/#16` 为 composite（多子条件 AND），其余为单 condition（regex/list）。所有 `regex` pattern 经 `re` 编译校验（开发阶段用脚本预检），避免非法正则导致装载失败。

### 1.3 严重度约束（AC-P3-8）
新增 16 条 active 中需控制 high/critical 占比，避免破坏 AC-P1-13（≤55%）。

**实测校准（开发阶段）**：初版 16 条 active 为 high 10 / medium 5 / critical 1，装载后整体 high 占比 **55.8%**（163 条中 high 91），略超 55%。为闭合 AC-P1-13，将两条"双用途、合法运维亦可能触发"的规则由 high 降为 medium：
- `adv_rmm_tool_abuse`（RMM 工具进程存在）—— 工具本身非恶意；
- `adv_suspicious_service_create`（`sc create` / `New-Service`）—— 正常部署亦常见。

降权后 active = **high 8 / medium 7 / critical 1**，整体 high 占比 **54.6%（89/163）≤ 55% ✅**，AC-P1-13 不回归。

**P3-1 规则正则校准（开发阶段发现）**：`adv_powershell_obfuscated` 原 pattern 含 `-nop`，会匹配 `-NoProfile`（`-N-o-P-…`）前缀造成误报。已移除 `-nop`，保留强混淆指标 `-enc`/`-encodedcommand`/`-w hidden`/`-windowstyle hidden`。该修正同时保证负向用例（`powershell -NoProfile -Command Get-Date`）不命中。

---

## 2. P3-2 `exists` 持久化兜底扩展

### 2.1 动机
`rule_engine._match_exists` 已支持（line 1422），canonical 模型已声明 `wmi_subscribe`/`scheduled_task`/`service_operation`/`registry_modify` 事件类型。但**后端零采集器产出这些字段**（P0-3 确认）。故本阶段交付"规则模板"，待采集器接线即激活。

### 2.2 实现（`advanced_detections.json` 内 `enabled:false` 段）

| 规则名 | 类型 | condition.field | pending_collector |
|---|---|---|---|
| `pki_wmi_subscription_exists` | exists | `wmi_subscription_name` | `wmi_subscribe` |
| `pki_scheduled_task_exists` | exists | `scheduled_task_name` | `scheduled_task` |
| `pki_service_image_path_exists` | exists | `service_image_path` | `service_operation` |
| `pki_registry_run_exists` | exists | `registry_key_path` | `registry_modify` |

每条 `_meta`：
```json
{"pending_collector": "wmi_subscribe", "mitre_attack": "T1546.003",
 "note": "后端暂未产出该字段，置 disabled；采集器接线后改 enabled=true 即生效"}
```
> 这 4 条**不参与 active 命中统计**，但作为"已设计、待激活"的持久化兜底留存，杜绝未来采集器上线后漏检。符合 P0-3 选项 (b) 的"标注待采集"政策，且与 `dns_c2_beaconing`/`domain_fronting_detection` 的 disabled 先例一致。

### 2.3 P3-2 不做的事（明确边界）
- **不**将这 4 条置 `enabled:true`（会制造死规则）。
- **不**新增采集器（超出本阶段范围；采集器补齐属 P0-3a，前序未做）。
- 文档登记缺口，待采集器就绪后由运维改 `enabled=true` 激活。

---

## 3. 验证策略（见 03-test / 04-verify）

- **装载验证**：`load_default_rules()` 总数 = 143 + 16(active) + 4(disabled) = 163；无非法 `rule_type`。
- **命中验证**：抽 `adv_eventlog_clear` / `adv_local_account_create`（regex）与 `adv_shadow_copy_delete`（composite）用 `MatcherRegistry.dispatch` 直接命中（构造样本事件 item）。
- **event_log_summary 回归**：已落地 6 条仍可被 `evaluate_summary` 命中（不破坏 P0-2）。
- **死规则校验**：active 规则逐条映射到 canonical 字段；exists 兜底 4 条 `enabled:false` 且带 `pending_collector`。
- **占比校验**：整体 high 占比 ≤55%（AC-P1-13 不回归）。
- **定向回归**：规则相关 10 文件 `--noconftest` 复跑，零回归。

---

## 4. 验收标准（AC）

| AC | 描述 |
|---|---|
| AC-P3-1 | `advanced_detections.json` 存在且被 loader 装载（总数 +20） |
| AC-P3-2 | 新增 16 条 active 检测点，全部使用合法 `rule_type` |
| AC-P3-3 | 每条 active 规则字段对应现有 canonical 事件模型（无缺失采集器依赖） |
| AC-P3-4 | 抽样 active 规则（`adv_eventlog_clear`/`adv_local_account_create`/`adv_shadow_copy_delete`）可被 matcher 真实命中 |
| AC-P3-5 | 无新增死规则：active 规则均有可行采集器；不存在 JA3/ETW/K8s/MFA/Exchange 等无采集器 active 规则 |
| AC-P3-6 | P3-2 的 4 条 `exists` 持久化兜底规则定义完整，`enabled:false` + `_meta.pending_collector` 标注 |
| AC-P3-7 | `load_default_rules()` 无非法类型、无装载异常 |
| AC-P3-8 | 整体 high 占比仍 ≤55%（AC-P1-13 不回归） |
| AC-P3-9 | P3 四篇文档（01-04）齐备、可追溯 |
