# IR Platform 进程树与异常进程检测增强方案

> 文档生成说明：基于 2026-07-12 代码走查（backend 进程检测相关源码），由主理人（齐活林/Qi）在 Agent 子代理基础设施临时不可用时，直接基于源码落地的技术交底级方案。覆盖用户指定的五大方向 + 风险评级完善 + 补充检测规则 + 实施任务分解。所有结论均引用真实文件路径与行号。

---

## 0. 文档范围与阅读指引

| 章节 | 内容 |
|---|---|
| 1 | 现状摘要（代码实证，已实现的能力 + 真实缺口） |
| 2 | 痛点与缺失环节（用户 5 大方向逐条 + 代码证据） |
| 3 | 补充检测规则候选（具体 JSON condition + severity + 误报平衡） |
| 4 | 风险评级机制完善（两套权重不一致修正 + 关键进程提权） |
| 5 | 实施任务分解（给工程师，最小改动清单） |
| 6 | 待确认问题 |

**关键结论先行**：当前进程检测"单点行为模式"已较丰富（孤儿/可疑父/非系统目录/进程链/时间聚类/短命均已有逻辑），但**缺三类能力**：① 僵尸进程（零覆盖）；② 进程名伪装 / 可疑路径 / 隐蔽进程（零覆盖）；③ 异常网络连接进程专项（仅 netcat 监听，无"脚本解释器/无签名进程外连"）。叠加**两套 severity 权重不一致 + 关键进程规则 severity 偏低**，导致"实测有风险但未被标记高风险"——这是本方案的核心修复目标。

---

## 1. 现状摘要（代码实证）

### 1.1 进程检测主链路

| 环节 | 文件:行 | 已实现 |
|---|---|---|
| 进程异常检测入口 | `backend/app/analysis/anomaly_detector.py:41` `detect_processes()` | ✅ 白名单过滤 → parent_name 反查 → 规则匹配 → 累加评分 |
| 父子关系补全 | `anomaly_detector.py:62-75` | ⚠️ 仅 `ppid → pid_to_proc` 反查补 `parent_name`，**未重建进程树/无可视化** |
| 孤儿进程判定 | `rule_engine.py` `_match_behavior` `orphan_process` | ⚠️ 仅 `ppid == 0 or None`（Windows 下几乎不命中，见 §2.1） |
| 可疑父进程 | `_match_behavior` `suspicious_parent` | ⚠️ 仅 office 父 → 脚本子（漏浏览器/PDF 父） |
| 非系统目录进程 | `unsigned_process` | ✅ 实现，但 severity=**low**（default_rules.json:297） |
| 进程链攻击路径 | `_match_process_chain` | ✅ 回溯父链 ≥min_chain_length 个可疑进程 |
| 时间聚类 | `_match_time_cluster` | ✅ 时间窗内 ≥min_count 进程启动 |
| 短命 Shell | `_match_short_lived` | ✅ powershell/cmd 存活 <max_alive_seconds |
| 累加评分 | `anomaly_detector.py:94-183` `_apply_accumulated_scoring` | ✅ 同 PID 合并命中、risk_score=min(sum,100)、severity 取最高 |

### 1.2 BEHAVIOR_PATTERNS（20 种，rule_engine.py:329-350）

`orphan_process` / `suspicious_parent` / `unsigned_process` / `network_scan` / `credential_dump` / `uac_bypass` / `token_manipulation` / `antivirus_tamper` / `defense_evasion` / `lateral_movement` / `data_exfil` / `webshell_activity` / `ransomware_behavior` / `persistence_wmi` / `persistence_com_hijack` / `discovery_recon` / `dll_sideload` / `process_chain` / `time_cluster` / `short_lived`

**缺失**（用户明确要求但无对应 pattern）：`zombie_process`（僵尸）、`process_name_spoof`（伪装）、`suspicious_path`（可疑路径）、`hidden_process`（隐蔽）、`anomalous_net_process`（异常网络进程）。

### 1.3 风险评级现状（两套权重不一致）

