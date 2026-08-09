# P1 阶段 · 开发文档（实现细节与代码说明）

| 项 | 内容 |
| --- | --- |
| 阶段 | P1（重大漏报 / 能力短板） |
| 环节 | 开发（第 2/4 环节） |
| 上游 | `p1/01-design.md` |
| 下游 | `p1/03-test.md` → `p1/04-verify.md` |
| 编写日期 | 2026-08-08 |

---

## 1. 变更总览

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `backend/app/rules/process_enhancement_rules.json` | 修改 | P1-1-A 严重度/三态声明的 `_meta`；P1-1-B 下线 4 条 behavior 规则；P1-1-C 7 条 regex 治理（→ `composite`/`exists`/降权） |
| 2 | `backend/app/rules/default_rules.json` | 修改 | P1-2 下线 2 条重复 pattern 规则；P1-4 5 条「仅判进程名」规则复合化/降权 |
| 3 | `backend/app/rules/rule_engine.py` | 修改 | `_match_unsigned_exe` 三态语义修正；`_match_exists` 扩展 `expected_value`+`value_type:"bool"`；新增 `_coerce_bool` / `_BOOL_TRUE_TOKENS` / `_BOOL_FALSE_TOKENS` |
| 4 | `backend/app/database.py` | 修改 | 新增 `_create_behavior_baselines_table()` 并在 `init_db` 调用（P1-5） |
| 5 | `backend/app/models/behavior_baseline.py` | **新增** | `BehaviorBaseline` 模型：`upsert/get/list_by_scope/is_reliable/suggest_threshold` |

> 本阶段**不修改任何 Agent 端代码**，全部改动限于 `backend/`；**不改变任何存量规则的判定结果**（除设计明确约定的三态/降权/下线外）。

---

## 2. P1-1-A · `unsigned_executable` 三态语义与白名单

### 2.1 `_match_unsigned_exe` 三态修正（`rule_engine.py:2472`）

修正前 `None` 与 `0` 被同等处理（缺数据即判未签名）。修正后：

```python
exe_is_signed = data_item.get("exe_is_signed")

# 未知态：无 file_hashes 记录 → 不判定（避免「缺数据即告警」）
if exe_is_signed is None:
    return False
# 明确未签名
if exe_is_signed in (0, False, "", "0", "false", "False"):
    return True
# 已签名。仅当采集器显式回填了空的签名主体时才视为数据异常
if exe_is_signed in (1, True, "1", "true", "True"):
    if "exe_signer" in data_item:
        signer = data_item.get("exe_signer")
        if isinstance(signer, str) and signer.strip() == "":
            return True
return False
```

原则：**未知不等于有罪**（unknown ≠ guilty）。`exe_is_signed=1` 且 `exe_signer` 键缺失/为 `None` 不再误判为未签名，仅当 `exe_signer` 键**显式存在且为空串**才视为数据异常命中。

### 2.2 系统目录白名单扩充

`_SIGNED_SYSTEM_DIRS` 由原先仅含 `system32/syswow64/program files(x86)` 扩充至新增 `c:\windows\winsxs`、`c:\windows\servicing`、`c:\windows\microsoft.net`、`c:\windows\assembly`，覆盖 `TrustedInstaller.exe` / `TiWorker.exe` 等微软签名组件。

### 2.3 严重度与声明

- `unsigned_executable` 严重度 `high → medium`（无签名本身是弱信号，需与路径/行为组合才有价值）。
- `condition._meta` 新增 `requires_field: "exe_is_signed"`、`requires_source`、`coverage_note`、`severity_changed_at: "P1-1-A"`、`severity_changed_from: "high"`、`severity_change_reason`。

> 注：该规则的 `exe_is_signed` 实际来自 `file_hashes` JOIN 注入（设计意图），当前 `file_hashes` 与 `process_events.process_path` 交集为 0，规则处于**静默状态**，属 P2-3 可观测清单项。详见 `04-verify.md` AC-P1-3。

