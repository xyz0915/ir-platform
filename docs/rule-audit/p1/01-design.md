# P1 阶段设计文档 —— 重大漏报治理与能力短板补齐

| 项 | 内容 |
| --- | --- |
| 阶段 | P1（重大漏报 / 能力短板） |
| 环节 | 设计（第 1/4 环节） |
| 上游 | `optimized-feasibility-v2.md` P1 章节、`p0/04-verify.md` |
| 下游 | `p1/02-dev.md` → `p1/03-test.md` → `p1/04-verify.md` |
| 编写日期 | 2026-08-08 |

---

## 1. 背景与本阶段定位

P0 解决的是"规则**不可能**命中"（占位 IOC、无消费层、无采集字段）。
P1 解决的是"规则**命中了也没用**"——即命中率与信噪比的问题：

- 有的规则**恒命中**（100% 误报），淹没真实告警；
- 有的规则**恒不命中**（依赖字段无产出 / 匹配算法结构性不可达）；
- 有的规则**重复命中**（同一行为出两条 critical，虚增风险评分）。

本阶段所有结论**均由真实生产库 `backend/data/ir_platform.db` 实测得出**，不采用推断。探针脚本：`backend/_p1_probe.py`、`_p1_chain_probe.py`、`_p1_dup_probe.py`、`_p1_field_probe.py`。

### 1.1 实测基线

| 数据表 | 行数 |
| --- | --- |
| `process_events` | 2199 |
| `abnormal_processes` | 685 |
| `registry_keys` | 3160 |
| `network_connections` | 658 |
| `file_hashes` | **70** |
| `alerts` | 65 |
| `iocs` | 4 |

规则库现状（137 条，不含 10 条 attack_chain）：

| 严重度 | 数量 | 占比 |
| --- | --- | --- |
| critical | 26 | 19.0% |
| high | 86 | **62.8%** |
| medium | 23 | 16.8% |
| low | 2 | **1.5%** |

**81.8% 的规则是 high 及以上**——这本身就是一个需要治理的信号：当一切都是高危时，没有什么是高危的。

---

## 2. 问题清单（实测确认）

### 2.1 【P1-1-A】`unsigned_executable` 100% 误报 —— 严重

**实测**：非系统目录进程 541 条，其中 **541 条（100.0%）**会被判定为"无签名可执行文件"，severity=`high`。

**样例**（全部是正常文件）：

```
C:\Windows\servicing\TrustedInstaller.exe                    ← 微软签名的系统组件
C:\Windows\WinSxS\...\TiWorker.exe                           ← 微软签名的系统组件
C:\Users\xyz\...\node_modules\@esbuild\win32-x64\esbuild.exe ← 开发工具
C:\Users\xyz\AppData\Local\QuarkUpdater\...\updater.exe      ← 正常软件更新器
```

**根因（两层）**：

1. **缺失被当作否定**。`rule_engine.py:2418`：

   ```python
   if exe_is_signed in (0, None, "", False):
       return True
   ```

   `None` 表示"**未知**（没有对应的 `file_hashes` 记录）"，却与 `0`（**确认未签名**）等价处理。而 `file_hashes` 仅 70 行、与 `process_events.process_path` **交集为 0**，因此所有进程的 `exe_is_signed` 恒为 `None` → 恒返回 `True`。

2. **系统目录白名单过窄**。`system_dirs` 仅含 `system32`/`syswow64`/`program files`(x86)，遗漏 `C:\Windows\WinSxS`、`C:\Windows\servicing`、`C:\Windows\Microsoft.NET` 等大量微软签名目录。

**设计决策**：

- 三态语义化：`None`（未知）→ **不判定，返回 False**；仅 `0`/`False`/`""`（明确未签名）→ 判定成立。这是"未知不等于有罪"的基本原则。
- 扩充系统目录白名单，新增 `c:\windows\winsxs`、`c:\windows\servicing`、`c:\windows\microsoft.net`、`c:\windows\assembly`。
- 严重度 `high` → `medium`（无签名本身是弱信号，需与路径/行为组合才有价值）。
- 新增 `_meta.requires_field: "exe_is_signed"` 声明，并纳入 P2-3 的可观测清单，让运维知道"该规则当前因缺 `file_hashes` 覆盖而静默"。

