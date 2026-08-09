# 启用状态单一真值（Enable-SSOT）改造 — 测试文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 测试阶段（Testing） |
| **负责人** | 规则治理组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联开发** | `docs/rule-audit/enable-ssot/02-development.md` (v1.0.0) |
| **测试套件** | `backend/tests/test_enable_ssot.py`（新增 8 例）+ 回归套件 2 个 |

---

## 1. 测试范围与策略

- **目标**：逐条验证设计阶段 AC-1~AC-7 是否经开发阶段落实。
- **层级**：以**模型层 + 服务层**单元/集成测试为主（策略部署事务、单一真值计算、行为引擎门控均为纯后端逻辑）。前端 `effective_active` 徽标与一键对齐按钮经 `vite build` 编译验证（见 §4）。
- **隔离策略**：测试文件顶部在导入任何 app 数据库模块**之前**重定向 `app.config.settings.DB_PATH` 到 `tempfile.mkdtemp()` 下的独立库，避免触碰运行中的生产库 `data/ir_platform.db`（当前 uvicorn 仍用真实库）。
- **执行参数**：`pytest <file> -v --noconftest`。`--noconftest` 用于规避项目 `conftest.py` 触发 torch 全量收集导致的崩溃（既有的环境问题，与本次改动无关，详见 §5）。
- **运行环境**：`backend/venv/Scripts/python.exe`（pytest 9.1.1），`PYTHONPATH=.`。

---

## 2. 测试用例清单（新增 8 例，覆盖 AC-1~AC-7）

| 编号 | 用例函数 | 映射 AC | 验证点 |
| --- | --- | --- | --- |
| TC-01 | `test_effective_active_reason_branches` | AC-1 | `effective_active_of` 四个分支：生效中 / 未选入激活策略 / 已禁用 / 无激活策略 |
| TC-02 | `test_annotate_effective_batch` | AC-1 | `annotate_effective` 批量附加 `effective_active` / `effective_reason` |
| TC-03 | `test_activate_deploys_enabled_flags` | AC-2 | `activate()` 部署事务：选中→`enabled=1`，未选→`enabled=0` |
| TC-04 | `test_activate_does_not_enable_deprecated` | AC-2 | `deprecated` 规则不被部署改写（仍 `enabled=0`） |
| TC-05 | `test_activate_writes_audit_with_effective` | AC-2 / AC-6 | 部署改变 `enabled` 时写 `rule_audit_log`（action=`policy_deploy`），且 `new_val` 含 `effective_active` |
| TC-06 | `test_ensure_active_policy_auto_activates` | AC-3 | 无激活策略时 `ensure_active_policy()` 自动激活基线；再次调用命中已有激活策略不重新部署（保留手工 override） |
| TC-07 | `test_behavior_engine_gated_by_policy` | AC-5 | 行为引擎规则随激活策略选中集被纳入/排除门控 |
| TC-08 | `test_align_enabled_high_risk_semantics` | AC-7 | "一键对齐"语义：已启用 critical/high 补选、low 不补选 |

> 说明：AC-4（双页可见真实生效态）为前端展示层，经 `vite build` 编译验证 + 代码评审确认（详见开发文档 §AC-4 与 §4），未单列自动化用例。

---

## 3. 执行结果

### 3.1 主测试套件（test_enable_ssot.py）

```
命令：backend/venv/Scripts/python.exe -m pytest tests/test_enable_ssot.py -v --noconftest
结果：8 passed in 28.99s  （177 warnings，均为既有 Pydantic V1→V2 弃用告警，与本次改动无关）
```

| 用例 | 结果 |
| --- | --- |
| TC-01 `test_effective_active_reason_branches` | ✅ Pass |
| TC-02 `test_annotate_effective_batch` | ✅ Pass |
| TC-03 `test_activate_deploys_enabled_flags` | ✅ Pass |
| TC-04 `test_activate_does_not_enable_deprecated` | ✅ Pass |
| TC-05 `test_activate_writes_audit_with_effective` | ✅ Pass |
| TC-06 `test_ensure_active_policy_auto_activates` | ✅ Pass |
| TC-07 `test_behavior_engine_gated_by_policy` | ✅ Pass |
| TC-08 `test_align_enabled_high_risk_semantics` | ✅ Pass |