```python
# anomaly_detector.py:12-18 —— 用于 abnormal_processes.risk_score 累加
SEVERITY_SCORES = {"critical":40,"high":25,"medium":10,"low":5,"info":2}

# risk_assessor.py:16-31 —— 用于主机总 risk_score 与 risk_level
SEVERITY_WEIGHTS = {"critical":25,"high":15,"medium":8,"low":3,"info":0}
RISK_LEVELS = [(80,"critical"),(60,"high"),(40,"medium"),(20,"low"),(0,"info")]
```

**问题**：① 两套权重数值不一致（critical 40 vs 25，high 25 vs 15）；② RiskAssessor 中 `medium=8`，需 7.5 个 medium 进程才到 high(60)、10 个才到 critical(80)——**单条高威胁进程几乎不可能推高主机评级**；③ 进程规则的 severity 本身偏低（见 §2.5）。

### 1.4 数据模型与 DDL（技术债，非 bug）

- `abnormal_processes` 建表 DDL（`database.py:632-645`）**仅 14 列，无 `risk_score`/`matched_rules`/`attack_path`**。
- 但 `AbnormalProcess.batch_create`（`models/analysis.py:113-115`）INSERT 写入这 3 列。
- **已通过迁移补齐**：`_alter_abnormal_processes_table`（`database.py:650-668`）运行时 `ALTER TABLE ... ADD COLUMN`，`init_db` 调用（database.py:1130）。
- 结论：运行时可用（非炸裂），属"建表 DDL 与模型/迁移不同步"的轻微技术债，建议把三列补回建表 DDL 以消除歧义。

### 1.5 字段命名坑（必须对齐）

- 进程落库字段：`process_name`（模型 L120），Agent 原始字段 `name` 在 `detect_processes` L165 被映射为 `process_name`。**规则 condition 引用进程名必须用落库字段 `name`/`process_name` 视匹配上下文**：behavior 模式读 `data_item.get("name")`（`_match_behavior` 多处用 `name`），regex 模式读 `condition.field`（如 `command_line`/`path`）。
- 网络维度：`network_connections` 表用 `remote_addr`（`models/analysis.py:690`），`suspicious_connections` 用 `remote_address`（`models/analysis.py:216`）——别名不一致，跨维度关联需注意。

---

## 2. 痛点与缺失环节（用户 5 大方向）

### 2.1 进程父子关系链完整性校验

- **现状**：`detect_processes` L62-75 构建 `pid_to_proc` 并反查补 `parent_name`，构建 `process_map` 供 `process_chain` 回溯。但**只补全 parent_name 文本，不重建进程树、不做链完整性校验、无可视化输出**。
- **孤儿进程识别缺口**：`orphan_process` 逻辑（`rule_engine.py` `if pattern=="orphan_process": return ppid==0 or ppid is None`）。
  - **Windows 取证数据下几乎不命中**：Windows 进程 `ppid` 通常是 `4`（System）或真实父 PID，**pid 0 = System Idle Process，真实进程 ppid 不会是 0**。结果该规则在 Windows 场景下形同虚设，大量真孤儿（父已退出、父 PID 不在进程列表）漏检。
  - 正确做法：孤儿 = `ppid not in 进程列表 pid 集合`（父已退出/不存在），并排除 `ppid==4`（System 合法父）与 session 0 系统进程。
- **僵尸进程识别缺口**：BEHAVIOR_PATTERNS 无任何 zombie pattern，规则库无对应规则。**零覆盖**。

### 2.2 孤儿进程与僵尸进程识别策略

- 孤儿：见 §2.1，判定逻辑需从 `ppid==0` 改为"`ppid` 不在进程列表"。
- 僵尸（defunct / Z 状态 / 残留句柄）：Windows 离线取证数据通常**无 zombie 状态字段**（采集自 psutil/win32 快照，不含 Z 态）。可行推断策略（降级为"疑似"，需人工确认）：
  - 进程出现在 `processes` 列表，但其 `pid` 同时出现在 `network_connections.pid` 或 `timeline_events` 中，且进程 `start_time` 与最后一次活动的时间差极大（如 > 7 天）、`threads==0` → 疑似僵尸残留。
  - 或进程 `pid` 在 `processes` 但无任何关联 event/connection/thread → 孤立残留。
  - **诚实声明**：这是数据受限下的启发式，非确证；severity 建议 high 但标注"待人工确认"。

