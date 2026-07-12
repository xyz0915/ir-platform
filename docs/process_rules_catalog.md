# 进程检测规则目录（规则管理视角）

> 聚焦「规则管理模块」本身，按规则文件里的 `category` 大类、`severity`、`enabled`、评分权重
> 维度归类，把**针对进程**或**匹配进程字段（pid/ppid/name/cmdline/state/threads/子进程关系…）**
> 的检测规则逐条列出。所有结论均来自当前代码事实，标注 `file:line` / JSON 行号。
>
> 基线：`backend/app/rules/default_rules.json`（102 条）、`default_attack_chain.json`、`rule_engine.py`、
> `anomaly_detector.py`、`models/rule.py`、`api/rules.py`。

---

## 0. 范围与口径说明（重要）

**主目录口径**：本目录的「进程规则」= 被进程检测管线实际评估的规则集合，即
`AnomalyDetector.detect_processes` 选取的 `category ∈ {process, behavior, execution}`
（`backend/app/analysis/anomaly_detector.py:78`）。这 29 条规则是规则管理中**以进程为检测主体**
的全部规则，且**全部 `enabled=true`**。

**边界处理**（满足「匹配进程字段」口径，但避免冲淡聚焦目录）：
- 其它 category（credential / defense_evasion / lateral / …）中同样匹配 `command_line`
  （进程命令行字段）的规则，列入 **附录 B**，按原 category 归类，供「全部找出来」核对。
- `docs/seed_rules_process.json` 中的 5 条进程专属种子规则**未接入线上规则集**（不位于
  `backend/app/rules/` 目录，不被 `load_default_rules()` 加载），列入 **附录 A** 并明确标注。

> 结论先行：规则管理对进程检测**实际生效**的规则共 **29 条**（process=10 / behavior=8 /
> execution=11）；若把「匹配进程命令行字段」的跨维度规则也计入，则全库共 **64 条**匹配
> 进程 `command_line`（详见附录 B 的 35 条 + 主目录 29 条）。

---

## 1. 规则管理运行机制

### 1.1 规则来源与加载链路
1. **聚合读取**：`loader.load_default_rules()`（`backend/app/rules/loader.py:25`）glob
   `backend/app/rules/*.json`，逐条 schema 校验，返回合法规则列表。
2. **初始化入库**：`database.py:544` 在初始化时调用 `load_default_rules()`，按 `name` upsert
   `source='default'` 的行（校验失败仅告警跳过，不阻断整库）。
3. **运行时读取**：`RuleEngine.load_rules()`（`backend/app/rules/rule_engine.py:295`）从 DB 读
   `Rule.list_enabled()`（仅启用规则）。
4. **管线筛选**：进程检测入口 `AnomalyDetector.detect_processes`
   （`anomaly_detector.py:41`）先 `whitelist_service.filter_whitelisted(processes)` 剔除白名单，
   再筛选 `category ∈ {process, behavior, execution}` 的规则交给 `RuleEngine.evaluate`。

### 1.2 默认启用与开关
- 每条规则 JSON 自带 `enabled` 字段，默认 `true`；DB `Rule.enabled` 默认 `True`。
- **主目录 29 条全部 `enabled=true`**。全库中唯一 `enabled=false` 的是 `network` 类的
  `dns_c2_beaconing` 与 `domain_fronting_detection`（不在进程集内）。
- 规则管理 API（`backend/app/api/rules.py`）：`list_rules`（按 category/enabled/搜索过滤）、
  `create_rule`（`source='user'`）、`bulk_enable_rules`、`reset_default_rules`（重置回默认）、
  `update_rule`（可改 `enabled`/`severity`/`condition`，写审计）、`delete_rule`。
- 模型字段（`backend/app/models/rule.py:12`）：`category / rule_type / severity(默认 medium) /
  enabled(默认 True) / source(默认 user) / condition / label`。

### 1.3 评分如何累加（两级）
- **进程级（同一 PID 内）**：`anomaly_detector.py:12` `SEVERITY_SCORES =
  {critical:35, high:20, medium:10, low:5, info:1}`；`_apply_accumulated_scoring`
  （`anomaly_detector.py:104`）对同 PID 命中累加 `risk_score = min(Σ, 100)`，取最高 `severity`。
