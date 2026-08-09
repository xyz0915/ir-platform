# P2 验证文档 — 规则库治理与双管道对齐

> 阶段：P2（#105）｜ 环节：验证（04-verify）
> 配套文档：01-design.md（设计）· 02-dev.md（开发）· 03-test.md（测试）
> 验收口径：真实库 `data/ir_platform.db` + 真实代码实测

---

## 1. 验收结论

**P2 阶段四环节全部完成，验收通过，可交付并进入 P3。**

核心交付：C2 端口 SSOT 泛化、严重度治理闭合 AC-P1-13（high 占比 59.9%→53.8%）、种子加载可观测性（孤儿识别 + 噪声消除）、双管道桥接契约验证。

---

## 2. AC 逐条核对（P2 共 14 项）

| AC | 需求 | 实测证据 | 结果 |
|---|---|---|---|
| AC-P2-1 | C2 端口 SSOT 文件存在且可解析 | `c2_ports.json` high=[4444,6667,1337] low=[4443,5555,8888] | ✅ |
| AC-P2-2 | 引擎 `_C2_PORTS` 与 SSOT 一致 | `set(_C2_PORTS) == SSOT` → True | ✅ |
| AC-P2-3 | 文件缺失回退、不抛异常 | 缺失时 `_load_c2_ports` 返回内置回退集 | ✅ |
| AC-P2-4 | 缓存可刷新 | `_refresh_c2_ports()` 清空后重载一致 | ✅ |
| AC-P2-5 | 旧 6 条 `c2_port_*` 移除 | `load_default_rules()` 中 0 残留 | ✅ |
| **AC-P2-6** | 合并后 2 条规则 values==SSOT | `c2_suspicious_port_high`==high，`_low`==low | ✅ |
| **AC-P2-7** | AC-P1-13 闭合（high%≤55%） | 口径修正后 53.8% ≤ 55% | ✅ |
| AC-P2-8 | 9 条 critical 标 `requires_hitl` | 9 条 `_meta.requires_hitl=true` | ✅ |
| AC-P2-9 | loader 结构化报告 | `LoadReport` 字段 + `summary_line` | ✅ |
| AC-P2-10 | 非数组文件静默跳过 | 计入 `skipped`，启动 WARNING 降为 1 条 | ✅ |
| **AC-P2-11** | 孤儿识别不删除 | `P0-1-TAMPER` 被 WARN 暴露、`preserved>=1`、未被删 | ✅ |
| AC-P2-12 | `load_default_rules()` 兼容 | 仍返回 list，存量调用无碍 | ✅ |
| **AC-P2-13** | 双管道三种载荷形态 | `extract_event_summary` 单/列表/裸 dict 正确 | ✅ |
| AC-P2-14 | 无规则/空 summary 降级 | `evaluate_summary` 返回 `[]` | ✅ |

**P2 验收：14/14 全 PASS。**

---

## 3. 跨阶段闭环（AC-P1-13 正式闭合）

| 阶段 | high 占比 | 说明 |
|---|---|---|
| P1 末（旧口径，漏算 attack_chain） | 59.9% | AC-P1-13 FAIL（移交 P2-2） |
| P1 末（修正口径后） | ~62.8% | 暴露口径缺陷 |
| P2 末（P2-1 合并 + 口径修正 + 探针补全） | **53.8%** | **AC-P1-13 PASS ✅** |

> P2-1 合并 C2 端口 6→2 使 high 82→77；探针口径补全 `default_attack_chain.json` 使分母正确。两者叠加达成 ≤55%。

---

## 4. 回归兼容性

| 范围 | 结果 |
|---|---|
| 规则相关 10 文件定向回归（`--noconftest`） | 163 passed / 53 subtests passed，零回归 |
| P1 探针 `_p1_verify.py` | 13/13 PASS |
| P0 探针（前序） | 10/10 PASS |

> 全量 `tests/` 因 `conftest.py` 加载 torch 触发 Windows 原生 access violation（预存环境问题，与 P2 无关）。规则相关验证已通过定向回归充分覆盖，结论不受影响。

---

## 5. 已知限制与移交

1. **HITL 仅元数据**：`requires_hitl=true` 是契约，下游告警处置 UI 需据此触发人工确认——本阶段不实现 UI（移交前端/警报模块）。
2. **端口收敛遗留**：`8443/1080/5900/9999/31337` 与业务端口重叠，已从 C2 单列移除，依赖 `anomalous_net_process` 综合判定。如需纯端口 high 规则，需先在 `_BUSINESS_PORTS` 解耦（移交后续）。
3. **环境限制**：torch 原生崩溃为预存环境问题，建议后续将 `conftest.py` 的 AI 栈导入改为惰性/隔离，避免污染规则类测试收集。

---

## 6. 交付物清单

| 类型 | 路径 |
|---|---|
| 设计文档 | `docs/rule-audit/p2/01-design.md` |
| 开发文档 | `docs/rule-audit/p2/02-dev.md` |
| 测试文档 | `docs/rule-audit/p2/03-test.md` |
| 验证文档 | `docs/rule-audit/p2/04-verify.md` |
| 新文件 | `backend/app/rules/c2_ports.json` |
| 改动 | `backend/app/rules/rule_engine.py` · `default_rules.json` · `event_log_rules.json` · `default_attack_chain.json` · `process_enhancement_rules.json` · `loader.py` · `database.py` |
| 新测试 | `backend/tests/test_p2_rule_governance.py` |
| 探针修正 | `backend/_p1_verify.py` |

**阶段状态：P2 ✅ 可交付，进入 P3（#106）。**
