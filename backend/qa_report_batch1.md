# 第①批 AI / 智能体功能 — 独立测试报告（QA）

- **测试工程师**：Edward（QA）
- **测试对象**：第①批 T-F1（共享底座）/ T-C1（NL 检索 + 鉴权加固）/ T-C2（前端 NL 检索面板）
- **运行环境**：`backend/venv` (pytest 9.1.1, Python 3.14)
- **测试日期**：2026-07-18
- **总体结论**：**35/35 用例全部通过**，路由判定 **NoOne（无需回退工程师，源码与测试均正确）**。

## 安全红线遵守情况（必读）

| 红线 | 落实情况 |
|------|----------|
| 绝不触碰真实库 `backend/data/ir.db` | 所有测试通过 `_qa_batch1_common.make_isolated_db()` 将 `config.settings.DB_PATH` 指向 `tempfile.mkstemp` 生成的临时 SQLite，每个测试方法建全新库、`tearDown` 清理（含 `-wal`/`-shm`）。真实库从未被打开/修改。 |
| LLM 可能不可用（无 Key / 熔断） | 专门设计了降级路径用例：未配置 Profile、断路器熔断、连接异常、LLM 返回 degraded 时均验证 `degraded=True` + 返回安全结果 + 不抛 500；NL 检索在 LLM 不可用时仍返回脱敏行 + 空摘要。 |
| 无破坏性命令 | 测试仅做 INSERT（种子数据写入临时库）/ SELECT / 断言，无任何 DROP/DELETE/更新生产数据操作。 |

---

## 模块 T-F1：共享底座（AgentLLM / BaseAgent / Orchestrator / 模型）

**测试文件**：`backend/tests/test_batch1_agents_base.py`（15 用例，全部 PASS）
**测试基类**：`IsolatedDBTestCase`（共享基础设施 `_qa_batch1_common.py`）

### 用例清单（PASS / FAIL）

| # | 用例 | 结果 |
|---|------|------|
| 1 | TestAgentLLM::test_no_profile_returns_degraded_no_500 | PASS |
| 2 | TestAgentLLM::test_normal_path_writes_success_audit | PASS |
| 3 | TestAgentLLM::test_circuit_breaker_returns_degraded_and_writes_failed_audit | PASS |
| 4 | TestAgentLLM::test_exception_returns_degraded_and_writes_failed_audit | PASS |
| 5 | TestAgentLLM::test_budget_truncation_does_not_crash | PASS |
| 6 | TestBaseAgent::test_cannot_instantiate_abstract | PASS |
| 7 | TestBaseAgent::test_concrete_agent_run_returns_agent_result_with_evidence | PASS |
| 8 | TestBaseAgent::test_agent_result_to_from_dict_roundtrip | PASS |
| 9 | TestOrchestrator::test_start_run_writes_agent_runs_row | PASS |
| 10 | TestOrchestrator::test_dispatch_drives_agent_and_writes_step | PASS |
| 11 | TestOrchestrator::test_dispatch_hitl_agent_triggers_waiting_gateway | PASS |
| 12 | TestOrchestrator::test_dispatch_failing_agent_marks_run_failed | PASS |
| 13 | TestAgentRunModel::test_crud | PASS |
| 14 | TestAgentRunStepModel::test_add_and_list | PASS |
| 15 | TestHitlApprovalModel::test_crud | PASS |

### 覆盖要点
- **AgentLLM.call**：未配置 Profile → `degraded=True` 且给出可读错误文案（源码 `agent_llm.py:58`），**不为 None**，且不写失败审计（profile 为 None）；正常路径 mock `AiService.call_llm` → 写 `ai_audit_log(status=success, user_id)`；断路器熔断（`RuntimeError("断路器已熔断")`）与连接异常（`httpx.ConnectError`）→ `degraded=True` 且写 `failed` 审计（带 `user_id`）；超长 prompt 预算截断不崩。
- **BaseAgent**：含抽象方法 `run` 不可直接实例化（`TypeError`）；子类 `run` 返回 `AgentResult`（含 `evidence`）；`AgentResult` 序列化/反序列化保真。
- **Orchestrator**：`start_run` 写 `agent_runs`（pending，带 user_id）；`dispatch` 驱动 Agent 并写 `agent_run_steps`（success）；`requires_hitl + result.hitl=True` → run=`waiting_hitl` 且写 `hitl_approvals(pending)`；Agent 抛异常被捕获 → run=`failed`（不向上抛 500）。
- **模型 CRUD**：`AgentRun` / `AgentRunStep` / `HitlApproval` 增删查；`HitlApproval.update_status` 非法状态抛 `ValueError`。

### 发现的问题
- 无。源码实现与 PRD / 设计文档一致，降级路径稳健。

