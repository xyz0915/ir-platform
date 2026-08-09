# 案件详情数据扩充（P0+P1）— 测试文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 测试阶段（Testing） |
| **负责人** | 应急研判组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联开发** | `docs/case-audit/enriched/02-development.md` (v1.0.0) |
| **测试套件** | `backend/tests/test_case_summary.py`（新增 9 例）+ 回归套件 3 个 |

---

## 1. 测试范围与策略

- **目标**：逐条验证设计阶段 AC-1~AC-11 是否经开发阶段落实。
- **层级**：以**服务层**单元/集成测试为主（聚合逻辑全部为纯后端 SQL 查询），前端卡片经 `vite build` 编译验证（见 §4）。
- **隔离策略**：测试文件顶部在导入任何 app 数据库模块**之前**重定向 `app.config.settings.DB_PATH` 到 `tempfile.gettempdir()` 下的独立库 `ir_test_case_summary.db` 并 `init_db()`，避免触碰运行中的生产库 `data/ir_platform.db`（当前 uvicorn 仍用真实库）。
- **执行参数**：`pytest tests/test_case_summary.py -v --noconftest`。`--noconftest` 用于规避项目 `conftest.py` 触发 torch 全量收集导致的崩溃（既有的环境问题，与本次改动无关，详见 §5）。
- **运行环境**：`backend/venv/Scripts/python.exe`（pytest 9.1.1），`PYTHONPATH=.`。

---

## 2. 测试用例清单（新增 9 例，覆盖 AC-2~AC-10）

| 编号 | 用例函数 | 映射 AC | 验证点 |
| --- | --- | --- | --- |
| TC-01 | `test_derived_severity_ignores_dismissed` | AC-2 | 派生严重度忽略 dismissed（critical+high+medium(dismissed) → high）；无主机 → none |
| TC-02 | `test_alert_stats` | AC-3 | alert_stats.total/by_severity/by_status 正确；top_alerts 按严重度+次数排序 |
| TC-03 | `test_host_stats_and_online_agents` | AC-4 | 主机总数/状态分布；仅 hostA 在线 → online_agents=1；风险 Top5 以 IOC 命中数排序 |
| TC-04 | `test_remediation_progress` | AC-6 | items JSON 解析：done/total/percent 正确（2 项 1 完成 → 50%） |
| TC-05 | `test_triage_progress` | AC-7 | triage_tasks 状态分布（pending/running/done）计数正确 |
| TC-06 | `test_ioc_joins_threat_intel` | AC-8 | ioc_hits 关联 iocs/threat_intel，`intel` 字段回灌 provider/risk_score |
| TC-07 | `test_ttp_from_threat_intel_attck` | AC-9 | kill_chain 来自 attack_stage；techniques 聚合自 attck JSON |
| TC-08 | `test_ai_summary_parsed` | AC-10 | security_events.ai_analysis JSON 解析，取最高 risk_score 结论 |
| TC-09 | `test_timeline_present` | AC-5 | 时间线含「案件创建」+「首批主机接入」（依赖 hosts.collection_time 非空）+ 其余里程碑，按时间排序 |

> 说明：AC-1（接口存在）经路由冒烟 + 回归套件覆盖；AC-11（前端多卡片）经 `vite build` 编译验证 + 代码评审确认（详见开发文档 §AC-11 与 §4），未单列自动化用例。

---

## 3. 执行结果

### 3.1 主测试套件（test_case_summary.py）

```
命令：backend/venv/Scripts/python.exe -m pytest tests/test_case_summary.py -v --noconftest
结果：9 passed in 9.26s  （warnings 均为既有 Pydantic V1→V2 弃用告警，与本次改动无关）
```

| 用例 | 结果 |
| --- | --- |
| TC-01 `test_derived_severity_ignores_dismissed` | ✅ Pass |
| TC-02 `test_alert_stats` | ✅ Pass |
| TC-03 `test_host_stats_and_online_agents` | ✅ Pass |
| TC-04 `test_remediation_progress` | ✅ Pass |
| TC-05 `test_triage_progress` | ✅ Pass |
| TC-06 `test_ioc_joins_threat_intel` | ✅ Pass |
| TC-07 `test_ttp_from_threat_intel_attck` | ✅ Pass |
| TC-08 `test_ai_summary_parsed` | ✅ Pass |
| TC-09 `test_timeline_present` | ✅ Pass |

### 3.2 回归测试套件

