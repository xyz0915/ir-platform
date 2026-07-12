# 进程检测加强规则评估报告（应急安全视角）

> 目标：基于 `docs/process_rules_catalog.md` §6 指出的三个硬缺口，给出**系统化、可落地**的加强规则集。
> 全部结论基于**当前仓库真实代码**（非早期设计文档），已逐条标注 `file:line`。
>
> ⚠️ **重要前提（代码已演进）**：`docs/process_detection_enhancement.md` 的 T1–T8 设计大部分**已落地**：
> - `orphan_process` 修正已生效（`rule_engine.py:873-883`，`ppid not in process_map` 且排除 0/1/4）；
> - `suspicious_parent` 已改为 **condition 驱动**（`rule_engine.py:885-908`，父列表含 office+浏览器+PDF+压缩+IM）；
> - 两套 severity 权重已统一为 `{critical:35,high:20,medium:10,low:5,info:1}`（`anomaly_detector.py:12`）；
> - 5 个进程行为模式已在 `BEHAVIOR_PATTERNS`（`rule_engine.py:60-64`）且 `_match_*` 实现齐全
>   （`:1515/1561/1617/1659/1718`）；`global_context` 已补 `connections`（`anomaly_detector.py:84`）。
> 因此本报告**不重复**已完成项，聚焦真正缺口：① 5 条种子规则未接入；② 二进制特征无数据源/JOIN；
> ③ 内存/ETW/session/实时缺失；④ 白名单整体剔除导致的衍生链漏检。

---

## 0. 三类标记与现状基线

每条规则标注其一：
- **【已有设计待接入】**：规则逻辑/JSON 已存在，仅差接线（移动文件/初始化/小改造）。
- **【需新增数据源】**：当前 `ProcessInfo` 或采集端无对应字段，须扩 schema + Agent 采集。
- **【纯架构演进】**：无需新字段、属管线/评分/实时性改造。

**进程快照现状（决定缺口边界）**：
- `ProcessInfo` 字段（`backend/app/schemas/agent_data.py:69-79`）只有
  `pid/ppid/name/path/command_line/user/start_time/threads/connections` ——
  **无** `sha256/is_signed/signer/内存区段/session/window_title`。
- 文件级哈希/签名**已采集**（`file_hashes` 维度含 `sha256/is_signed/signer`，
  `analysis_service.py:155-171` → `FileHash` 模型 + IOC `hash` 匹配 `ioc_checker.py:99`），
  **但进程检测管线未做 process↔file 关联**。
- 白名单在检测入口**整体剔除进程**（`anomaly_detector.py:57-58` →
  `WhitelistService.filter_whitelisted`，`whitelist_service.py:143-154`），
  `signature` 类别为**空 stub**（`whitelist_service.py:137-139`）→ 衍生链漏检根因。
- 检测为**一次性快照**（`AnomalyDetector.detect_processes` 读 `raw_data.processes` 全量），
  无事件订阅/增量。

---

## 1. 缺口①：二进制特征校验机制（补 hash / 签名 / 内存）

### 1.1 新数据源需求与采集改造点
| 能力 | 现状 | 需补数据源 | 采集改造点 |
|---|---|---|---|
| 已知恶意哈希黑名单 | `file_hashes` 已采集 sha256；IOC `hash` 匹配仅查 network（`ioc_checker.py:99`） | **无需新 Agent 字段**：进程按 `path` JOIN 已采集的 `file_hashes` 即可获得 `exe_sha256` | `analysis_service.py` 在 `detect_processes` 前按 `process.path == file_hash.file_path` 注入 `exe_sha256`/`exe_is_signed`/`exe_signer`（低成本，纯后端 JOIN） |
| 数字签名缺失/失效 | `file_hashes` 已有 `is_signed/signer` | 同上（JOIN 即可） | 同上 |
| 签名被吊销/过期 | 无 | 吊销库（离线 CRL/OCSP 缓存） | 新增 `revoked_ca` 数据源 + 校验逻辑 |
| 无文件内存注入（reflective/hollowing/远线程） | 完全无 | 进程**内存快照**（线程起始地址、内存区段、PE 头痕迹） | Agent 采集端扩展 `memory_sections` 字段（`schemas/agent_data.py` 扩 `ProcessInfo`）；或经 ETW（见 §2） |
| 脚本解释器加载异常 PE | 完全无 | ETW `ImageLoad` / AMSI 事件 | 事件订阅（§2 实时管线） |
| ETW/AMSI 旁路 | 仅 `amsi_bypass_attempt` 命令行规则（`default_rules.json:1064`） | ETW provider 禁用事件 | 事件订阅（§2） |

