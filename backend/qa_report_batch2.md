# 第②批 P0-A 多智能体协同处置闭环 — 独立测试报告

- **QA 工程师**：software-qa-engineer-2（严过关）
- **测试对象**：第②批 P0-A（T-A1 四 Agent + Orchestrator / T-A2 编排 API + HITL / T-A3 前端接线）
- **测试轮次**：Round 1（发现 10 项失败）→ 全部判定为**测试代码 Bug**，自修 → Round 2（回归 39/39 通过）
- **路由判定**：**NoOne（全部通过，无需返工）**

---

## 一、总览

| 指标 | 数值 |
|------|------|
| 总用例数 | 39 |
| 通过 | 39 |
| 失败 | 0 |
| 通过率 | **39/39 = 100%** |
| 估算覆盖率 | 关键路径（闭环主链路 + HITL 安全闸 + LLM 降级）≈ 90%+ |
| 跑批耗时 | ≈ 70s（含隔离库建表 + RAG 降级 keyword 回退） |

**安全红线遵守情况（全部满足）**：
- ✅ 全程使用 `_qa_batch1_common.IsolatedDBTestCase` 隔离临时 SQLite，**绝不触碰** `backend/data/ir.db`（仅 `config.settings.DB_PATH` 被重写为 `tempfile`，每次 `tearDown` 清理文件与 WAL/SHM）。
- ✅ 覆盖 **LLM 不可用路径**：默认无 AI Profile → `AgentLLM` 返回 `degraded=True`，四 Agent 仍基于真实数据产出带 `evidence/confidence` 的输出且不抛 500（已在 Triage/Investigator/Reporter 用例中显式断言 `[LLM 摘要不可用：…]` 标注）。
- ✅ 无任何破坏性命令、未删除任何生产数据。
- ✅ `RootCauseAgent` 懒加载 `try/except` 失败回退 `None` 属**预期设计**（第②批未落地根因 Agent），InvestigatorAgent 已 `if RootCauseAgent is None` 守卫并走本地根因，测试显式验证该回退。

---

## 二、T-A1：四 Agent + Orchestrator（25 用例，全部通过）

**测试文件**：`tests/test_batch2_agents.py`（22 用例）、`tests/test_batch2_orchestrator.py`（3 用例）

### 2.1 DataProvider（4 用例）
| 用例 | 结果 | 说明 |
|------|------|------|
| test_event_and_log_retrieval | PASS | get_event/get_events/get_logs_by_host/get_process_events/get_host 读真实数据；NOPE→None |
| test_enabled_rules_and_hit_summary | PASS | get_enabled_rules 非空；get_rules_hit_summary 命中产出；无规则→空串 |
| test_extract_refs | PASS | event/log/process refs 格式 `security_events.id=SE-1` 等 |
| test_retrieve_cases_returns_empty_on_rag_failure | PASS | RAG 异常（chroma down）降级为空列表，不阻断调查链路 |

### 2.2 TriageAgent（5 用例）
| 用例 | 结果 | 说明 |
|------|------|------|
| test_instantiation_metadata | PASS | name=triage_agent，requires_hitl=False |
| test_run_produces_agent_result_with_evidence | PASS | run() 返回 AgentResult（stage/evidence/confidence） |
| test_llm_unavailable_annotates_marker | PASS | degraded→输出含 `[LLM 摘要不可用：…]` |
| test_llm_available_uses_content | PASS | LLM 正常时采用 LLM content |
| test_run_no_events_returns_zero_confidence | PASS | 无事件→confidence=0.0 |

### 2.3 InvestigatorAgent（3 用例）
| 用例 | 结果 | 说明 |
|------|------|------|
| test_instantiation_and_rootcause_lazy_fallback | PASS | RootCauseAgent 懒加载失败→None（预期设计），本地根因兜底 |
| test_run_produces_timeline_and_local_root_cause | PASS | 构造时间线 + 本地根因，返回 AgentResult |
| test_llm_unavailable_still_produces_output | PASS | degraded 仍产出 |