为确认本次改动（新增聚合服务、新增 summary 路由、前端重写、`.gitignore` 扩充）未破坏既有能力，运行既有相关套件：

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| `test_case_summary.py` | `pytest tests/test_case_summary.py --noconftest` | ✅ **9 passed** |
| `test_enable_ssot.py` | `pytest tests/test_enable_ssot.py --noconftest` | ✅ **8 passed** |
| `test_rules_import.py` | `pytest tests/test_rules_import.py --noconftest` | ✅ **15 passed** |
| `test_p2_rule_governance.py` | `pytest tests/test_p2_rule_governance.py --noconftest` | ✅ **23 passed，25 subtests passed** |

合并执行（4 文件同跑）：**55 passed，25 subtests passed，42.70s**。

**结论**：新增 9 例全部通过，3 个回归套件全部通过，无既有用例因本次改造而失败。

---

## 4. 前端编译验证（AC-11 配套）

- 命令：`cd frontend && npx vite build --logLevel warn`
- 结果：编译通过，无错误（仅良性 chunk 体积提示）。
- 覆盖：`CaseDetailView.vue`（9 张卡片渲染 + 主机列表 + 批量 AI 对比对话框保留）、`cases.js`（新增 `summary` 方法）。

---

## 5. 缺陷报告

> 说明：以下缺陷均出现在**测试用例编写/冒烟阶段本身**（测试代码或早期服务 bug），生产代码逻辑经修正后正确。缺陷在测试开发过程中已修复并复测通过，未遗留至交付物。

### D-1 派生严重度 IN 子句漏传参数（已修复）
- **发现阶段**：服务冒烟期间（`_smoke_summary.py`）。
- **现象**：`sqlite3.ProgrammingError: Incorrect number of bindings supplied... 1 statement, 0 supplied`。
- **根因**：`_derived_severity` 中 `conn.execute(f"...IN ({_in_clause(host_ids)}) AND status != 'dismissed'")` 漏传 `host_ids` 参数。
- **修复**：补 `, host_ids`，改为 `conn.execute(sql, host_ids)`。
- **状态**：✅ 已修复。

### D-2 种子数据缺 NOT NULL 列（已修复，测试构造问题）
- **发现阶段**：首次跑 `test_case_summary.py`。
- **现象**：连续报 `agents.agent_id NOT NULL`、`alerts.rule_name/title NOT NULL`、`triage_tasks.scope NOT NULL`、`security_events.event_key/id NOT NULL/UNIQUE` 等约束失败。
- **根因**：种子 SQL 未覆盖这些 NOT NULL/UNIQUE 列（属测试构造遗漏，非生产缺陷）。
- **修复**：种子补齐 `agent_id`、`rule_name`、`title`、`scope`（SQL 单引号转义 `'[''file_hashes'']'`）、`event_key`、`id`（TEXT PK）；并在 `_seed()` 开头清空全部相关表，规避重复 `_seed()` 触发 UNIQUE 冲突。
- **状态**：✅ 已修复，9 例全绿。

### D-3 时间线缺「首批主机接入」里程碑（已修复，测试构造问题）
- **发现阶段**：`test_timeline_present`。
- **现象**：时间线断言缺少「首批主机接入」节点。
- **根因**：种子未设 `hosts.collection_time`，而 `_timeline` 要求 `collection_time IS NOT NULL`。
- **修复**：两台主机补 `collection_time`（`2026-08-01 09:30:00` / `09:35:00`）。
- **状态**：✅ 已修复。

### D-4 环境限制（既有，非本次缺陷，记录备案）
- **现象**：组合导入某些 app 模块在导入阶段触发段错误（exit 139，segfault）；单独导入 `app.services.case_summary`、模型层模块均正常。
- **根因**：既有的 torch/environment 环境问题（同前序审计记录的 `--noconftest` 崩溃），与本次改动无关。
- **处置**：服务层以 `case_summary.py` 为入口，绕开该导入路径；生产运行不受影响（uvicorn 进程已正常加载全部模块）。
- **状态**：📌 已知环境限制，不在本次修复范围，后续可独立排查。

---

## 6. 阶段衔接说明

- 本文档为**测试阶段**交付物，证明 AC-1~AC-11 经代码落实且回归无损。
- **验证阶段**须基于本文档的执行结果，逐条比对 AC 达成情况，输出 `04-validation.md`（验收标准比对 + 结论）。