### 1.2 加强规则表

| name | 中文 label | category | severity | 触发逻辑（条件 / 补在 rule_engine.py 的哪） | 适用场景 | 优先级 | 类型 |
|---|---|---|---|---|---|---|---|
| `malicious_hash_process` | 进程 exe 命中恶意哈希黑名单 | behavior（或 process） | critical | 进程注入 `exe_sha256` 后匹配 IOC `hash` 列表（复用 `RuleEngine._load_iocs_by_type("hash")`，扩展 `ioc_checker` 使 process 维度也查 hash）；或新增 behavior pattern `malicious_hash` | 已知木马/勒索哈希 | P0 | 【已有设计待接入】file_hashes 已采集，仅缺 process↔file JOIN（`analysis_service.py:155`） |
| `unsigned_executable` | 进程 exe 无数字签名 | behavior | high | JOIN `file_hashes` 注入 `exe_is_signed==0` 或 `exe_signer` 空；behavior `unsigned_exe`（`_match_*` 读 `data_item.get("exe_is_signed")`） | 非系统目录无签名 exe | P1 | 【需新增数据源】部分已有：file_hashes 有 is_signed，仅需 JOIN |
| `revoked_expired_signature` | 签名被吊销/过期 | behavior | high | `exe_signer` 命中吊销库（CRL/OCSP 离线缓存）；behavior `revoked_sig` | 有效签名但 CA 已吊销的伪装 | P2 | 【需新增数据源】吊销库 |
| `fileless_reflective_injection` | 无文件内存注入（reflective/hollowing/远线程） | behavior | critical | 需进程 `memory_sections`（线程起始地址在 non-image/堆、PE 头痕迹）；behavior `memory_injection`（新增 `_match_memory_injection`，参考现有 `_match_*` 注册进 `BEHAVIOR_PATTERNS`） | fileless 攻击、进程镂空 T1055.012 | P1 | 【需新增数据源】内存快照 +【纯架构演进】 |
| `script_interpreter_memory_pe` | 脚本解释器内存加载异常 PE | behavior | high | 需 ETW `ImageLoad` 事件：powershell/python 在内存加载 PE 且无磁盘文件；behavior `interpreter_mem_pe` | 内存加载无文件落地（DotNet inline 进阶） | P2 | 【需新增数据源】ETW 事件 |
| `amsi_etw_tamper` | ETW/AMSI 旁路（事件级） | behavior | high | 订阅 ETW provider 禁用 / `amsi.dll` 内存修补事件；behavior `etw_amsi_tamper`（升级现有 `amsi_bypass_attempt` 命令行规则） | AMSI/ETW patch | P2 | 【纯架构演进】需 §2 事件订阅 |

> 关键低成本杠杆：前两条（恶意哈希、无签名）**无需改 Agent**，仅靠 `analysis_service` 的
> process→file_hashes JOIN 即可上线，应作为 P0/P1 首选（数据源已存在）。

---

## 2. 缺口②：实时监控替代方案（补快照式缺口）

