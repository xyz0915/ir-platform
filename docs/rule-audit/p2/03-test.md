# P2 测试文档 — 规则库治理与双管道对齐

> 阶段：P2（#105）｜ 环节：测试（03-test）
> 配套文档：01-design.md（设计）· 02-dev.md（开发）· 04-verify.md（验证）

---

## 1. 测试策略

P2 测试分三层：
1. **新增专项套件** `tests/test_p2_rule_governance.py`（23 passed / 25 subtests passed），逐 AC 覆盖 P2-1~P2-4。
2. **存量回归**：规则相关 10 个测试文件定向回归（绕过 `conftest.py` 的 torch 原生崩溃，见 §4），确认 P2 改动不破坏既有行为。
3. **探针复跑**：`_p1_verify.py` 复跑确认 AC-P1-13 闭合（13/13）。

---

## 2. 专项套件逐 AC 结果（`test_p2_rule_governance.py`）

| AC | 用例（节选） | 验证点 | 结果 |
|---|---|---|---|
| AC-P2-1 | `test_c2_ssot_file_exists_and_parses` | `c2_ports.json` 含 high/low 端口，且引擎装载全集 == SSOT | PASS |
| AC-P2-2 | `test_engine_c2_matches_ssot` | `rule_engine._C2_PORTS` 与 `c2_ports.json` 一致 | PASS |
| AC-P2-3 | `test_c2_ssot_fallback_on_missing_file` | 文件缺失时回退内置集合、不抛异常 | PASS |
| AC-P2-4 | `test_c2_ssot_refresh_clears_cache` | `_refresh_c2_ports()` 清空缓存后重载 | PASS |
| AC-P2-5 | `test_old_c2_port_rules_removed` | `c2_port_*` 6 条已移除、无残留 | PASS |
| **AC-P2-6** | `test_merged_c2_rules_reflect_ssot` | 新 2 条 `c2_suspicious_port_*` values == SSOT high/low | **PASS** |
| AC-P2-7 | `test_p1_probe_high_ratio_closed` | `_p1_verify` 口径含 `default_attack_chain.json`，high% ≤ 55% | PASS |
| AC-P2-8 | `test_critical_rules_marked_requires_hitl` | 9 条 critical 规则 `requires_hitl=true` 且 enabled | PASS |
| AC-P2-9 | `test_loader_report_structure` | `LoadReport` 字段齐全、`summary_line` 格式化 | PASS |
| AC-P2-10 | `test_loader_silences_nonarray_skip` | 非数组 JSON 计入 `skipped`、不告警 | PASS |
| **AC-P2-11** | `test_ac_p2_11_orphans_reported_not_deleted` | `P0-1-TAMPER` 孤儿被识别、`preserved>=1`、不被删除 | **PASS** |
| AC-P2-12 | `test_load_default_rules_backward_compat` | `load_default_rules()` 仍返回列表（向后兼容） | PASS |
| **AC-P2-13** | `test_ac_p2_13_payload_shape_compatibility` | `extract_event_summary` 三种真实载荷形态正确 | **PASS** |
| AC-P2-13b | `test_ac_p2_13b_malformed_payload_degrades_safely` | 畸形载荷（None/空/字符串/非 dict）返回 `{}` 不抛 | PASS |
| AC-P2-14 | `test_ac_p2_14_evaluate_degrades_without_rules` | 空 summary / 空规则返回 `[]` | PASS |
| AC-P2-14b | `test_ac_p2_14b_evaluate_matches_builtin_rules` | 4662 DCSync 阈值≥1 端到端命中 | PASS |

> 失败史（已修复，留痕）：首轮 3 failed ——
> - `test_ac_p2_11`：`preserved` 原仅统计"与默认 JSON 同名"的用户规则，漏算独立用户规则 → 修正 `database.py` 改为统计全部 `source='user'` 行。
> - `test_ac_p2_13` / `13b`：测试误用私有函数名 `_extract_event_summary`，真实导出为 `extract_event_summary`；且"形态 3"假设了不存在的 `{"security": {...}}` 嵌套，改为真实支持的裸计数字典形态。修复后全绿。

---

## 3. P2-4 桥接链路测试覆盖

`TestP2DualPipelineContract` 覆盖：
- 单对象 / 列表包裹 / 裸计数字典三种 `event_ids_summary` 抽取形态（对齐 `extract_event_summary` 实际契约）。
- 畸形载荷降级（6 种边界输入均返回 `dict`，不抛）。
- `evaluate_summary` 在无规则 / 空 summary / `None` 时优雅返回 `[]`。
- 端到端：`{"4662": 1}` 经内置规则命中 DCSync 阈值（≥1）。

结论：P0-2 桥接层契约完整、可降级，**无需额外代码改动**。

---

## 4. 存量定向回归（无 conftest torch 崩溃）

全量 `tests/` 收集因 `tests/conftest.py` 加载 `agent_test_utils → agent_llm → ai_service → sentence_transformers → torch` 触发 **Windows 原生 access violation**（预存环境问题，与 P2 无关，非本次引入）。

采用 `--noconftest` 对规则相关 10 个文件定向回归：

```
tests/test_rules_import.py
tests/test_rule_matcher_behavior_fix.py
tests/test_unified_engine.py
tests/test_process_enhancement_p0.py
tests/test_process_enhancement_p1.py
tests/test_process_enhancement_p2.py
tests/test_process_detection.py
tests/test_attack_chain.py
tests/test_p2_rule_governance.py
tests/test_rule_engine_feedback.py
```

**结果：163 passed, 53 subtests passed（279.98s），零回归。**

含义：P2-1（SSOT / 规则合并）、P2-2（HITL 元数据）、P2-3（loader / database 孤儿检测）均未破坏规则引擎、攻击链、进程增强、IOC 等既有行为。

---

## 5. 探针复跑（AC-P1-13 闭合确认）

`_p1_verify.py`（口径已修正为含 `default_attack_chain.json`）：

```
AC-P1-13 high 占比：53.8%  ≤ 55%  → PASS
总体：13/13 通过
```

---

## 6. 修复后累计测试状态

| 套件 | 结果 |
|---|---|
| `test_p2_rule_governance.py`（新增） | 23 passed / 25 subtests passed |
| 规则相关 10 文件定向回归 | 163 passed / 53 subtests passed |
| P1 验收探针 `_p1_verify.py` | 13/13 PASS |
| P0 验收探针（前序） | 10/10 PASS |

结论：**P2 测试全部通过，无回归，可进入验证环节。**