- **主机级**：`RiskAssessor.assess`（`backend/app/analysis/risk_assessor.py`）按类别累加各维度
  命中（`SEVERITY_WEIGHTS` 同上），`min(Σ, 100)` 后映射等级
  （`risk_assessor.py:25`）：`≥80 critical / ≥60 high / ≥40 medium / ≥20 low / 其余 info`。
- ⚠️ 不一致：进程级 `anomaly_detector.py:110` docstring 写 `critical=40/high=25`，与常量 `35/20`
  不符，以常量为准（详见全景文档 §5.3）。

### 1.4 进程相关的开关 / 配置项
- **白名单**：`WhitelistService.filter_whitelisted` 在进程检测入口前置剔除（`anomaly_detector.py:57`），
  可能漏掉「白名单进程派生的恶意子进程链」。
- **阈值参数（写在规则 `condition` 内，可经 `update_rule` API 调整）**：
  - `high_connection_count`：`connection_count > 50`（default_rules.json:606）
  - `time_cluster_burst`：`window_minutes=5, min_count=5`（default_rules.json:1762-1763）
  - `short_lived_shell`：`max_alive_seconds=30`，目标进程 powershell/cmd/wscript/cscript
    （default_rules.json:1778-1785）
  - `process_chain_attack`：`min_chain_length=3`（default_rules.json:1729）
  - `zombie_process_suspect`（种子，未接入）：`threshold_days=7`（docs/seed_rules_process.json:73）

---

## 2. 主目录（按 category 分大组）

> 表格字段：`name`（规则 ID）/ `label`（展示名）/ `severity` / 触发条件·匹配逻辑 / 文件位置。

### 2.1 category = process（10 条，全部 regex 匹配 `command_line`）

| name | label | severity | 触发条件 · 匹配逻辑 | 文件位置 |
| --- | --- | --- | --- | --- |
| `powershell_encoded_command` | PowerShell 编码命令执行 | high | `command_line` 正则 `powershell.*(-enc\|-encodedcommand)\s+` | default_rules.json:84-98 |
| `powershell_bypass_execution` | PowerShell 绕过执行策略 | high | `command_line` 正则 `powershell.*-ExecutionPolicy.*(Bypass\|Unrestricted)` | default_rules.json:101-115 |
| `certutil_download` | Certutil 下载文件 | high | `command_line` 正则 `certutil.*-urlcache.*-split` | default_rules.json:118-132 |
| `bitsadmin_download` | Bitsadmin 下载文件 | medium | `command_line` 正则 `bitsadmin.*/transfer` | default_rules.json:135-149 |
| `suspicious_mshta` | Mshta 执行远程脚本 | medium | `command_line` 正则 `mshta.*(http\|https\|javascript\|vbscript)` | default_rules.json:152-166 |
| `regsvr32_squiblydoo` | Regsvr32 Squiblydoo 远程脚本 | medium | `command_line` 正则 `regsvr32.*/s.*/u.*(http\|https\|scrobi)` | default_rules.json:169-183 |
| `wmic_process_create` | WMIC 远程进程创建 | high | `command_line` 正则 `wmic.*process.*call.*create` | default_rules.json:186-200 |
| `rundll32_suspicious` | Rundll32 加载可疑模块 | high | `command_line` 正则 `rundll32.*(shell32\|javascript\|http)` | default_rules.json:203-217 |
| `cmd_powershell_chain` | CMD 启动 PowerShell 链 | high | `command_line` 正则 `cmd.*/c.*powershell` | default_rules.json:220-234 |
| `nc_netcat_listener` | Netcat 监听后门 | critical | `command_line` 正则 `(nc\|netcat).*-l.*-p` | default_rules.json:237-251 |

### 2.2 category = behavior（8 条，进程为中心）

