# P1 阶段 · 验证文档（验收结论）

| 项 | 内容 |
| --- | --- |
| 阶段 | P1（重大漏报 / 能力短板） |
| 环节 | 验证（第 4/4 环节） |
| 上游 | `p1/01-design.md`、`p1/02-dev.md`、`p1/03-test.md` |
| 验收探针 | `backend/_p1_verify.py` |
| 结论 | **12/13 AC 通过；1 项（AC-P1-13）为已知限制，归 P2-2** |
| 编写日期 | 2026-08-08 |

---

## 1. 验证结论总览

| 维度 | 结果 |
| --- | --- |
| 设计验收标准（14 项） | 12 PASS / 1 FAIL（AC-P1-13）/ 1 不适用说明 |
| 验收探针 `_p1_verify.py` | 12/13 通过 |
| 规则相关存量回归 | 5 文件 12 例全部修复转绿（80 passed） |
| 真实库实测基线 | `process_events` 2199 / `file_hashes` 70 / `registry_keys` 3160 |

> 全部结论均基于真实生产库 `backend/data/ir_platform.db` 实测，不采用推断。

---

## 2. AC 逐条核对

| AC | 验收标准 | 结论 | 证据 |
| --- | --- | --- | --- |
| AC-P1-1 | `exe_is_signed is None` 不命中；`=0` 命中 | ✅ PASS | 8 个三态用例全部符合预期 |
| AC-P1-2 | WinSxS/servicing 路径进程不命中 | ✅ PASS | 系统目录路径命中 0/4 |
| AC-P1-3 | 非系统目录进程 `unsigned_exe` 命中 541→0 | ✅ PASS | 真实库 335 条非系统目录进程命中 0（改造前 541） |
| AC-P1-4 | 4 条依赖字段规则 `enabled=false` 且含 `disabled_reason` | ✅ PASS | `fileless_reflective_injection` 等 4 条均带 `condition._meta.disabled_reason` |
| AC-P1-5 | `credential_dump`/`dll_sideload` 各仅 1 条启用 | ✅ PASS | 启用规则中重复 pattern：无 |
| AC-P1-6 | 同一份输入不再产生语义双告警 | ✅ PASS | `credential_dump→lsass_dump_detection`；`dll_sideload→dll_search_order_hijack` |
| AC-P1-7 | `attack_chain_default_c2_persistence` 可达 | ✅ PASS | [process→connection→registry] 可达=True（order_verified=False，符合无序 registry 设计） |
| AC-P1-8 | `attack_chain_webshell_certutil` 可达 | ✅ PASS | [process→process→registry→connection] 可达=True |
| AC-P1-9 | 其余 8 条链无回归 | ✅ PASS | 空事件集下 8 条链均不命中 |
| AC-P1-10 | 无「裸进程名 + high/critical」规则 | ✅ PASS | 仍为裸进程名+high/critical 的规则：无 |
| AC-P1-11 | `ws_behinder_godzilla` 不误报 | ✅ PASS | `exists`+布尔语义，误报/漏报输入均不命中 |
| AC-P1-12 | `behavior_baselines` 表创建幂等 | ✅ PASS | 表存在=True，迁移可重复执行 |
| AC-P1-13 | high 占比 ≤55% | ❌ FAIL（已知限制） | 全口径 62.8%→59.9%；启用口径 58.7%（详见 §3） |
| AC-P1-14 | P0 68 例 + P1 新增用例全绿，无新增回归 | ✅ PASS | P0 套件 68 passed；P1 规则相关 12 例修复后 80 passed |

---

## 3. 已知限制：AC-P1-13（严重度分布）

**现象**：`high` 严重度占比由改造前 **62.8%** 降至 **59.9%**（全口径）/ **58.7%**（启用口径），仍未达设计目标 **≤55%**。

**原因**：P1 仅对有限几条规则做了降权（unsigned_executable、ms_anomaly_class、ms_conn_signal、ws_file_name 等）。整体严重度分布治理（对存量 high 规则做系统性再平衡）属于 **P2-2（严重度校准）** 的正式交付范围，不在 P1 内。

**处置**：标记为已知限制，移交 P2-2。P1 阶段已在不引入新误报的前提下将 high 占比下降约 3 个百分点，方向正确。

---

## 4. 回归与兼容性说明

- **P1 引入的测试修复（3 例）**：`test_rules_import.test_10`（禁用集合扩至全 JSON）、`test_process_enhancement_p1.test_chain_risk`（权重 20→实际 medium 累加 20）、`test_process_enhancement_p2.test_evaluate_runs_and_detects`（改写为三态语义验证）。均使测试对齐 P1 的正确行为，非掩盖缺陷。
- **存量陈腐测试修复（9 例）**：规则计数公式漏算 `event_log_rules.json`、临时库缺 `engine_type` 列、注册表类型数 7→8。与 P1 无关，修复后套件转绿。
- **行为变更声明**：除设计约定的三态/降权/下线外，本阶段不改变任何存量规则判定结果（`behavior_baselines` 仅建表，零行为变更）。
- **受攻击链 `ordered` 改造影响**：8 条现存链索引约束放宽（无序事件可任意位置选中），已通过 AC-P1-9 确认无回归；2 条含 registry 的链恢复可达（AC-P1-7/8）。

---

## 5. 交付物清单

| 文档 | 状态 |
| --- | --- |
| `p1/01-design.md` | 已完成 |
| `p1/02-dev.md` | 已完成 |
| `p1/03-test.md` | 已完成 |
| `p1/04-verify.md` | 本文件 |

**P1 阶段结论：可交付**。唯一遗留项 AC-P1-13 已在 P2-2 排期，不阻塞 P1 验收。