### 2.1 工程可行演进方案（不要求立刻写流式引擎）
1. **事件订阅（首选）**：Windows 经 **ETW** `Microsoft-Windows-Kernel-Process` / `Microsoft-Windows-Sysmon`；Linux 经 **auditd**（`-a always,exit -F arch=b64 -S execve`）或 **eBPF**（Tracee/Falco）。订阅"进程创建/远线程/镜像加载"事件，与现有 snapshot 管线**并行**共存。
2. **兼容路径（不影响现有 29 条）**：snapshot 管线（`detect_processes`）**保持不变**；新增 `detect_process_stream` 消费事件流，复用同一套 `rules` 表（`category ∈ {process,behavior,execution}`）。规则可双跑，snapshot 保底、事件流补实时。
3. **周期增量重扫 cadence**：Agent 维持"全量快照每 N 分钟"+ "增量 diff 每秒"，后端对 diff 触发轻量 `RuleEngine.evaluate`（仅新增进程），降低全量重算成本。
4. **fileless / 内存驻留触发时机**：事件流检测到"进程创建即加载异常 PE / 无磁盘 exe 却有活跃连接"时即时告警，不必等下次快照。
5. **数据落库**：进程创建事件写入新 `process_events` 表，供跨快照关联（§2.2 的 R2）与溯源。

### 2.2 加强规则表

| name | 中文 label | category | severity | 触发逻辑（/`_match_*` 位置） | 适用场景 | 优先级 | 类型 |
|---|---|---|---|---|---|---|---|
| `process_respawn_loop` | 短时间重复进程重生 | behavior | high | 同 `path`/`command_line` 在窗口内重复 ≥K 次（如 60s≥5）。行为模式 `process_respawn`：快照下可由 `time_cluster` 近似（已存在 `rule_engine.py:1370`），精确版需事件流计数 | 驻留守护/木马反复拉起 | P1 | 【纯架构演进】事件流精确，快照可近似 |
| `process_vanished_between_snapshots` | 快照间出现又消失的进程 | behavior | high | 进程仅见于 `process_events`/`network_connections`/`timeline` 但不在任一完整快照 → 残留/规避。行为模式 `vanished_process`（需 `process_events` 表） | 反取证/短时驻留 | P2 | 【纯架构演进】需增量快照/事件表 |
| `injection_window_anomaly` | 注入行为窗口异常 | behavior | critical | 进程启动后极短时间（<2s）向其它进程建远线程。行为模式 `injection_window`（事件流） | 远线程注入、进程镂空 | P2 | 【纯架构演进】需事件流 |
| `fileless_memory_residency` | fileless 内存驻留 | behavior | high | 进程 `path` 为空/UNC/内存 但 `connection_count>0` 或 `threads>0`（**基于现有 `path`+`connections` 字段，快照可部分实现**）。行为模式 `fileless_residency` | 无磁盘落地的内存驻留进程 | P1 | 【纯架构演进】低成本，快照可先做 |

> 注：纯快照下 `time_cluster_burst`（已存在）已近似覆盖"集中爆发"，但**无法**识别"两次快照间消失"
> 与"注入时间窗"——这两类必须靠事件流（P2）。

---

## 3. 缺口③：父子进程行为链追踪（补白名单衍生链缺口）

**当前已具备**：`orphan_process`（修正后，`rule_engine.py:873-883`）、`suspicious_parent`（condition 驱动，`rule_engine.py:885-908`）、`process_chain_attack`（≥3 级，`rule_engine.py:1294`）、`phishing_doc_macro`（父 office+子解释器，`default_rules.json:651`）。缺口在**多级祖先、白名单穿透、LOTL 组合、伪造/跨会话父、链路级评分**。

### 3.1 加强规则表