| name | label | severity | 触发条件 · 匹配逻辑 | 文件位置 / 实现 |
| --- | --- | --- | --- | --- |
| `orphan_process` | 孤立进程（无父进程） | high | 行为模式 `orphan_process`：父 PID 不在本机进程列表（父已退出/伪造）；排除 ppid∈{0,1,4} | default_rules.json:254-267；`rule_engine.py:833 _match_behavior` |
| `suspicious_parent_child` | 办公软件启动脚本解释器 | medium | 行为模式 `suspicious_parent`：父进程∈白名单(office/浏览器/PDF/压缩/IM) 且 子进程∈{powershell,cmd,wscript,cscript} | default_rules.json:270-283；`rule_engine.py:833` |
| `unsigned_process` | 非系统目录进程 | medium | 行为模式 `unsigned_process`：path 非空且不在 system32/syswow64/usr/bin/usr/sbin | default_rules.json:286-299；`rule_engine.py:833` |
| `high_connection_count` | 进程连接数异常 | medium | threshold：`connection_count > 50`（进程外连数突增） | default_rules.json:600-614；`rule_engine.py:709 _match_threshold` |
| `remote_desktop_suspicious` | 可疑远程控制软件 | low | regex 匹配 `name`：`(teamviewer\|anydesk\|vnc\|rustdesk\|sunlogin)` | default_rules.json:617-631；`rule_engine.py:631 _match_regex` |
| `process_chain_attack` | 进程链攻击路径 | critical | 行为模式 `process_chain`：父子链 ≥`min_chain_length=3`，链中同时出现可疑父(office/浏览器…)与可疑子(powershell/cmd/curl…)；写入 attack_path | default_rules.json:1723-1753；`rule_engine.py:1294 _match_process_chain` |
| `time_cluster_burst` | 时间聚类异常爆发 | high | 行为模式 `time_cluster`：`window_minutes=5` 内 ≥`min_count=5` 个进程启动（按 start_time 二分计数） | default_rules.json:1756-1770；`rule_engine.py:1370 _match_time_cluster` |
| `short_lived_shell` | 短存活 Shell 进程 | medium | 行为模式 `short_lived`：目标进程(powershell/cmd/wscript/cscript) 存活 `<max_alive_seconds=30`（或 threads≤1） | default_rules.json:1773-1793；`rule_engine.py:1457 _match_short_lived` |

> 说明：`orphan_process` / `suspicious_parent_child` / `unsigned_process` 的匹配逻辑封装在
> `_match_behavior` 调度器中（`rule_engine.py:833`）；`process_chain` / `time_cluster` /
> `short_lived` 有独立 `_match_*` 实现；`high_connection_count` 走 threshold 分支；
> `remote_desktop_suspicious` 走 regex（字段 `name`）。

### 2.3 category = execution（11 条，匹配 `command_line` 的进程执行特征）