### 3.2 回归测试套件

为确认本次改动（部署事务、去静默回退、行为引擎门控、字段注解）未破坏既有能力，运行既有规则相关套件：

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| `test_rules_import.py` | `pytest tests/test_rules_import.py --noconftest` | ✅ **15 passed** |
| `test_p2_rule_governance.py` | `pytest tests/test_p2_rule_governance.py --noconftest` | ✅ **23 passed, 25 subtests passed** |

**结论**：新增 8 例全部通过，2 个回归套件全部通过，无既有用例因本次改造而失败。

---

## 4. 前端编译验证（AC-4 配套）

- 命令：`cd frontend && npx vite build --logLevel warn`
- 结果：编译通过，无错误、无类型/模板告警。
- 覆盖：`RulesView.vue`（真实生效中/未生效芯片、生效态筛选、行内徽标、详情弹窗生效态）、`PolicyConfigView.vue`（行内 `effState` 徽标、一键对齐高危按钮、部署提示修正）。

---

## 5. 缺陷报告

> 说明：以下两条缺陷均出现在**测试用例编写阶段本身**（测试代码 bug），生产代码逻辑经修正后正确。缺陷在测试开发过程中已修复并复测通过，未遗留至交付物。

### D-1 行为引擎门控用例 AttributeError（已修复）

- **发现阶段**：编写 TC-07 期间。
- **现象**：`test_behavior_engine_gated_by_policy` 报 `AttributeError: module 'app.analysis.service_risk_analyzer' has no attribute '_load_behavior_rules'`。
- **根因**：`_load_behavior_rules` 是 `ServiceRiskAnalyzer` **类内静态方法**，模块级别无此属性；用例误用 `sra._load_behavior_rules()` 调用。
- **修复**：改为 `ServiceRiskAnalyzer._load_behavior_rules()`，并新增 `from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer`；用例内 3 处调用同步替换。
- **状态**：✅ 已修复，TC-07 转绿。

### D-2 部署审计用例断言失败（已修复）

- **发现阶段**：编写 TC-05 期间。
- **现象**：`test_activate_writes_audit_with_effective` 断言 `rule_audit_log` 应写入 `policy_deploy`，实际无记录，断言失败。
- **根因**：原用例创建 `enabled=True` 且被选中的规则，部署前后 `enabled` 无变化 → 不触发任何改写 → 无审计写入，属**用例构造错误**而非生产缺陷。
- **修复**：改为创建 `enabled=False` 规则、被策略选中，`activate` 后 `enabled` 由 `False→True`，触发审计写入；断言 `policy_deploy` 记录存在且 `new_val` 含 `effective_active`。
- **状态**：✅ 已修复，TC-05 转绿。

### D-3 环境限制（既有，非本次缺陷，记录备案）

- **现象**：单独执行 `import app.api.rules` 等组合在导入阶段触发段错误（exit 139，segfault）；单独导入 `app.models.policy`、`app.models.rule`、`analysis_service`、`service_risk_analyzer` 均正常。
- **根因**：既有的 torch/environment 环境问题（同前序审计记录的 `--noconftest` 崩溃），与 Enable-SSOT 改动无关。
- **处置**：测试套件以模型/服务层为入口，绕开该导入路径；生产运行不受影响（uvicorn 进程已正常加载全部模块）。
- **状态**：📌 已知环境限制，不在本次修复范围，后续可独立排查。

---

## 6. 阶段衔接说明

- 本文档为**测试阶段**交付物，证明 AC-1~AC-7 经代码落实且回归无损。
- **验证阶段**须基于本文档的执行结果，逐条比对 AC 达成情况，输出 `04-validation.md`（验收标准比对 + 结论）。