| name | 中文 label | category | severity | 触发逻辑（/`_match_*` 位置） | 适用场景 | 优先级 | 类型 |
|---|---|---|---|---|---|---|---|
| `whitelist_derived_child` | 白名单进程派生的可疑子链 | behavior | high | **核心修复**：改造 `anomaly_detector.py:57-58` 不再整体剔除白名单进程，改为标 `whitelisted=True` 仍建树；当白名单进程派生 script/LOLBin 子进程则触发。行为模式 `whitelist_derived_chain`（新增 `_match_*`） | 白名单程序(浏览器/办公)被利用拉起恶意子进程 | P0 | 【纯架构演进】核心漏洞修复 |
| `grandparent_chain_anomaly` | 祖辈(祖父)链异常 | behavior | high | 扩展 `global_context.process_map` 支持多级祖先回溯（当前仅补 1 级 `parent_name`，`anomaly_detector.py:69-75`）；行为模式 `ancestry_chain`：白名单/script 父的**父**为可疑系统服务/异常 | 多层伪装父链 | P1 | 【纯架构演进】小代码（补全祖先链） |
| `lotl_chain_combo` | LOTL 链式组合 | attack_chain / behavior | high | 复用现有 `attack_chain` 框架（`default_attack_chain.json` 已含 process 维 step1）：新增 "compress→decode→execute" 多 step 链（如 `certutil -decode` → `powershell -enc`）。或 behavior `lotl_chain`（condition 驱动多 step） | living-off-the-land 组合技 | P1 | 【已有设计】attack_chain 框架已存在 +【纯架构演进】 |
| `fabricated_parent_pid` | 伪造/不可能父 PID | process / behavior | high | 升级现有 `parent_pid_spoofing`（`default_rules.json:1036`，仅命令行）：加字段级校验 `ppid==pid`、或 `ppid` 指向自身/不可能是父。行为模式 `parent_pid_spoof`（字段级分支） | 父 PID 伪造（PPID spoofing） | P1 | 【已有设计待接入】命令行规则已有 +【纯架构演进】字段级 |
| `cross_session_parent_child` | 跨会话/跨用户父子 | behavior | medium | 父 `session==0` 系统进程但子交互会话 GUI/脚本，或父子 `user` 不同。需进程 `session`/`user` 字段（`ProcessInfo` 当前无 `session`） | 跨会话横向/服务伪装交互进程 | P2 | 【需新增数据源】session 字段 |
| `behavior_chain_scoring` | 基于行为链的评分 | （评分机制） | — | 扩展 `_apply_accumulated_scoring`（`anomaly_detector.py:104`）从"按 PID 聚合"改为"按 ancestry 链路聚合"：同一祖先链路多节点命中累加链路级 `risk_score`，避免白名单父穿透后子进程单点漏评 | 链式攻击整体定级 | P1 | 【纯架构演进】评分机制升级 |

### 3.2 已有设计待接入的种子规则（P0 首选，仅差接线）
以下 5 条 JSON 已存于 `docs/seed_rules_process.json`，且 `_match_*` 已在 `rule_engine.py` 实现、
`BEHAVIOR_PATTERNS` 已注册 —— **只需把文件移入 `backend/app/rules/` 并重新初始化入库即可生效**
（`loader.load_default_rules` 仅 glob `rules/*.json`，`database.py:544` 入库）。

| name | label | category | severity | 行为模式 | 实现位置 | 状态 |
|---|---|---|---|---|---|---|
| `process_name_spoof` | 进程名伪装 | behavior | high | `process_name_spoof` | `rule_engine.py:1515` | 【已有设计待接入】 |
| `suspicious_process_path` | 可疑进程路径 | behavior | high | `suspicious_path` | `rule_engine.py:1561` | 【已有设计待接入】 |
| `hidden_or_spoofed_service_process` | 隐蔽/仿冒服务进程 | behavior | high | `hidden_process` | `rule_engine.py:1617` | 【已有设计待接入】 |
| `anomalous_network_process` | 异常网络连接进程 | behavior | high | `anomalous_net_process` | `rule_engine.py:1659` | 【已有设计待接入】 |
| `zombie_process_suspect` | 疑似僵尸/残留进程 | behavior | high | `zombie_process` | `rule_engine.py:1718` | 【已有设计待接入】 |