| name | label | severity | 触发条件 · 匹配逻辑 | 文件位置 |
| --- | --- | --- | --- | --- |
| `dotnet_inline_compilation` | DotNet 内联编译执行（无文件） | high | `command_line` 正则 `(csc\.exe\|dotnet\.exe).*(CSharpCodeProvider\|CodeDOM\|\.cs\b\|Inline\|CompileAssemblyFromSource)` | default_rules.json:3-18 |
| `msbuild_inline_task_execution` | MSBuild 内联任务执行（无文件 LOLBin） | high | `command_line` 正则 `msbuild.*(InlineTasks\|UsingTask\|CodeTaskFactory\|TaskFactory)` | default_rules.json:20-34 |
| `msiexec_remote_lolbin` | MSIExec 远程下载执行（LOLBin） | high | `command_line` 正则 `msiexec.*(/i\|/package\|/a)\s+https?://` | default_rules.json:37-51 |
| `phishing_doc_macro` | 钓鱼文档宏执行 | high | composite(AND)：`parent_name` 正则 `(winword\|excel\|powerpnt)\.exe` **且** `name` 正则 `(powershell\|cmd\|wscript\|cscript\|mshta)\.exe` | default_rules.json:651-677 |
| `exploit_script_download` | 漏洞利用脚本下载执行 | high | `command_line` 正则 `(Invoke-WebRequest\|Invoke-RestMethod\|wget\|curl).*(Invoke-\|Get-Exploit\|CVE-\|exploit)` | default_rules.json:680-694 |
| `malicious_macro_indicator` | 恶意宏特征 | high | `command_line` 正则 `(AutoOpen\|AutoClose\|Auto_Open\|Document_Open\|Workbook_Open)` | default_rules.json:697-711 |
| `wmic_lolbin_execution` | WMIC LOLBin 执行 | high | `command_line` 正则 `wmic.*/format:` | default_rules.json:714-728 |
| `cmd_obfuscated_execution` | CMD 混淆执行 | high | `command_line` 正则 `cmd.*(\^.{0,3}){3,}`（脱字符混淆） | default_rules.json:731-745 |
| `powershell_download_cradle` | PowerShell 下载 Cradle | high | `command_line` 正则 `(iex\|Invoke-Expression\|Invoke-WebRequest\|Net\.WebClient).*(http\|https)` | default_rules.json:748-762 |
| `mshta_inline_script` | MSHTA 内联脚本执行 | high | `command_line` 正则 `mshta.*(javascript\|vbscript):` | default_rules.json:765-779 |
| `cscript_wscript_download` | CScript/WScript 下载执行 | high | `command_line` 正则 `(cscript\|wscript).*(http\|https).*\.(vbs\|js\|vbe\|jse\|wsf\|hta)` | default_rules.json:782-796 |

### 2.4 主目录统计（按 category 拆分，全部 enabled）

| category | 规则数 | rule_type 分布 |
| --- | --- | --- |
| `process` | 10 | regex ×10（均匹配 command_line） |
| `behavior` | 8 | behavior ×6（orphan/suspicious_parent/unsigned/process_chain/time_cluster/short_lived）、threshold ×1（high_connection_count）、regex ×1（remote_desktop_suspicious，匹配 name） |
| `execution` | 11 | regex ×10、composite ×1（phishing_doc_macro） |
| **合计** | **29** | — |

---

## 3. 硬编码进程规则排查结论

规则定义（name/label/category/severity/enabled/condition）**全部数据化**在 `default_rules.json`，
`anomaly_detector.py` 内**无**硬编码规则条件（仅按 category 过滤后委托 `RuleEngine.evaluate`）。

唯一「硬编码」的是 **行为模式的匹配逻辑**，集中在 `backend/app/rules/rule_engine.py`：
- `BEHAVIOR_PATTERNS`（`rule_engine.py:38`）硬编码 25 个行为模式名（含 T1 新增 5 个进程模式
  `rule_engine.py:60-64`）；
- 对应 `_match_*` 实现：`_match_process_chain:1294`、`_match_time_cluster:1370`、
  `_match_short_lived:1457`、`_match_process_name_spoof:1515`、`_match_suspicious_path:1561`、
  `_match_hidden_process:1617`、`_match_anomalous_net_process:1659`、`_match_zombie_process:1718`；
  其余（orphan/suspicious_parent/unsigned 等）在 `_match_behavior:833` 调度器内。

> 即：**规则「是什么」由 JSON 管理可改，「怎么匹配」由代码硬编码**。修改匹配语义需改代码；
> 修改阈值/启用/严重度可纯经规则管理 API。

---

## 4. 附录 A：进程专属种子规则（`docs/seed_rules_process.json`，未接入线上）

这 5 条 `category=behavior / rule_type=behavior / severity=high` 的规则**仅存在于 `docs/`**，
不在 `backend/app/rules/`，不被 `load_default_rules()` 加载，**线上不生效**；但其匹配逻辑已在
`rule_engine.py` 实现并被 `BEHAVIOR_PATTERNS` 注册（说明是「预留待接入」的进程增强规则）。