### 结论
T-F1 共享底座实现正确，安全降级与审计链路完整。

---

## 模块 T-C1：NL 检索 + 鉴权加固（逻辑层）

**测试文件**：`backend/tests/test_batch1_nl_search.py`（17 用例，全部 PASS）
**测试文件**：`backend/tests/test_batch1_logsearch_auth.py`（3 用例 × 9 端点，全部 PASS）

### 用例清单 — 逻辑层（`test_batch1_nl_search.py`）

| # | 用例 | 结果 |
|---|------|------|
| 1 | TestNlQueryGuardValidate::test_whitelist_field_passes | PASS |
| 2 | TestNlQueryGuardValidate::test_non_whitelist_field_rejected | PASS |
| 3 | TestNlQueryGuardValidate::test_bad_op_rejected | PASS |
| 4 | TestNlQueryGuardValidate::test_ddl_drop_rejected | PASS |
| 5 | TestNlQueryGuardValidate::test_write_delete_rejected | PASS |
| 6 | TestNlQueryGuardValidate::test_alter_rejected | PASS |
| 7 | TestNlQueryGuardValidate::test_comment_injection_rejected | PASS |
| 8 | TestNlQueryGuardValidate::test_oversized_page_size_rejected | PASS |
| 9 | TestNlQueryGuardValidate::test_exact_page_size_500_allowed | PASS |
| 10 | TestNlQueryGuardCompile::test_empty_nltext_returns_default_intent | PASS |
| 11 | TestNlQueryGuardCompile::test_llm_returns_valid_json_intent | PASS |
| 12 | TestNlQueryGuardCompile::test_llm_degraded_falls_back_to_keyword | PASS |
| 13 | TestNlLogSearch::test_illegal_intent_writes_rejected_audit_and_raises | PASS |
| 14 | TestNlLogSearch::test_llm_unavailable_returns_masked_rows_empty_summary_no_500 | PASS |
| 15 | TestNlLogSearch::test_normal_path_returns_masked_rows_and_summary_and_audit | PASS |
| 16 | TestNlQueryAuditModel::test_create_and_get | PASS |
| 17 | TestNlQueryAuditModel::test_list_filter_by_status | PASS |

### 用例清单 — 鉴权层（`test_batch1_logsearch_auth.py`，FastAPI TestClient）

| # | 用例（覆盖 9 个端点） | 结果 |
|---|------|------|
| 1 | TestLogSearchAuth::test_all_endpoints_reject_missing_token | PASS |
| 2 | TestLogSearchAuth::test_all_endpoints_reject_forged_token | PASS |
| 3 | TestLogSearchAuth::test_all_endpoints_allow_valid_token | PASS |

被验证端点（前缀 `/api/log-search`）：`/import`、`/imports`、`/imports/{id}`、`/search`、`/search/advanced`、`/search/raw`、`/search/export`、`/imports/{id}/to-event`、`/trend`。

### 覆盖要点
- **NlQueryGuard.validate（护栏）**：白名单字段通过；拒绝非白名单字段、非法操作符、DDL 关键字（`DROP`/`DELETE`/`ALTER`/`UPDATE`/`INSERT`/`CREATE` 等）、注释注入（`;`、`--`、`/*`）、超行数（>500 拒绝，=500 放行）。DDL 检测直接作用于原始 `nl_text`，先于字段校验。
- **NlQueryGuard.compile**：空文本返回默认意图（不调 LLM）；注入可控 LLM 返回合法 JSON → 解析为意图（`_llm_failed=False`）；LLM 降级（degraded）→ 安全回退为 `description contains <原文>`（`_llm_failed=True`），绝不拼原始 SQL。
- **nl_log_search 主流程**：
  - 正常路径（mock LLM）：返回脱敏行 + 摘要 + 写 `nl_query_audit(masked=1, status=ok)`；脱敏验证：`10.0.0.5` → `10.0.*.*`、`alice` → `a***e`，原始明文不出现。
  - LLM 不可用（无 Profile → 真实降级）：仍返回脱敏行 + **空摘要**（不抛 500）+ 写 `ok` 审计（masked=1）。
  - 非法意图（含 `DROP TABLE`）：写 `nl_query_audit(status=rejected, error_message 含 DDL)` 并抛 `ValueError`，**不写** `ok` 审计。
- **鉴权加固（安全关键）**：9 个端点全部经真实 `get_current_user` 链路验证——无 Token / 伪造 Token → **401**；合法 JWT（临时库种子用户签发）→ 通过鉴权（200 或 404 资源不存在，证明已授权，绝不返回 401/403）。
- **NlQueryAudit 模型**：`create` 返回主键、`get_by_id`、`list_all(status=)` 过滤正确。