> **不做的事**：不引入"猜测签名状态"的启发式（如按目录推断）。宁可静默，不可造假——与 P0 同一原则。

### 2.2 【P1-1-B】依赖未采集字段的 behavior 规则 —— 与 P0-3 同类

实测 `process_events.detail`（2199 行）内字段出现情况：

| 字段 | 出现 | 结论 |
| --- | --- | --- |
| `session` | 1224/2199 | ✅ 可用 |
| `memory_sections` | **0/2199** | ❌ 零产出 |
| `exe_is_signed` / `exe_signer` / `exe_sha256` | 0（依赖 `file_hashes` JOIN，覆盖 0%） | ❌ 实际不可用 |

受影响规则：

| 规则 | pattern | 依赖 | 处置 |
| --- | --- | --- | --- |
| `fileless_reflective_injection` | `memory_injection` | `memory_sections` | 置 `enabled:false` + `disabled_reason` |
| `script_interpreter_memory_pe` | `interpreter_mem_pe` | `memory_sections` | 置 `enabled:false` + `disabled_reason` |
| `amsi_etw_tamper` | `etw_amsi_tamper` | ETW 事件流 | 置 `enabled:false` + `disabled_reason` |
| `injection_window_anomaly` | `injection_window` | 事件流时序 | 置 `enabled:false` + `disabled_reason` |
| `malicious_hash_process` | list on `exe_sha256` | `file_hashes` 覆盖 | 保留启用（IOC 驱动，空库不命中，无误报风险） |
| `cross_session_parent_child` | `cross_session` | `session` | **保留启用**（字段可用） |
| `revoked_expired_signature` | `revoked_sig` | `exe_signer` | 保留启用（空库降级 False，无误报风险） |

**处置原则**（沿用 P0-3）：**下线而非删除**，保留 `depends_on` 复活线索，`label` 加"（已下线·待采集器补齐）"后缀。

区分标准是**误报风险**而非"是否有数据"：
- `revoked_sig` / `malicious_hash_process` 缺数据时降级为 `False` → 静默、无害，**保留**；
- `memory_injection` 等虽然也降级为 `False`，但它们的存在会让运维**误以为已覆盖内存注入检测** → 必须显式下线标注。

### 2.3 【P1-1-C】宽泛 regex 导致的结构性误报

| 规则 | severity | field | pattern | 问题 |
| --- | --- | --- | --- | --- |
| `ws_behinder_godzilla` | high | `behinder_godzilla_signal` | `(true\|1)` | **用 regex 匹配布尔字段**。任何含字符 `1` 的值（如 `"score:10"`、`"false, 1 hit"`）均命中 |
| `ms_filter_signal` | medium | `evidence` | `(Filter\|addFilter\|StandardContext\|priority\|servlet)` | 任何 Java Web 应用的证据文本必含 `Filter`/`servlet` |
| `ms_anomaly_class` | high | `class_signals` | `(MemShell\|Filter\|Servlet\|ClassLoader\|Spring\|...)` | 同上，`Spring`/`Servlet` 是正常框架标识 |
| `ms_conn_signal` | high | `conn_signals` | `(\d{1,3}\.){3}\d{1,3}:\d+` | 匹配任意 `IP:端口`，等价于"只要有连接就告警" |
| `ws_suspicious_funcs` | high | `suspicious_funcs` | `(eval\|base64_decode\|...)` | 正常 PHP 框架大量使用 `base64_decode`/`preg_replace` |
| `ws_webdir_activity` | high | `path` | `(upload\|tmp\|cache\|static\|public\|...).*\.(php\|jsp\|...)` | 正常站点的 `/static/index.php` 即命中 |

**设计决策**：

1. `ws_behinder_godzilla` 改用 `threshold`/`exists` 语义而非 regex——布尔字段用 regex 是类型误用。改为 `exists` + `expected_value: true` 语义（引擎已有 `_match_exists`，扩展支持值比较）。
2. `ms_filter_signal`、`ms_anomaly_class` 降 severity 并改为 `composite`：单一关键词不足以定性，须"关键词 + 至少一个异常信号（如 `agent_signals` 或 `thread_signals`）"共同成立。
3. `ms_conn_signal` 降 `high` → `low`，且改为仅作为 composite 的**子条件**，不再独立出告警。
4. `ws_suspicious_funcs` / `ws_webdir_activity` 归并为一条 `composite`：**Web 目录 + 脚本后缀 + 可疑函数**三者同时成立才告警，单项不再独立触发。