### 2.4 ResponderAgent（6 用例）
| 用例 | 结果 | 说明 |
|------|------|------|
| test_metadata_requires_hitl | PASS | requires_hitl=True（强制 HITL 网关） |
| test_derive_action_block_ip | PASS | 高严重度外连日志→推导 `block_ip`（8.8.8.8） |
| test_derive_action_isolate_host | PASS | 推导 `isolate_host` |
| test_derive_action_export_report_fallback | PASS | 兜底 `export_report` |
| test_run_writes_responder_action_and_hitl | PASS | run() 写 responder_action 并写 hitl_approvals(pending)，非直接执行 |
| test_execute_action_writes_disposition | PASS | execute_action 经 ActionService.execute + disposition_service 写 event_disposition_log |

### 2.5 ReporterAgent（4 用例）
| 用例 | 结果 | 说明 |
|------|------|------|
| test_metadata | PASS | name=reporter_agent，requires_hitl=False |
| test_run_aggregates_stages_and_marks_llm_unavailable | PASS | 聚合三阶段→Markdown；含"安全事件复盘报告""HITL 审批""LLM 摘要不可用"；evidence 非空 |
| test_run_reads_stage_outputs_from_db | PASS | 从 agent_run_steps 读取各阶段真实输出 |
| test_sink_case_writes_case_row | PASS | 写 cases 表 + 刷新 RAG 索引（rebuild_seed_index 已 mock 避免副作用） |

### 2.6 Orchestrator 流水线（3 用例）
| 用例 | 结果 | 说明 |
|------|------|------|
| test_run_pipeline_reaches_waiting_hitl | PASS | run_pipeline 串行 triage→investigation→responder→置 run=waiting_hitl；三阶段各写 1 步；pending 审批 action=block_ip |
| test_resume_approve_executes_and_completes | PASS | 管理员 approve→ActionService 被调用 + 写 event_disposition_log + reporter 收尾→run=completed（4 步含 report） |
| test_resume_reject_skips_execution | PASS | reject→跳过执行、无 disposition 行、run 收尾 completed |

**T-A1 覆盖率**：四 Agent 全部公共 API（name/requires_hitl/run/证据/置信度）、LLM 降级双路径、Orchestrator 状态机（waiting_hitl / completed / approve / reject）均已覆盖。

**T-A1 结论**：实现与设计（§4.3 / T-A1）一致，多智能体闭环可独立运行、降级安全闸有效。

---

## 三、T-A2：编排 API + HITL（8 用例，全部通过）

**测试文件**：`tests/test_batch2_agents_api.py`
**方式**：`fastapi.testclient.TestClient` + `dependency_overrides` 注入 `get_current_user`（mock auth，区分 admin / 普通用户 / 匿名）。

| 用例 | 结果 | 说明 |
|------|------|------|
| test_no_token_returns_401 | PASS | POST /api/agents/run 无 token → 401 |
| test_non_admin_can_list_runs | PASS | 普通用户 GET /api/agents/runs → 200（鉴权通过） |
| test_non_admin_cannot_approve_403 | PASS | 普通用户 POST /api/agents/runs/{id}/approve → 403（HITL 安全闸：仅管理员） |
| test_reject_endpoint_403_for_non_admin | PASS | 普通用户 reject → 403 |
| test_admin_approvals_list_200 | PASS | 管理员 GET /api/agents/approvals → 200 |
| test_create_run_reaches_waiting_hitl | PASS | 有效 token → 启动流水线 → waiting_hitl |
| test_end_to_end_hitl_loop | PASS | 端到端：waiting_hitl → 管理员 approve → ActionService 被调用 + 写 event_disposition_log → completed |
| test_approve_nonexistent_approval_404 | PASS | 审批不存在的 approval_id → 404（边界） |

**T-A2 覆盖率**：鉴权（401/403/200）、运行列表与详情（含 steps[]）、HITL 安全闸（admin-only 批准/拒绝/待审列表）、端到端 HITL 闭环、边界（404）全覆盖。

**T-A2 结论**：API 层与 HITL 安全闸行为符合设计，授权边界正确（非管理员无法批准/拒绝），端到端闭环贯通。

---

## 四、T-A3：前端接线（6 用例，全部通过）

**测试文件**：`tests/test_batch2_frontend.py`
**方式**：静态/集成校验（**不起 dev server**），逐文件读取源码做字符串/结构断言。