| name | label | 行为模式 | 触发条件 · 匹配逻辑 | 代码实现 | 接入状态 |
| --- | --- | --- | --- | --- | --- |
| `process_name_spoof` | 进程名伪装（仿冒系统进程） | `process_name_spoof` | 双扩展名 / 大小写混淆 / 编辑距离==1 相似名 / Unicode 同形，仿冒系统进程 | `rule_engine.py:1515` | 种子，未加载 |
| `suspicious_process_path` | 可疑进程路径 | `suspicious_path` | temp/appdata/programdata/downloads 用户可写目录、伪装 system32、ADS/UNC | `rule_engine.py:1561` | 种子，未加载 |
| `hidden_or_spoofed_service_process` | 隐蔽/仿冒服务进程 | `hidden_process` | 同名(svchost 等)不同路径（仿冒服务）；或交互式进程无窗口标题+session>0 | `rule_engine.py:1617` | 种子，未加载 |
| `anomalous_network_process` | 异常网络连接进程 | `anomalous_net_process` | 脚本解释器/非系统进程 发起非业务端口外连，或连 C2 端口(4444/8443/1337/31337/6667/9999/1080/5900) | `rule_engine.py:1659` | 种子，未加载 |
| `zombie_process_suspect` | 疑似僵尸/残留进程（待确认） | `zombie_process` | 线程==0 或完全孤立 且 启动>threshold_days(默认7)；启发式，需人工确认 | `rule_engine.py:1718` | 种子，未加载 |

---

## 5. 附录 B：其它匹配进程命令行（command_line）的跨维度规则

为满足「匹配进程字段的规则全部找出来」口径，下列规则**不属于进程检测管线主目录**，但同样匹配
进程 `command_line` 字段，按原 category 归类列出（供核对，非进程主体规则）。

| category | 规则数 | 规则 name（severity） |
| --- | --- | --- |
| `credential` | 7 | sam_dump_detection(critical) · ntds_dump_detection(critical) · dpapi_credential_theft(critical) · browser_credential_theft(critical) · lsa_secrets_dump(critical) · kerberoasting_detection(critical) · dcsync_detection(critical) |
| `defense_evasion` | 7 | obfuscated_execution_evasion(high) · code_signing_bypass(high) · process_injection_indicator(high) · amsi_bypass_attempt(high) · sysmon_tampering(high) · parent_pid_spoofing(high) · reflective_dll_injection(high) |
| `lateral` | 5 | psexec_lateral_movement(critical) · rdp_tunnel_detection(critical) · ssh_lateral_tunnel(critical) · pass_the_hash_detection(critical) · scheduled_task_lateral(critical) |
| `privilege_escalation` | 3 | service_permission_escalation(high) · scheduled_task_escalation(high) · sticky_keys_escalation(high) |
| `persistence` | 3 | image_file_execution_hijack(high) · appinit_dlls_persistence(high) · screensaver_persistence(high) |
| `discovery` | 4 | domain_discovery_commands(medium) · sensitive_file_search(medium) · clipboard_capture(medium) · smb_share_enumeration(medium) |
| `exfiltration` | 2 | dns_tunnel_exfil(high) · icmp_tunnel_exfil(high) |
| `network` | 3 | known_c2_framework(high) · domain_fronting_detection(high, disabled) · webshell_file_detection(high) |
| `impact` | 1 | data_destruction_indicator(critical) |
| **合计** | **35** | — |

> 此外，`default_attack_chain.json` 的 `attack_chain_default_c2_persistence`（critical，主机级
> `attack_chain`）其 step1 维度为 `process`，匹配 `command_line` 正则 `powershell.*-enc`，属跨维度
> 关联检测，不计入单进程规则。
> 注：`startup`(3) / `ioc`(3) 类匹配的是 `command` / `remote_address` 字段（非进程命令行），不列入本表。

---

## 6. 规则管理对进程检测的覆盖度小结

**已覆盖（规则管理可配置维度）**
- **命令行特征（LOLBin / 下载 / 横向 / 混淆 / 宏）**：`process`(10) + `execution`(11) 共 21 条
  regex/composite，覆盖 PowerShell 编码/绕过、certutil/bitsadmin/msi/wmic/mshta/regsvr32/rundll32/
  netcat、DotNet/MSBuild 内存加载、CMD 混淆、下载 Cradle、钓鱼宏等。