### 2.3 进程创建行为异常模式分析

- **已实现**：`suspicious_parent`（office 父→脚本子）、`process_chain`、`short_lived`、`time_cluster`、`unsigned_process`。
- **缺口**：
  - `suspicious_parent` 父列表硬编码为 `winword/excel/powerpnt/outlook`（`rule_engine.py`），漏 **浏览器父（chrome/edge/firefox/iexplore）→ powershell**（浏览器漏洞利用落地常见）、**PDF 阅读器父（acrord32/foxitreader）、压缩软件父（winrar/7z/bandizip）、IM 父（wechat/qq/teamviewer）**。
  - 异常启动时间：无专门规则（仅 `time_cluster` 覆盖"集中爆发"，无"非工作时间/首次登录会话外启动"）。
  - 与登录会话不符：无（无 `session`/`user` 与登录时间关联）。

### 2.4 扩充检测规则覆盖范围（用户明确要求）

| 场景 | 现状 | 缺失 |
|---|---|---|
| 隐蔽进程（双扩展名/无窗口/隐藏） | 无 | ❌ 缺 pattern + 规则 |
| 进程名伪装（相似名/大小写/unicode/双扩展名） | 无 | ❌ 缺 pattern + 规则 |
| 可疑进程路径（temp/downloads/appdata/roaming/伪装 system32/ADS） | `unsigned_process` 仅判"非系统目录" | ❌ 缺专项 path 规则（C:\Windows\Temp、AppData\Roaming、盘符仿冒、ADS 备用数据流未覆盖） |
| 异常网络连接进程（netcat/curl/wget/powershell 外连、无签名进程外连、非常用端口） | 仅 `nc_netcat_listener` 判监听 `-l -p`（severity=medium），有 `network_scan`/`data_exfil` 行为模式但无"脚本解释器/无签名进程发起外连"专项 | ❌ 缺专项 |

### 2.5 风险评级机制完善（用户重点关注：实测有风险却未标 high）

**实证：default_rules.json 中关键进程规则 severity 偏低**

| 规则 | 技术 | severity | 问题 |
|---|---|---|---|
| `powershell_encoded_command` (L86-99) | T1059/001 编码混淆 | **medium** | 混淆命令是强恶意信号，应 high |
| `powershell_bypass_execution` (L101-116) | T1059/001 绕过策略 | **medium** | 同上 |
| `certutil_download` (L118-133) | T1105 下载 | **medium** | 下载器，应 high |
| `wmic_process_create` (L186-201) | T1047 横向 | **medium** | 横向移动，应 high |
| `rundll32_suspicious` (L203-218) | T1218 | **medium** | 应 high |
| `cmd_powershell_chain` (L220-235) | T1059 | **medium** | 应 high |
| `nc_netcat_listener` (L237-252) | T1571 监听后门 | **medium** | **监听后门仅 medium，明显偏低，应 high/critical** |
| `orphan_process` (L254-268) | 孤立进程 | **medium** | Windows 下几乎不命中（§2.1） |
| `suspicious_parent_child` (L270-284) | 宏攻击 | **medium** | 合理，但父列表过窄 |
| `unsigned_process` (L286-300) | 非系统目录 | **low** | 过低；temp/appdata 下 exe 应 high |

**根因链路**（为何"实测有风险却未标 high"）：
1. 规则 severity 偏低（medium/low）→ `abnormal_processes.severity` = medium/low；
2. RiskAssessor `_calculate_category_score` 按 `SEVERITY_WEIGHTS` 累加：medium=8、low=3（risk_assessor.py:143-144）；
3. 单条 netcat 监听（medium=8）对主机 0-100 分仅贡献 8，远低于 high 阈值 60；
4. 叠加两套权重不一致（AnomalyDetector 累加用 40/25/10/5，RiskAssessor 用 25/15/8/3），主机评级被稀释。

**结论**：仅靠"堆 medium 进程数量"才能升主机评级，单条高威胁进程（监听后门、混淆 powershell、下载器）无法触发高风险告警——正是用户指出的核心问题。

---

## 3. 补充检测规则候选（具体、可入库）