### 2.4 【P1-2】behavior pattern 重复 —— 实测 2 组（非 1 组）

可行性报告只列出了 `credential_dump`。实测扫描发现**还有一组未被审计的重复**：

```
pattern = credential_dump  (2 条)
  - lsass_dump_detection      severity=critical   label=LSASS 凭据转储
  - credential_dump_behavior  severity=critical   label=凭据导出综合行为

pattern = dll_sideload  (2 条)
  - dll_search_order_hijack   severity=high       label=DLL 搜索顺序劫持
  - dll_hijack_behavior       severity=high       label=DLL 侧加载行为
```

两组的 `condition` 除 `description` 外完全一致，即**同一份数据会产生两条独立告警**。后果：

- 主机风险评分被重复计入，虚高；
- 告警列表出现语义重复条目，分析师需人工判重；
- `critical` 级重复尤其有害（`credential_dump` 组）。

**设计决策**：每组**保留语义更明确的一条，另一条置 `enabled:false`**，而非物理删除：

| 保留 | 下线 | 理由 |
| --- | --- | --- |
| `lsass_dump_detection` | `credential_dump_behavior` | 前者 label 指明 LSASS 具体目标，可操作性强 |
| `dll_search_order_hijack` | `dll_hijack_behavior` | 前者对应 MITRE T1574.001 明确技战术 |

下线条目补 `_meta.disabled_reason: "duplicate_pattern"` 与 `duplicate_of` 指向保留项，便于追溯。

### 2.5 【P1-3】攻击链 registry 步骤**结构性永不可达** —— 严重

可行性报告的假设是"`registry` 采集器可能不产出 `key_path`"。**实测证伪**：`registry_keys` 有 3160 行，`key_path` 齐备，且 `(?i).*\\Run` 可正常命中（如 `SOFTWARE\Microsoft\Windows\CurrentVersion\Run\SecurityHealth`）。

**真实根因是排序与贪心算法的交互缺陷**：

`rule_engine.py:2838-2843` 的排序键：

```python
def _sort_key(e):
    ts = e.get("timestamp")
    return (ts is None, ts if ts is not None else datetime.min)
```

即"**有时间戳的事件排在前，无时间戳的排在后**"。而各维度时间戳可用性为：

| 维度 | timestamp | 排序位置 |
| --- | --- | --- |
| `registry` | 有（`last_write_time` → 退化 `collected_at`） | **靠前** |
| `timeline` | 有 | 靠前 |
| `process` / `connection` / `persistence` / `ioc` | **恒为 `None`**（代码显式置 None） | **靠后** |

匹配算法要求每一步"位于上一步索引之后"。因此对于 `process → connection → registry` 这类**以 registry 收尾**的链：

```
排序后: [registry, registry, ..., process, connection, ...]
step1(process)    → 命中索引 K（在 registry 之后）
step2(connection) → 命中索引 K+1
step3(registry)   → 需索引 > K+1，但所有 registry 均在 < K → 【永不命中】
```

已用 `_p1_chain_probe.py` 推演验证，输出：

```
step1(process): 命中索引 2
step2(connection): 命中索引 3
step3(registry): 在索引 >3 范围内【找不到】该维度事件 → 链中断
结论：该链 ... 【永不可达】
```

**受影响**：10 条攻击链中的 2 条——`attack_chain_default_c2_persistence`（P0 刚修好 IOC 的那条）、`attack_chain_webshell_certutil`。即 **P0-1 的修复成果被这个 bug 完全抵消**，链依然不可达。

**加重因素**：`registry_keys.last_write_time` **3160/3160 全为空**，退化到 `collected_at` 后**去重值仅 2 个**——即所有注册表项共享同一"伪时间戳"。给它排序权重不仅无益，反而有害。

**设计决策（方案 C：语义修正）**：

评估了三个方案：

| 方案 | 做法 | 评价 |
| --- | --- | --- |
| A | 把 registry 的 timestamp 也置 None | 可解不可达，但丢弃 `last_write_time` 未来可用时的真实时序 |
| B | 排序改为"无时间戳排前" | 只是把问题转移到 timeline 维度，治标 |
| **C** | **区分"无时间戳"与"时间戳不可信"，并让贪心匹配对无序事件放宽索引约束** | 语义正确，且保留未来真实时序能力 |