---

## 4. 汇总：总表 + 实施分批

### 4.1 总表（缺口 → 规则 → 优先级 → 状态 → 需新数据源）

| 缺口 | 规则 | 优先级 | 状态 | 需新数据源 |
|---|---|---|---|---|
| ① 二进制 | `malicious_hash_process` | P0 | 【已有设计待接入】 | 否（JOIN file_hashes 即可） |
| ① 二进制 | `unsigned_executable` | P1 | 【需新增数据源·部分已有】 | 否（JOIN file_hashes） |
| ① 二进制 | `revoked_expired_signature` | P2 | 【需新增数据源】 | 是（吊销库） |
| ① 二进制 | `fileless_reflective_injection` | P1 | 【需新增数据源】+【纯架构演进】 | 是（内存快照） |
| ① 二进制 | `script_interpreter_memory_pe` | P2 | 【需新增数据源】 | 是（ETW ImageLoad） |
| ① 二进制 | `amsi_etw_tamper` | P2 | 【纯架构演进】 | 是（ETW 事件） |
| ② 实时 | `process_respawn_loop` | P1 | 【纯架构演进】 | 否（事件流精确/快照近似） |
| ② 实时 | `process_vanished_between_snapshots` | P2 | 【纯架构演进】 | 是（process_events 表） |
| ② 实时 | `injection_window_anomaly` | P2 | 【纯架构演进】 | 是（事件流） |
| ② 实时 | `fileless_memory_residency` | P1 | 【纯架构演进】 | 否（快照可部分实现） |
| ③ 链追踪 | `whitelist_derived_child` | P0 | 【纯架构演进】 | 否（改剔除逻辑） |
| ③ 链追踪 | `grandparent_chain_anomaly` | P1 | 【纯架构演进】 | 否（补祖先链） |
| ③ 链追踪 | `lotl_chain_combo` | P1 | 【已有设计】+【纯架构演进】 | 否 |
| ③ 链追踪 | `fabricated_parent_pid` | P1 | 【已有设计待接入】+【纯架构演进】 | 否 |
| ③ 链追踪 | `cross_session_parent_child` | P2 | 【需新增数据源】 | 是（session 字段） |
| ③ 链追踪 | `behavior_chain_scoring` | P1 | 【纯架构演进】 | 否（评分升级） |
| ③ 链追踪 | `process_name_spoof` 等 5 条种子 | P0 | 【已有设计待接入】 | 否 |

### 4.2 加强规则总数与优先级分布
- **共 21 条加强规则** = 16 条本次新增/增强设计 + 5 条已有设计待接入的种子规则。
- **优先级分布**：**P0 = 7**（含 5 条种子 + `malicious_hash_process` + `whitelist_derived_child`）、
  **P1 = 8**（`unsigned_executable`/`fileless_reflective_injection`/`process_respawn_loop`/
  `fileless_memory_residency`/`grandparent_chain_anomaly`/`lotl_chain_combo`/`fabricated_parent_pid`/
  `behavior_chain_scoring`）、**P2 = 6**（`revoked_expired_signature`/`script_interpreter_memory_pe`/
  `amsi_etw_tamper`/`process_vanished_between_snapshots`/`injection_window_anomaly`/
  `cross_session_parent_child`）。
- **类型分布**：【已有设计待接入】7（5 种子 + `malicious_hash_process` + `fabricated_parent_pid` 的命令行部分）；
  【需新增数据源】6（`revoked_expired_signature`/`fileless_reflective_injection`/`script_interpreter_memory_pe`/
  `amsi_etw_tamper`/`cross_session_parent_child` + `unsigned_executable` 部分）；
  【纯架构演进】约 10（链路/评分/实时/白名单穿透等）。