> 规则入库走 `rules` 表（与 `default_rules.json`/`seed_rules.json` 同构，`RuleEngine.load_rules()` 读 DB）。**纯数据规则**（regex/composite/list）写 JSON 即可；**新行为模式**（zombie/spoof/path/hidden/net）需先在 `rule_engine.py` 加 pattern + 实现（§5 T1-T2），再写规则。

### 3.1 进程名伪装检测（process_name_spoof）— 需新 behavior pattern

**引擎实现要点**（`_match_name_spoof`）：
- 双扩展名：`name` 匹配 `(?i).*\.(exe|scr|bat|cmd|pif|com)\.(exe|scr|...)$` 或 `(?i).*\.(jpg|png|docx?|pdf)\.exe$`
- 大小写伪装：维护系统进程白名单（`svchost, lsass, services, csrss, winlogon, explorer, taskmgr, cmd, powershell, rundll32, spoolsv, msdtc, lsaiso, fontdrvhost`），进程 `name.lower()` 命中白名单但原大小写不同 → 大小写混淆（如 `Svch0st`/`PowerShell`）
- 相似名/拼写陷阱：与原名 Levenshtein 编辑距离 == 1（如 `svch0st`→`svchost`、`cxmd`→`cmd`、`taSkmgr`→`taskmgr`），用 `difflib.SequenceMatcher` 或简单 DP
- unicode 同形（`svchοst` 用 Cyrillic о）：检测非 ASCII 字符且 `unicodedata.normalize('NFKC', name)` 命中白名单

**规则**（severity=high）：

```json
{
  "name": "process_name_spoof",
  "description": "进程名伪装：双扩展名 / 大小写混淆 / 相似名 / Unicode 同形，仿冒系统进程",
  "category": "behavior",
  "rule_type": "behavior",
  "condition": { "pattern": "process_name_spoof", "description": "仿冒系统进程名" },
  "severity": "high",
  "enabled": true,
  "label": "进程名伪装（仿冒系统进程）",
  "_meta": { "mitre_attack": "T1036/005" }
}
```

### 3.2 可疑进程路径检测（suspicious_path）— 需新 behavior pattern