采用 **C**，具体：

1. `_build_host_events` 为每个事件增加 `ordered: bool` 标志——`timestamp` 存在**且该维度时序可信**时为 `True`，否则 `False`。
2. registry 维度：仅当 `last_write_time` 非空时 `ordered=True`；退化到 `collected_at` 时 `ordered=False`（`collected_at` 是采集时刻，不代表事件发生时刻）。
3. `_match_attack_chain` 贪心时：`ordered=True` 的事件之间维持严格索引递增；`ordered=False` 的事件**不参与索引约束**（可在任意位置被选中，但每个事件仍只能被消费一次）。
4. 时间窗 `span` 计算维持原状——仅统计 `ordered=True` 的事件，无序事件不参与时间约束。

这样：当前（`last_write_time` 全空）2 条链恢复可达；未来采集器补齐 `last_write_time` 后，自动升级为真正的时序校验，无需改规则。

### 2.6 【P1-4】"仅判进程名"规则降权/复合化 —— 实测 6 条（非 5 条）

| 规则 | 当前 severity | pattern | 问题 |
| --- | --- | --- | --- |
| `cmd_powershell_chain` | high | `cmd\.exe` | 每台 Windows 机器每天数百次正常执行 |
| `msbuild_inline_task_execution` | high | `msbuild\.exe` | 开发机正常构建 |
| `msiexec_remote_lolbin` | high | `msiexec\.exe` | 正常软件安装 |
| `bitsadmin_download` | medium | `bitsadmin\.exe` | 正常系统更新 |
| `ws_file_name` | high | web-shell 文件名 或组 | 含 `cmd\.(php\|jsp...)`，`cmd.php` 可能是正常路由 |
| `remote_desktop_suspicious` | low | `(teamviewer\|anydesk\|vnc\|rustdesk\|sunlogin)` | 企业内正常远程办公工具 |

**设计决策**——按"是否存在可判别的恶意参数特征"分两类处理：

**类别 1：有明确恶意参数特征 → 改 `composite`（进程名 AND 参数特征）**

| 规则 | 追加的 `command_line` 特征 |
| --- | --- |
| `msbuild_inline_task_execution` | `\.(xml\|csproj\|proj)\b` 且含 `UsingTask\|Inline\|CodeTaskFactory`，或指向用户可写目录 |
| `msiexec_remote_lolbin` | `/i\s+https?://` 或 `/q`+远程 URL（远程 MSI 才是 LOLBin 滥用） |
| `bitsadmin_download` | `/transfer` 且含 `http` |
| `cmd_powershell_chain` | `cmd` 与 `powershell` 同时出现且含 `-enc\|-e \|/c ` 等链式调用特征 |

**类别 2：无法用参数区分 → 仅降权 + 留待基线**

| 规则 | 处置 |
| --- | --- |
| `remote_desktop_suspicious` | `low` 保持，标注 `_meta.needs_baseline: true`，等 P1-5 资产基线上线后按"该资产是否历史常见"判定 |
| `ws_file_name` | `high` → `medium`，并从 或组中移除过于通用的 `cmd`/`shell` 两项（保留 `b374k\|c99\|r57\|weevely\|chopper\|antsword\|godzilla\|behinder` 等专有 webshell 名） |

**`unsigned_process`（即 `unsigned_executable`）** 已在 §2.1 单独处理。

### 2.7 【P1-5】行为基线存储

`high_connection_count` / `network_scan_behavior` / `time_cluster_burst` / `data_compression_exfil` 等规则使用**全局固定阈值**，对"一台正常的开发机"和"一台内网跳板机"用同一把尺子，必然两头不讨好。

**本阶段范围界定（重要）**：P1-5 只做**基础设施骨架**，不做完整的基线自适应判定。理由是基线需要历史数据积累周期，在数据不足时启用自适应反而比固定阈值更不可控。

P1 交付：

1. **`behavior_baselines` 表**（幂等迁移）：

   | 列 | 类型 | 说明 |
   | --- | --- | --- |
   | `id` | INTEGER PK | |
   | `scope_type` | TEXT | `host` / `user` / `global` |
   | `scope_key` | TEXT | host_id 或 用户名；`global` 时为 `*` |
   | `metric` | TEXT | 指标名，如 `connection_count` |
   | `window` | TEXT | 统计窗口，如 `1h` / `1d` |
   | `sample_count` | INTEGER | 样本数（低于阈值时基线不可信） |
   | `mean` / `stddev` / `p95` / `max_value` | REAL | 统计量 |
   | `updated_at` | TEXT | |

   唯一索引：`(scope_type, scope_key, metric, window)`。