---

## 3. P1-1-B · 依赖未采集字段的 behavior 规则下线

4 条规则置 `enabled: false`，并保留可追溯信息：

| 规则 | pattern | `condition._meta.disabled_reason` | `depends_on` |
| --- | --- | --- | --- |
| `fileless_reflective_injection` | `memory_injection` | `no_producer_field` | P3-2（memory_sections 采集器） |
| `script_interpreter_memory_pe` | `interpreter_mem_pe` | `no_producer_field` | P3-2 |
| `amsi_etw_tamper` | `etw_amsi_tamper` | `no_event_stream` | P3-2（ETW 事件流） |
| `injection_window_anomaly` | `injection_window` | `no_event_stream` | P3-2（事件流时序） |

每条同时：
- `label` 加后缀 `（已下线·待采集器补齐）`；
- `condition._meta` 含 `disabled_detail`（实测 0/2199 次出现等）、`disabled_reason`、`depends_on`、`disabled_at: "P1-1-B"`。

处置原则（沿用 P0-3）：**下线而非删除**。`revoked_sig` / `malicious_hash_process` 因缺数据时降级 `False`、无副作用而**保留启用**；上述 4 条会让运维误以为已覆盖，必须显式下线标注。

---

## 4. P1-1-C · 宽泛 regex 结构性误报治理（7 条）

| 规则 | 改造前 | 改造后 | 要点 |
| --- | --- | --- | --- |
| `ws_behinder_godzilla` | `regex` 匹配 `(true\|1)` | `exists` + `condition.expected_value: true, value_type: "bool"` | 布尔字段用 regex 是类型误用 |
| `ms_anomaly_class` | `regex` 宽关键词 | `composite`（OR：强特征 MemShell/Godzilla…单独成立；弱特征 AND 佐证信号） | severity `high→medium` |
| `ms_filter_signal` | `regex` 单关键词 | `composite`（AND：动态注册 API + 佐证） | severity `medium→low` |
| `ms_conn_signal` | `regex` `IP:端口` | `composite` 子条件（不再独立告警） | severity `high→low` |
| `ws_suspicious_funcs` | `regex` 宽函数名 | `composite`（Web 目录 + 脚本后缀 + 可疑函数三者同成立） | 从 `ws_webdir_activity` 归并路径条件；移除 `base64_encode`/`preg_replace` |
| `ws_webdir_activity` | `regex` 路径 | **下线**（`enabled:false`，合并入 `ws_suspicious_funcs`） | `condition._meta.disabled_reason: "merged_into_composite"` |
| `ws_file_name` | `regex` 含 `cmd`/`shell` 通用词 | 移除 `cmd`/`shell`，保留 behinder/godzilla/weevely/c99 等专有名 | severity `high→medium` |

`ws_suspicious_funcs` 由 `regex` 改为 `composite`（logic AND：路径为 web 目录 **且** 脚本后缀 **且** `suspicious_funcs` 含危险函数），从 `ws_webdir_activity` 归并路径条件，消除单项误触发。

---

## 5. P1-2 · behavior pattern 重复去重（2 组）

| 保留 | 下线 | `disabled_reason` |
| --- | --- | --- |
| `lsass_dump_detection`（critical） | `credential_dump_behavior`（critical） | `duplicate_pattern`（`duplicate_of: lsass_dump_detection`） |
| `dll_search_order_hijack`（high） | `dll_hijack_behavior`（high） | `duplicate_pattern`（`duplicate_of: dll_search_order_hijack`） |

下线条目补 `_meta.disabled_reason: "duplicate_pattern"` 与 `duplicate_of`，避免同一份数据产生两条语义重复告警（尤其 `critical` 级重复会虚高主机风险评分）。

---

## 6. P1-4 · 「仅判进程名」规则复合化/降权（5 条）