**引擎实现要点**（`_match_suspicious_path`）：`path_lower` 匹配以下且不在白名单（Program Files/Windows\system32/Windows\SysWOW64）：
- 用户可写/临时目录：`temp|tmp|downloads|appdata\\roaming|appdata\\local|programdata|desktop|public`
- 伪装 system32：含 `system32` 但前缀非 `c:\windows\system32\`（如 `c:\windows\system32.exe\`、盘符仿冒 `d:\windows\system32\`）
- ADS 备用数据流 / UNC：含 `:` 后跟 `$`（如 `file.txt:stream`）或 `\\` 开头异常 UNC
- 用户目录下的 exe：`users\\*\\` 且非 `appdata\local\programs`

**规则**（severity=high）：

```json
{
  "name": "suspicious_process_path",
  "description": "进程路径位于临时/下载/AppData/ProgramData 或伪装系统目录/ADS 备用数据流",
  "category": "behavior",
  "rule_type": "behavior",
  "condition": { "pattern": "suspicious_path", "description": "可疑进程路径" },
  "severity": "high",
  "enabled": true,
  "label": "可疑进程路径",
  "_meta": { "mitre_attack": "T1036/004" }
}
```

### 3.3 隐蔽进程检测（hidden_process）— 需新 behavior pattern

**引擎实现要点**（`_match_hidden_process`）：
- 双扩展名已并入 spoof（§3.1），此处聚焦：进程名与已知服务名相同但 path 不在 system32（仿冒服务进程，如 `svchost.exe` 在 `C:\Temp\`）；
- 无窗口/隐藏：若数据含 `window_title==""` 且 `session>0` 且为交互式进程（powershell/cmd/rundll32）→ 疑似隐藏；
- 进程在 `image_file_execution_options` 映射（IFEO 劫持，已有 behavior `image_file_execution_hijack` 覆盖）

**规则**（severity=high）：

```json
{
  "name": "hidden_or_spoofed_service_process",
  "description": "进程名与系统服务同名但路径不在 system32，疑似仿冒服务进程",
  "category": "behavior",
  "rule_type": "behavior",
  "condition": { "pattern": "hidden_process", "description": "隐蔽/仿冒服务进程" },
  "severity": "high",
  "enabled": true,
  "label": "隐蔽/仿冒服务进程",
  "_meta": { "mitre_attack": "T1564/001" }
}
```

### 3.4 异常网络连接进程检测（anomalous_net_process）— 需新 behavior pattern（跨维度）

**引擎实现要点**（`_match_anomalous_net_process`，需 `global_context` 含 `connections`）：
- 从 `global_context["connections"]`（或 `network_connections` 表）取该 pid 的外连；
- 触发条件（任一）：
  - 进程名 ∈ {powershell, cmd, wscript, cscript, certutil, bitsadmin, mshta, rundll32, wmic, nc, netcat, curl, wget, python, perl, ruby} 且 `remote_port` 不在业务白名单（80/443/53/22/3389/445/8080…）；
  - 进程 `unsigned_process`（非系统目录）且有外连；
  - `remote_port` ∈ {4444,8443,1337,31337,6667,9999,1080,5900} 常见 C2/代理端口

**规则**（severity=high）：

```json
{
  "name": "anomalous_network_process",
  "description": "脚本解释器/无签名进程发起异常外连或连接常见 C2 端口",
  "category": "behavior",
  "rule_type": "behavior",
  "condition": { "pattern": "anomalous_net_process", "description": "异常网络连接进程" },
  "severity": "high",
  "enabled": true,
  "label": "异常网络连接进程",
  "_meta": { "mitre_attack": "T1071" }
}
```

> ⚠️ 前置改动：`detect_processes` 的 `global_context`（`anomaly_detector.py:79-82`）当前仅含 `process_map`/`all_items`，需补 `connections`（从 `raw_data.network.connections` 或 analysis_service 传入的 `network_connections` 表）供 `_match_anomalous_net_process` 使用。

### 3.5 僵尸进程检测（zombie_process）— 需新 behavior pattern（推断，P2）

**引擎实现要点**（`_match_zombie`，数据受限启发式）：
- 进程 `pid` 出现在 `network_connections.pid` 或 `timeline_events`；
- 且 `start_time` 与最后一次关联活动时间差 > 阈值（如 7 天）且 `threads==0` 或 `connection_count>0` 但进程自身无其他活动；
- 或进程 `pid` 在 `processes` 列表但全库无任何 event/connection/thread 关联 → 孤立残留
- **标注**：命中仅作"疑似"，severity=high 但 reason 明示"待人工确认"

**规则**：

```json
{
  "name": "zombie_process_suspect",
  "description": "疑似僵尸/残留进程（数据受限启发式，需人工确认）",
  "category": "behavior",
  "rule_type": "behavior",
  "condition": { "pattern": "zombie_process", "description": "疑似僵尸进程" },
  "severity": "high",
  "enabled": true,
  "label": "疑似僵尸/残留进程（待确认）",
  "_meta": { "mitre_attack": "T1059" }
}
```

### 3.6 孤儿进程判定修正（orphan_process 规则增强）

**引擎实现修正**（`_match_behavior` 的 `orphan_process` 分支）：
```python
elif pattern == "orphan_process":
    ppid = data_item.get("ppid", 0)
    process_map = (global_context or {}).get("process_map", {})
    # 父不存在（已退出/伪造）→ 真孤儿；排除 System(4) 与 session0 系统进程
    if ppid is None or ppid == 0:
        return ppid is not None and ppid != 4  # Windows: ppid=0 不视为孤儿
    return ppid not in process_map and ppid != 4