- **进程关系**：`orphan_process`（孤立）、`suspicious_parent_child`（异常父子）、`process_chain_attack`
  （≥3 级可疑链，写 attack_path）、`phishing_doc_macro`（父 office+子解释器）。
- **进程属性**：`unsigned_process`（非系统目录）、`remote_desktop_suspicious`（远控软件名）；
  增强种子 `process_name_spoof` / `suspicious_process_path` / `hidden_or_spoofed_service_process`
  已实现逻辑但**未接入**。
- **资源/行为**：`high_connection_count`（连接数>50）、`time_cluster_burst`（5 分钟≥5 进程）、
  `short_lived_shell`（存活<30s）；僵尸检测种子 `zombie_process_suspect` 未接入。
- **外连关联**：进程自身规则不含 C2 端口/IP（这些在 `network`/`ioc`），但
  `anomalous_net_process`（种子）与 `process_chain_attack` 的 `anomalous_net_process` 行为模式
  通过 `connections` 全局上下文按 pid 关联外连。
- **可运营性**：全部 29 条默认启用；阈值/启用/严重度均可经规则管理 API 改；白名单前置过滤。

**缺口与建议（基于代码事实）**
1. **5 条进程增强规则未接入**：`docs/seed_rules_process.json` 的进程名伪装/可疑路径/仿冒服务/
   异常外连/僵尸 规则逻辑与 `BEHAVIOR_PATTERNS` 已就绪，仅差把种子文件移入 `backend/app/rules/`
   并初始化入库，即可上线。
2. **无二进制级特征**：缺进程哈希、数字签名、导入表/内存特征检测；`process_injection_indicator`
   等仅靠命令行字符串特征（非真实注入行为）。
3. **离线快照本质**：规则基于一次性导入的进程快照，无实时/持续监控、无 fileless 检测。
4. **白名单前置风险**：白名单进程整体被剔除，可能漏掉其派生的恶意子进程链。
5. **评分口径**：进程级与主机级两套累加（权重一致 35/20/10/5/1），attack_chain 单独记入不影响
   主分；进程级 docstring 与常量权重不一致（§1.3）建议修订注释。
6. **攻击链落地**：`attack_chain_default_c2_persistence` 含 process 维度 step，但前端
   `HostDetailView.aiReportAttackChain` 当前恒为 null，未接入展示。

---

## 7. 关键代码索引（file:line）

| 关注点 | 位置 |
| --- | --- |
| 规则主源（102 条） | `backend/app/rules/default_rules.json` |
| 攻击链规则（1 条，主机级） | `backend/app/rules/default_attack_chain.json` |
| 规则聚合加载 | `backend/app/rules/loader.py:25` `load_default_rules`；`database.py:544` 初始化入库 |
| 行为模式硬编码集合 | `backend/app/rules/rule_engine.py:38` `BEHAVIOR_PATTERNS`（T1 进程模式 `:60-64`） |
| 运行时读取启用规则 | `backend/app/rules/rule_engine.py:295` `RuleEngine.load_rules` |
| 进程检测管线筛选 | `backend/app/analysis/anomaly_detector.py:78` `category in (process,behavior,execution)` |
| 白名单前置 | `backend/app/analysis/anomaly_detector.py:57` |
| 进程级累加评分 | `backend/app/analysis/anomaly_detector.py:12`（权重）、`:104`（合并） |
| 主机级风险定级 | `backend/app/analysis/risk_assessor.py:16`（权重）、`:25`（等级） |
| 行为匹配调度 | `backend/app/rules/rule_engine.py:833` `_match_behavior` |
| 进程链/时间聚类/短存活 | `rule_engine.py:1294` / `:1370` / `:1457` |
| 进程增强行为（种子） | `rule_engine.py:1515/1561/1617/1659/1718` |
| 规则模型 | `backend/app/models/rule.py:12` `Rule`（enabled/severity/condition 可改） |
| 规则管理 API | `backend/app/api/rules.py`（list/create/bulk-enable/reset/update/delete） |
| 进程种子（未接入） | `docs/seed_rules_process.json` |