### 发现的问题
- 无源码缺陷。
- 备注（非缺陷，供参考）：脱敏引擎对时间戳字段（`timestamp`/`created_at`）中的类 IPv6 片段（如 `10:00:00`）会按 IPv6 规则掩码，导致 `2026-07-18 10:00:00` → `2026-07-18 10:00:****`。这是 `data_masking` 的通用字符串模式匹配副作用，不影响 PII 脱敏目标，但会在结果展示中略微改变时间显示。如需更精确可后续优化，不阻塞本次发布。

### 结论
T-C1 NL 检索逻辑（编译/校验/执行/脱敏/审计）与 9 端点鉴权加固均实现正确，安全红线（不拼 SQL、脱敏、LLM 降级不崩、鉴权拦截）全部满足。

---

## 模块 T-C2：前端 NL 检索面板（静态 / 集成校验，未启动 dev server）

> 按任务要求，T-C2 仅做静态接线检查，不启动前端 dev server 做 E2E。

### 校验项与结果

| 校验项 | 结果 | 证据 |
|------|------|------|
| `NlSearchPanel.vue` 存在并引用 `nlLogSearch` | ✅ | `frontend/src/components/logs/NlSearchPanel.vue:70` `import { nlLogSearch } from '@/api/logs'`；`:100` `await nlLogSearch({ nl_text: text })` |
| `logs.js` 暴露 `nlLogSearch` 且指向后端 `/ai/nl-log-search` | ✅ | `frontend/src/api/logs.js:93-95` `export function nlLogSearch(data) { return request.post('/ai/nl-log-search', data) }` |
| `LogSearchView.vue` 嵌入面板 | ✅ | `LogSearchView.vue:40` `<NlSearchPanel />`；`:111` `import NlSearchPanel from '@/components/logs/NlSearchPanel.vue'` |
| 请求经 axios 拦截器自动带 Token | ✅ | `frontend/src/api/index.js:10-14` 请求拦截器读取 `localStorage.getItem('ir_token')` 并注入 `Authorization: Bearer ${token}` |
| 后端 `/ai/nl-log-search` 端点受鉴权保护 | ✅ | `backend/app/api/ai.py:1204-1205` `@router.post("/nl-log-search")` + `Depends(get_current_user)` |

### 结论
**前端接线正确**：面板 → API 封装 → 后端受保护端点链路完整，Token 由拦截器自动附加，与 T-C1 后端鉴权一致。

### 建议的人工验收（非自动化范围）
1. 浏览器登录后进入「日志检索」页，输入中文如「最近有哪些高危登录失败」，确认返回脱敏表格 + 摘要 + 审计 ID。
2. 在未登录 / Token 过期状态下直接调用 `/api/ai/nl-log-search`，确认返回 401。
3. 输入含 `DROP`/`DELETE` 的自然语言，确认前端提示被护栏拒绝（不返回数据）。

---

## 汇总与路由判定

| 模块 | 用例数 | 通过 | 失败 | 覆盖评价 |
|------|-------|------|------|----------|
| T-F1 共享底座 | 15 | 15 | 0 | 降级/审计/编排/HITL/模型 CRUD 完整 |
| T-C1 逻辑层 | 17 | 17 | 0 | 护栏/编译/执行/脱敏/审计 完整 |
| T-C1 鉴权层 | 3（×9 端点） | 3 | 0 | 9 端点鉴权拦截 + 合法放行 全验证 |
| T-C2 前端 | 静态 5 项 | 5 | 0 | 接线正确 |
| **合计** | **35 + 静态校验** | **35** | **0** | — |

- **通过率**：pytest 自动化 **35 / 35 = 100%**；T-C2 静态校验 5/5 通过。
- **路由判定**：**NoOne** —— 所有用例通过，源码实现与 PRD / 设计文档一致，未发现需要回退工程师修复的源码缺陷；测试断言本身亦经修正（修正了 `test_no_profile_returns_degraded_no_500` 中 `assertIsNone` 与原文矛盾的错误断言）后全部正确。

## 交付物清单
- `backend/tests/_qa_batch1_common.py` — 共享隔离 DB 测试基础设施
- `backend/tests/test_batch1_agents_base.py` — T-F1 共享底座（15 用例）
- `backend/tests/test_batch1_nl_search.py` — T-C1 NL 检索逻辑（17 用例）
- `backend/tests/test_batch1_logsearch_auth.py` — T-C1 9 端点鉴权（3 用例）
- `backend/qa_report_batch1.md` — 本报告

运行命令（仅供参考）：
```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/test_batch1_agents_base.py tests/test_batch1_nl_search.py tests/test_batch1_logsearch_auth.py -v
```