```
**规则 severity 提升**：`orphan_process` 由 medium → **high**（真孤儿在应急中是强信号）。

### 3.7 suspicious_parent 扩展（纯数据/小代码）

- 扩展 `_match_behavior` 的 `suspicious_parents`/`suspicious_children` 硬编码列表（rule_engine.py）：
  - 父扩展：`winword/excel/powerpnt/outlook` + `chrome/edge/firefox/iexplore`（浏览器）+ `acrord32/foxitreader`（PDF）+ `winrar/7z/bandizip`（压缩）+ `wechat/qq/teamviewer`（IM）
  - 子保持：`powershell/cmd/wscript/cscript`
- 或改为 condition 驱动（更符合"规则引擎"设计）：`suspicious_parent` pattern 支持 `condition.parents`/`condition.children` 列表，规则 JSON 配置。建议走后者（更灵活），属 T6 小代码改动。

### 3.8 提升现有关键进程规则 severity（纯数据改动）

| 规则 | 原 severity | 建议 | 依据 |
|---|---|---|---|
| `powershell_encoded_command` | medium | **high** | 编码混淆强信号 |
| `powershell_bypass_execution` | medium | **high** | 绕过执行策略 |
| `certutil_download` | medium | **high** | T1105 下载器 |
| `wmic_process_create` | medium | **high** | T1047 横向移动 |
| `rundll32_suspicious` | medium | **high** | T1218 |
| `cmd_powershell_chain` | medium | **high** | T1059 脚本链 |
| `nc_netcat_listener` | medium | **critical** | 监听后门，实测高风险 |
| `unsigned_process` | low | **medium**（temp/appdata 下 exe 经 suspicious_path 已 high，此处提 medium 减少误报） | 非系统目录合法程序多 |

---

## 4. 风险评级机制完善

### 4.1 统一两套权重

将 `AnomalyDetector.SEVERITY_SCORES` 与 `RiskAssessor.SEVERITY_WEIGHTS` 对齐为同一套，建议：

```python
# 统一权重（两处共用，建议抽到 config 或常量模块）
SEVERITY_SCORES = {"critical":35,"high":20,"medium":10,"low":5,"info":1}
```

效果：单条 high 进程贡献 20，3 条 high → 60 = 主机 high；单条 critical（如 netcat 监听后门）→ 35，2 条 critical → 70 = high。使"单条高威胁进程"能实质影响主机评级。

### 4.2 提升关键进程规则 severity（见 §3.8）

规则 severity 直接决定 `abnormal_processes.severity`，从而决定 RiskAssessor 累加权重。提升 §3.8 列表的 severity 后，主机评级对"混淆 powershell / 下载器 / 监听后门"更敏感。

### 4.3 可选：critical 进程直推主机评级

对确认类强信号（confirmed C2 外连、confirmed 仿冒系统进程）可设"单条即拉主机至 high 及以上"的快速通道（兜底，避免数量稀释）。建议作为 P1 增强，非必需。

### 4.4 abnormal_processes 行 severity 与主机评级联动验证

- `detect_processes` 累加后 `abnormal_processes[].severity` = 命中规则最高 severity（anomaly_detector.py:172）；
- `RiskAssessor.assess` 读 `findings["abnormal_processes"]` 按 `SEVERITY_WEIGHTS` 累加（risk_assessor.py:62-67）；
- 提升规则 severity + 统一权重后，联动自动生效，无需改 RiskAssessor 主流程（仅改权重常量 + 规则 severity）。

---

## 5. 实施任务分解（给工程师，最小改动）

| 任务 | 改动文件 | 内容 | 依赖 |
|---|---|---|---|
| T1 | `backend/app/rules/rule_engine.py` | `BEHAVIOR_PATTERNS` 加 `zombie_process`/`process_name_spoof`/`suspicious_path`/`hidden_process`/`anomalous_net_process` | — |
| T2 | `rule_engine.py` `_match_behavior` | 加 5 个 pattern 分支 + 对应 `_match_*` 实现（含 global_context 传 connections）；修正 `orphan_process` 判定；`suspicious_parent` 列表/condition 扩展 | T1 |
| T3 | `anomaly_detector.py:79-82` | `global_context` 补 `connections`（供 anomalous_net_process） | T2 |
| T4 | `risk_assessor.py:16-22` + `anomaly_detector.py:12-18` | 统一 SEVERITY 权重常量 | — |
| T5 | `default_rules.json` + `docs/seed_rules_process.json`（新） | 入库补充规则（§3.1-3.5 的 5 条新 behavior 规则）+ 提升 §3.8 现有规则 severity | T1-T2 |
| T6 | `rule_engine.py` `suspicious_parent` | 扩展父/子列表或 condition 驱动 | T2 |
| T7 | `database.py:632-645` | 建表 DDL 补 `risk_score`/`matched_rules`/`attack_path`（消除与迁移不同步的技术债） | — |
| T8 | `backend/tests/test_process_detection.py`（新） | 单元测试：5 个新 pattern 命中、orphan 修正（Windows ppid=4 不误报）、suspicious_parent 扩展、severity 提升后 RiskAssessor 累加、全局回归 | T1-T7 |

**契约保护**：新增 behavior pattern 不影响既有规则；`rule_{i}_{name}` RAG 索引契约不变（规则仍只进 `rules` 表，不进向量库，见前文知识库相关结论）；`abnormal_processes` 字段不变（仅 DDL 补列与现状对齐）。

---

## 6. 待确认问题（交架构师/客户）

1. **僵尸进程推断可靠性**：Windows 离线取证无 zombie 态字段，§3.5 为启发式。是否接受"疑似+待人工确认"标签？还是本轮不做僵尸（P2）？
2. **anomalous_net_process 数据源**：用 `raw_data.network.connections`（Agent 原始）还是 analysis_service 已落库的 `network_connections` 表？影响 global_context 构造（T3）。
3. **suspicious_parent 扩展方式**：硬编码列表扩展（快）vs condition 驱动（灵活，需改 `_match_behavior`）？建议 condition 驱动。
4. **权重统一数值**：§4.1 建议值（critical35/high20/medium10/low5）是否可接受？需避免把正常多进程主机误判 high。
5. **隐蔽进程无窗口判定**：当前数据是否含 `window_title`/`session` 字段？若无，`hidden_process` 退化为例 3.3 的"仿冒服务进程"判定（P1）。
6. **误报容忍度**：temp/appdata 下合法安装程序（如 Teams/Chrome 更新）可能触发 `suspicious_path` high，是否需加安装目录白名单？建议加 `programdata\*.install` 等白名单。
7. **本轮范围**：进程树"可视化"（前端进程链视图）是否本轮做？本方案聚焦检测规则 + 评级，可视化建议单列 P2。

---

## 附录 A：补充规则覆盖度矩阵

| 用户要求场景 | 现状 | 本方案补充 | 实现类型 |
|---|---|---|---|
| 进程父子链完整性 | 仅 parent_name 文本补全 | 维持 + orphan 修正（父不存在判定） | 修 pattern |
| 孤儿进程 | ppid==0（Windows 不命中） | ppid 不在进程列表 + 排除 System(4) | 修 pattern |
| 僵尸进程 | 无 | zombie_process 启发式（P2） | 新 pattern + 规则 |
| 进程创建异常 | suspicious_parent/process_chain/time_cluster/short_lived | suspicious_parent 扩展父列表 | 扩 pattern |
| 隐蔽进程 | 无 | hidden_process（仿冒服务进程/双扩展名） | 新 pattern + 规则 |
| 进程名伪装 | 无 | process_name_spoof（双扩展名/大小写/unicode/相似名） | 新 pattern + 规则 |
| 可疑路径 | unsigned_process（仅非系统目录） | suspicious_path（temp/appdata/伪装system32/ADS） | 新 pattern + 规则 |
| 异常网络进程 | nc_netcat_listener（仅监听） | anomalous_net_process（脚本解释器/无签名外连/C2端口） | 新 pattern + 规则 |
| 风险评级 | 两套权重不一致 + 关键规则 severity 低 | 统一权重 + 提升 §3.8 规则 severity | 改常量 + 改规则 |

## 附录 B：误报/漏报平衡要点

- **suspicious_path**：加白名单（Program Files / Windows\system32 / SysWOW64 / programdata\*.install），避免合法更新程序误报。
- **process_name_spoof**：双扩展名 + 大小写/相似名 + unicode 三重判定，任一命中即报；相似名用编辑距离==1，避免正常短名误报（阈值严格）。
- **anomalous_net_process**：业务端口白名单（80/443/53/22/3389/445/8080/8443 业务）降低误报；仅"脚本解释器/无签名进程"触发，合法浏览器外连不报。
- **zombie_process**：标注"疑似+待确认"，不自动高危处置，防误杀。
- **orphan_process 修正**：排除 ppid==4（System）与 session 0 系统进程，避免海量误报。