### 4.3 实施分批建议
- **批次 1（P0，零/低代码，立即见效）**：
  1. 将 `docs/seed_rules_process.json` 移入 `backend/app/rules/` 并执行初始化入库（5 条进程增强规则上线）。
  2. 后端 JOIN：`analysis_service.py` 在 `detect_processes` 前按 `path` 关联 `file_hashes`，注入
     `exe_sha256/exe_is_signed/exe_signer` → 启用 `malicious_hash_process`（critical，命中 IOC 哈希黑名单）。
  3. 改造 `anomaly_detector.py:57-58`：白名单进程由"整体剔除"改为"标 `whitelisted=True` 仍建树" →
     启用 `whitelist_derived_child`（堵住衍生链漏检根因）。
- **批次 2（P1，扩关联/链/低成本内存）**：
  - `unsigned_executable`、`fileless_memory_residency`、`process_respawn_loop`（快照可近似）、
    `grandparent_chain_anomaly`（补祖先链）、`lotl_chain_combo`（复用 attack_chain）、
    `fabricated_parent_pid`（字段级）、`behavior_chain_scoring`（链路级评分）。
  - `fileless_reflective_injection`：需与批次 3 的内存采集协同。
- **批次 3（P2，架构演进 + 新数据源）**：
  - 事件流管线（ETW/auditd/eBPF）上线 → 支撑 `process_vanished_between_snapshots`、
    `injection_window_anomaly`、`script_interpreter_memory_pe`、`amsi_etw_tamper`。
  - `ProcessInfo` 扩 `session`/`memory_sections` 字段（协同 Agent 采集端） →
    `cross_session_parent_child`、`revoked_expired_signature`。

### 4.4 兼容性声明
- 所有新增规则复用现有 `rules` 表 / `RuleEngine.evaluate` / `BEHAVIOR_PATTERNS` 机制（如 `_match_*`）；
  新增 behavior pattern 不影响既有 29 条规则（契约保护，见 `process_detection_enhancement.md §5`）。
- 实时事件管线与 snapshot 管线**并行共存**，不改动现有 29 条检测逻辑。
- 白名单改造向后兼容：白名单进程仍被标记但不再"消失"，其恶意子链可被 `whitelist_derived_child` 捕获。

---

## 5. 关键代码索引（file:line，本次报告引用）

| 关注点 | 位置 |
|---|---|
| 进程快照字段（无 hash/签名/内存/session） | `backend/app/schemas/agent_data.py:69-79` `ProcessInfo` |
| 文件哈希/签名已采集（待 JOIN） | `analysis_service.py:155-171`（→ `FileHash`） |
| IOC hash 匹配（仅查 network，未查 process） | `app/analysis/ioc_checker.py:99` |
| 白名单整体剔除（衍生链漏检根因） | `anomaly_detector.py:57-58` + `whitelist_service.py:143-154` |
| 白名单 signature 为 stub | `whitelist_service.py:137-139` |
| 仅 1 级 parent_name 反查 | `anomaly_detector.py:69-75` |
| 累加评分（PID 级，需升链路级） | `anomaly_detector.py:104` `_apply_accumulated_scoring` |
| 已落地：orphan 修正 | `rule_engine.py:873-883` |
| 已落地：suspicious_parent condition 驱动 | `rule_engine.py:885-908` |
| 已落地：5 进程行为模式 + `_match_*` | `rule_engine.py:60-64`；`:1515/1561/1617/1659/1718` |
| 已落地：权重统一 | `anomaly_detector.py:12` |
| 已落地：global_context.connections | `anomaly_detector.py:84` |
| 已有 attack_chain 框架（含 process 维 step1） | `backend/app/rules/default_attack_chain.json` |
| 种子规则（未接入） | `docs/seed_rules_process.json`（5 条） |
| 规则加载（仅 glob rules/*.json） | `loader.py:25`；入库 `database.py:544` |
| 权重统一依据 | `process_detection_enhancement.md §4.1`（与 anomaly_detector.py:12 一致） |