**类别 1：有明确恶意参数特征 → 改 `composite`（进程名 AND 参数特征）**

| 规则 | 追加的 `command_line` 特征 |
| --- | --- |
| `msbuild_inline_task_execution` | `\.(xml\|csproj\|proj)\b` 且含 `UsingTask\|Inline\|CodeTaskFactory`，或指向用户可写目录 |
| `msiexec_remote_lolbin` | `/i\s+https?://` 或 `/q`+远程 URL |
| `bitsadmin_download` | `/transfer` 且含 `http` |
| `cmd_powershell_chain` | `cmd` 与 `powershell` 同时出现且含 `-enc\|-e \|/c ` 链式调用特征 |

**类别 2：无法用参数区分 → 仅降权**

| 规则 | 处置 |
| --- | --- |
| `remote_desktop_suspicious` | 保持 `low`，标注 `_meta.needs_baseline: true`，等 P1-5 资产基线上线后按「该资产是否历史常见」判定 |
| `ws_file_name` | `high→medium`，并从或组移除过通用的 `cmd`/`shell`（见 §4） |

---

## 7. P1-5 · 行为基线存储骨架

### 7.1 `behavior_baselines` 表（`database.py`）

新增 `_create_behavior_baselines_table(conn)`：列含 `scope_type`（host/user/global）、`scope_key`、`metric`、`window`、`sample_count`、`mean`/`stddev`/`p95`/`max_value`、`updated_at`。唯一索引 `idx_behavior_baselines_uniq(scope_type, scope_key, metric, window)` + 索引 `idx_behavior_baselines_metric`。`init_db` 中幂等调用（重复执行不报错）。

### 7.2 `BehaviorBaseline` 模型（`models/behavior_baseline.py`）

- `MIN_SAMPLES = 7`：`is_reliable()` 要求 `sample_count >= 7`（或 `mean` 缺失）才可信。
- `upsert()`：ON CONFLICT 幂等写入。
- `get()` / `list_by_scope()` / `list_by_metric()`：按维度查询。
- `suggest_threshold()`：`mean + sigma*stddev`；`stddev<=0` 时退化为 `max(mean, p95, max_value)`；不可信返回 fallback。

### 7.3 规则侧接口预留

`condition` 支持可选 `baseline: {metric, window, sigma}`。引擎读取基线——**基线不可信时回落到固定 `value`**，保证零行为变更。本阶段仅做基础设施，**不改变任何现有规则的判定结果**；实际计算任务与规则切换留待 P2/P3。

---

## 8. `rule_engine.py` 支撑改动

### 8.1 `_match_exists` 扩展（`expected_value` + `value_type: "bool"`）

- 缺省保持原「存在即真」语义；
- `value_type: "bool"` 时走 `_coerce_bool()` 规范化比较，无法判定→不命中（与「未知不等于有罪」一致）；
- 字面量比较大小写不敏感。

### 8.2 布尔规范化

新增类常量 `_BOOL_TRUE_TOKENS` / `_BOOL_FALSE_TOKENS` 与静态方法 `_coerce_bool(value)`：将 `"true"/"1"/1/...` 规范为三态布尔，无法判定返回 `None`。`ws_behinder_godzilla` 改用 `exists` + `expected_value: true` 后由本方法支撑。

---

## 9. 影响面与兼容性（摘要）

| 改动 | 兼容性 |
| --- | --- |
| `_match_unsigned_exe` 三态 | 行为变更，方向是消除 100% 误报，属修复 |
| 系统目录白名单扩充 | 纯收敛，减少误报 |
| 4 条 behavior 规则下线 | 告警量不变（本就恒不命中），无副作用 |
| 2 条重复规则下线 | 重复告警减半，风险评分预期下降（见 `04-verify.md`） |
| 7 条 regex → composite/exists/降权 | 告警量下降，真实攻击样本仍可命中（探针验证） |
| `behavior_baselines` 表 | 仅建表，零行为变更 |
