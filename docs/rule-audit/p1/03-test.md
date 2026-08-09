# P1 阶段 · 测试文档（测试用例与结果）

| 项 | 内容 |
| --- | --- |
| 阶段 | P1（重大漏报 / 能力短板） |
| 环节 | 测试（第 3/4 环节） |
| 上游 | `p1/01-design.md`、`p1/02-dev.md` |
| 验收探针 | `backend/_p1_verify.py`（只读真实库 `ir_platform.db`） |
| 存量套件回归 | 5 个规则相关测试文件（12 例）经修复后全绿 |
| 编写日期 | 2026-08-08 |

---

## 1. 测试目标

P1 解决的是「命中了也没用」——误报、漏报、重复命中。测试必须验证：

1. **三态正确**：`exe_is_signed` 为 `None`（未知）时不命中，`0`（明确未签名）时命中——既不误报（unknown≠guilty），也不漏报。
2. **诚实下线**：依赖未采集字段的规则被 `enabled:false` 且带 `disabled_reason`，不删库、可追溯。
3. **去重复**：同一 pattern 不再产生语义双告警。
4. **攻击链可达**：修复排序/贪心缺陷后，含 `registry` 收尾的 2 条链可达，其余 8 条链无回归。
5. **regex 治理**：宽泛正则改为 `composite`/`exists` 后，真实攻击样本仍可命中，正常样本不再误报。
6. **基线骨架**：`behavior_baselines` 表创建幂等。

---

## 2. 测试环境

| 项 | 值 |
| --- | --- |
| OS | Windows |
| Python | 3.13.12（`backend/venv`） |
| 数据库 | 真实库 `backend/data/ir_platform.db`（探针只读，不改写） |
| 验收探针 | `backend/_p1_verify.py`（覆盖 14 项 AC 中的 13 项可自动化项） |

执行命令：

```bash
cd backend
./venv/Scripts/python.exe _p1_verify.py
```

---

## 3. 验收探针 `_p1_verify.py`（13 项可自动化 AC）

逐条核对设计文档 §4 验收标准；AC-P1-13（严重度分布）为统计项，单独记录。

| AC | 验证点 | 探针结果 |
| --- | --- | --- |
| AC-P1-1 | `exe_is_signed is None` 不命中；`=0` 仍命中（8 个三态用例） | PASS |
| AC-P1-2 | `TrustedInstaller.exe`/`TiWorker.exe` 等 WinSxS/servicing 路径命中 0/4 | PASS |
| AC-P1-3 | 真实库 335 条非系统目录进程 `unsigned_exe` 命中 0（改造前 541） | PASS |
| AC-P1-4 | 4 条依赖字段规则 `enabled=false` 且含 `disabled_reason` | PASS |
| AC-P1-5 | 启用规则中重复 pattern：无 | PASS |
| AC-P1-6 | `credential_dump`→仅 `lsass_dump_detection`；`dll_sideload`→仅 `dll_search_order_hijack` | PASS |
| AC-P1-7 | `attack_chain_default_c2_persistence` [process→connection→registry] 可达 | PASS |
| AC-P1-8 | `attack_chain_webshell_certutil` [process→process→registry→connection] 可达 | PASS |
| AC-P1-9 | 其余 8 条链空事件集下均不命中（无回归） | PASS |
| AC-P1-10 | 仍为「裸进程名 + high/critical」的规则：无 | PASS |
| AC-P1-11 | `ws_behinder_godzilla`（`exists`+布尔语义）不再对含 `1` 的任意文本命中 | PASS |
| AC-P1-12 | `behavior_baselines` 表存在且迁移幂等 | PASS |
| AC-P1-13 | high 占比 全口径 62.8%→59.9% / 启用口径 58.7%（目标 ≤55%） | **FAIL（已知限制，归 P2-2）** |

**合计：12/13 通过。**

---

## 4. 存量测试套件回归（本阶段修复）

全量回归曾报告 17 个文件失败，其中 5 个规则相关文件共 12 例。经甄别：

- **3 例为 P1 引入**（测试须对齐 P1 的正确行为），**9 例为存量测试陈腐**（与 P1 无关，属其他未提交改动引入的漂移），均安全修复使套件转绿。

### 4.1 P1 引入的测试修复

| 文件 / 用例 | 修复 |
| --- | --- |
| `test_rules_import.py::test_10_disabled_rules_match_json` | 原仅读 `default_rules.json` 比对禁用集合；改为 glob `app/rules/` 全部 `*.json`（与 loader 一致），正确纳入 P1-1-B 在 `process_enhancement_rules.json` 下线的 5 条规则 |
| `test_process_enhancement_p1.py::test_chain_risk_accumulates_across_nodes` | `unsigned_executable` 严重度 `high→medium`（权重 25→10），链路累加期望由 `40` 修正为 `20` |
| `test_process_enhancement_p2.py::test_evaluate_runs_and_detects` | 原断言「缺失 `exe_is_signed` → 命中」是 P1-1-A 修正前的旧行为。改为：①管线层对未知态返回 0（不误报）；②在 matcher 层直接验证三态（0→命中 / None→不命中 / 1+有效 signer→不命中） |

### 4.2 存量陈腐测试修复（非 P1，转绿用）

| 文件 / 用例 | 根因 | 修复 |
| --- | --- | --- |
| `test_rules_import.py::test_01/05/06` | `EXPECTED_RULE_COUNT` 公式仅统计 4 个 JSON，漏掉 loader 实际加载的 `event_log_rules.json`（6 条），导致 141 vs 实际 147 | `EXPECTED_RULE_COUNT` 改为 glob `app/rules/*.json` 全部数组文件求和（与 loader 行为一致） |
| `test_rule_matcher_behavior_fix.py`（5 例） | 测试临时库 `rules` 表缺 `engine_type` 列，而产品 `_load_rules_by_categories` 已查询该列 | 临时建表补 `engine_type TEXT` 列并补全 INSERT 列 |
| `test_unified_engine.py::test_registered_types_include_all_7` | 引擎现已注册 8 类（新增 `event_log_summary`），原期望 7 类 | 期望集合更新为 8 类，方法改名 `test_registered_types_include_all_8` |

### 4.3 修复后结果

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/test_rules_import.py \
  tests/test_rule_matcher_behavior_fix.py tests/test_process_enhancement_p1.py \
  tests/test_process_enhancement_p2.py tests/test_unified_engine.py -q
# 结果：80 passed
```

> 说明：`test_process_enhancement_p2.py` 另含 `test_evaluate_graceful_no_events`（host 999 无事件返回 `[]` 不抛异常）等用例，均随修复转绿。

---

## 5. 未自动化的 AC 项

- **AC-P1-13（严重度分布）**：属统计/治理项，需对全库 147 条规则做严重度再平衡，正式交付在 **P2-2（严重度校准）**。当前 `high` 占比已由 62.8% 降至 59.9%（启用口径 58.7%），尚未达 ≤55% 目标，标记为已知限制。
- **AC-P1-7/8 的「前置导入 IOC」**：攻击链 `attack_chain_default_c2_persistence` 可达性依赖注入 IOC，探针以构造事件集 + `iocs_by_type` 注入验证，未走完整导入链路（与 P0-1 验证口径一致）。