| 用例 | 结果 | 说明 |
|------|------|------|
| test_agent_orchestration_api_calls | PASS | agentOrchestration.js 含 6 个封装函数（createAgentRun/listAgentRuns/getAgentRun/approveAgentRun/rejectAgentRun/listPendingApprovals）；复用 `import request from './index'`；路径前缀 `/agents/run`、`/agents/runs`、`/agents/approvals` 一致 |
| test_agent_store_actions | PASS | stores/agents.js 接入 6 个 API，暴露 fetchRuns/fetchRunDetail/startRun/fetchApprovals/approve/reject 动作 |
| test_agent_run_view_embeds_hitl_panel | PASS | AgentRunView.vue 内嵌 `<HitlApprovalPanel>`（`@/components/agents/HitlApprovalPanel.vue`） |
| test_router_registers_agent_orchestration | PASS | router/index.js 注册 `agent-orchestration` → AgentRunView |
| test_applayout_has_menu_item | PASS | AppLayout.vue 含「智能体编排」菜单 + `/agent-orchestration` 路由 |
| test_axios_interceptor_injects_token | PASS | api/index.js 的拦截器自动注入 `ir_token` + `Bearer` |

**T-A3 覆盖率**：6 个 API 封装、store 动作、视图内嵌、路由、菜单、axios 拦截器自动带 token 全部静态校验通过。

**T-A3 结论**：**前端接线正确**。所有编排/HITL 前端元素均按设计落地，且与后端路由前缀 `/api/agents/*` 对齐（请求经 `request` 实例自动带 token）。

**人工联调建议（非阻断）**：
1. 浏览器联调时确认 `Bearer` token 由 `localStorage.ir_token` 正确提供、401 时跳转登录。
2. HitlApprovalPanel 的 `isAdmin` 来自 `authStore.user?.role==='admin'`，需确认登录态 user 对象含 `role` 字段且与后端 admin 判定一致。
3. 端到端 UI 走查：启动编排 → 等待 HITL → 管理员审批 → 状态流转为 completed。

---

## 五、测试代码中发现的 Bug（自修，路由 NoOne）

Round 1 共 10 项失败，**全部为测试代码 Bug**（非被测源码缺陷），已在 Round 2 前自修：

| # | 失败用例 | 根因（测试侧） | 自修动作 |
|---|----------|----------------|----------|
| 1 | test_batch2_orchestrator ×2 | 测试文件未 `import AgentRunStep`，导致 `NameError` | 补充 `from app.models.agent_run import AgentRun, AgentRunStep` |
| 2 | test_batch2_frontend ×6 | 前端路径算错：`backend/frontend/src`（应为项目根同级 `frontend/src`） | 改为 `os.path.normpath(os.path.join(_BACKEND, "..", "frontend", "src"))` |
| 3 | test_enabled_rules_and_hit_summary | 断言依赖"测试种子插入的 Suspicious Beacon 出现在前 50 条"——但 `init_db()` 已载入 100+ 默认规则，`get_enabled_rules(limit=50)` 分页将其截断 | 改为不依赖具体规则名/分页：断言 `get_enabled_rules()` 非空 + 用确定性构造的 fake rule 验证 `get_rules_hit_summary` 包含规则名 + 无规则→空串 |
| 4 | test_run_aggregates_stages_and_marks_llm_unavailable | 断言 `result.evidence` 非空，但测试 ctx 三阶段均传空 evidence，聚合结果为 0 | 在 ctx 三阶段补充 `evidence` 列表，使聚合逻辑被真实验证 |

> 说明：上述失败均因**测试代码自身断言不当/路径错误**，被测源码（Agent/Orchestrator/API/前端）行为均正确。故未触发"返工工程师"路由。

---

## 六、路由判定

- **判定**：`NoOne`
- **理由**：Round 2 回归 39/39 全部通过；Round 1 的 10 项失败经验证均为测试代码 Bug，已自修，被测源码无缺陷。
- **遗留**：无已知阻断性问题。T-A3 仅静态校验，建议按第四节人工联调建议做一次浏览器端到端走查（非阻断）。
- **环境注记**：测试运行时存在大量 `PydanticDeprecatedSince20`（class-based config / `@root_validator` / `parse_obj`）告警，属存量依赖告警，不影响功能与测试结论，建议后续批次统一迁移至 Pydantic V2 写法。