2. **`BehaviorBaseline` 模型**：`upsert()` / `get()` / `list_by_scope()` / `is_reliable()`（`sample_count >= MIN_SAMPLES` 才算可信，默认 7）。

3. **规则侧接口预留**：`condition` 支持可选 `baseline: {metric, window, sigma}`。引擎读取基线——**基线不可信时回落到固定 `value`**，保证零行为变更。

P2/P3 再接入实际计算任务与规则切换。**本阶段不改变任何现有规则的判定结果**。

---

## 3. 影响面与兼容性

| 改动 | 影响 | 兼容性 |
| --- | --- | --- |
| `_match_unsigned_exe` 三态语义 | 该规则告警量 541 → 预计 0（数据补齐前） | 行为变更，但方向是消除 100% 误报，属修复 |
| 系统目录白名单扩充 | 减少误报 | 纯收敛 |
| 4 条 behavior 规则下线 | 告警量不变（本就恒不命中） | 无 |
| 2 条重复规则下线 | 重复告警减半 | 风险评分会下降，需在验证文档中说明属预期 |
| 攻击链 `ordered` 语义 | 2 条链从"不可达"变为"可达" | 新增告警可能性；已有链行为不变（其余 8 条全为 process/connection 维度，均 `ordered=False`，索引约束放宽后**匹配更宽松**，需重点回归） |
| 4 条规则 regex → composite | 告警量下降 | 需验证真实攻击样本仍能命中 |
| `behavior_baselines` 表 | 仅建表 | 零行为变更 |

> **最高风险点**：§2.5 的 `ordered` 改造会放宽 8 条现存攻击链的索引约束，可能引入新的误报。必须在测试环节对全部 10 条链做前后对比回归。

---

## 4. 验收标准

- **AC-P1-1** `unsigned_executable` 对 `exe_is_signed is None` 的进程不再命中；对 `exe_is_signed=0` 的进程仍命中
- **AC-P1-2** `TrustedInstaller.exe` / `TiWorker.exe` 等 WinSxS/servicing 路径进程不再命中
- **AC-P1-3** 真实库 541 条非系统目录进程的 `unsigned_exe` 命中数由 541 降至 0
- **AC-P1-4** 4 条依赖 `memory_sections`/ETW 的规则 `enabled=false` 且含 `disabled_reason`
- **AC-P1-5** `credential_dump` 与 `dll_sideload` 各自仅剩 1 条 enabled
- **AC-P1-6** 同一份输入数据不再产生语义重复的双告警
- **AC-P1-7** `attack_chain_default_c2_persistence` 在含 registry 事件的数据上**可达**（前置：导入 IOC）
- **AC-P1-8** `attack_chain_webshell_certutil` 同上
- **AC-P1-9** 其余 8 条攻击链改造前后命中结果**完全一致**（无回归）
- **AC-P1-10** 6 条 `field=name` 规则均已降权或复合化，无一保持"裸进程名 + high"
- **AC-P1-11** `ws_behinder_godzilla` 不再对含 `1` 的任意文本命中
- **AC-P1-12** `behavior_baselines` 表创建成功且迁移幂等（重复执行不报错）
- **AC-P1-13** 严重度分布中 high 占比由 62.8% 下降（目标 ≤ 55%）
- **AC-P1-14** P0 的 68 条用例与 P1 新增用例全绿，存量回归无新增失败

---

## 5. 不做的事（Non-Goals）

1. **不补采集器**。`memory_sections`、ETW、`file_hashes` 全量覆盖属 P3-2 与 Agent 侧工作，本阶段只做"诚实标注"。
2. **不实现基线自适应判定**。仅建表与预留接口，避免在样本不足时引入更不可控的行为。
3. **不删除任何规则**。一律 `enabled:false` + 原因标注，保留可追溯性与复活路径。
4. **不引入外部情报源**。实时 TI 属 P3。
5. **不修改 Agent 端代码**。P1 全部改动限于 `backend/`。
