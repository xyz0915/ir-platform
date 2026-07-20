# QA 报告 — 第⑤批（P2-H）知识库自进化闭环 · 独立验证

> 验证人：software-qa-engineer-5（Edward，独立 QA）
> 验证对象：T-H1（kb_feedback 表 + 反馈模型/CRUD + 自进化服务 + `/api/kb` 路由）、T-H2（前端反馈视图/接线）
> 交付来源：software-engineer-7（自测 IS_PASS=YES，12/12，vite build 通过）
> 验证方式：**独立**隔离测试 + 静态契约核对 + 前端构建

---

## 1. 概述

| 维度 | 结果 |
|---|---|
| 独立 QA 测试（新写 `test_batch5_qa_independent.py`） | **24 / 24 通过** |
| 工程师自测（`test_batch5_kb_self_evolve.py`，作为基线复跑确认） | 12 / 12 通过 |
| 前端 `vite build` | **通过（exit 0，built in 30.51s）** |
| 合计 | 36 测试通过 + 前端构建通过 |
| 源码 Bug | **0** |
| 测试代码 Bug（自修，Round 2） | 2（均为测试自身问题，非源码缺陷） |
| **最终路由判定** | **NoOne**（全部通过，无需回退工程） |

---

## 2. 安全红线合规（硬约束）

- ✅ **绝不触碰生产库**：全部用例基于 `tests/_qa_batch1_common.IsolatedDBTestCase`，每个方法使用独立临时 SQLite（`config.settings.DB_PATH` 重定向到 `tempfile`），未触碰 `backend/data/ir_platform.db`。
- ✅ **绝不触碰向量库**：`KnowledgeRetriever.rebuild_seed_index` 全程以 `unittest.mock.patch` 替代（no-op），未触碰 `backend/data/chroma`。
- ✅ **无外网 / 无超时**：所有 LLM 调用经 `FakeLLM` / `DegradedLLM` / `RaisingLLM` mock，确定性、可重复。

---

## 3. 逐模块验证结果

### T-H1 · 后端（知识库自进化闭环）

#### 3.1 鉴权闸门（清单 item 1）
- ✅ `POST /api/kb/feedback`、`GET /api/kb/feedback`、`POST /api/kb/evolve`、`GET /api/kb/stats` **全部 `Depends(get_current_user)`**。
- ✅ 无 token 时 4 端点均返回 **401**（实测确认，非 403）。
- ✅ 端点解析于 `/api/kb/...`；与既有 `/api/knowledge` 路由（如 `/api/knowledge/drafts`）共存，OpenAPI 路径无交集，未发生冲突/覆盖。

#### 3.2 反馈模型 / CRUD（清单 item 2）
- ✅ `kb_feedback` 表存在 + 恰有 **2 个索引**（`idx_kb_feedback_type`、`idx_kb_feedback_applied`，在 `database.py` 中）。
- ✅ `feedback_type` 枚举（`false_positive` / `true_positive` / `suppress`）为事实来源；非法类型在模型层抛 `ValueError`、API 层返回 422。
- ✅ `create` / `get_by_id` / `list`（按类型、按 `applied`、分页）/ `list_unapplied` / `mark_applied` / `get_stats` 全部覆盖；`is_false_positive` 派生列仅 `false_positive` 为真。
- ✅ `get_stats` 按类型与沉淀状态统计正确（`total`/`applied`/`unapplied`/`false_positive`/`suppress`/`true_positive`）。

#### 3.3 自进化闭环（清单 item 3）
- ✅ **误报 / 抑制**反馈 → 写 `rule_suppression`（自动抑制，复用既有表）+ 生成 **approved** `KnowledgeDraft` + 回写 `kb_feedback.applied_to_kb=true` / `suppression_id` / `knowledge_draft_id` / `kb_entry_id`。
- ✅ 反馈被明确标记为已沉淀（`applied_to_kb=1`，`kb_entry_id == entry_ref`）。
- ✅ `evolve_all` 批量处理全部未沉淀反馈，`processed`/`applied` 计数准确，统计同步更新。

#### 3.4 真阳性只沉淀不抑制（清单 item 4）
- ✅ `true_positive` 反馈走沉淀（`knowledge_draft_id` 非空、`approved`），但 **不产生任何抑制规则**（`suppression_id` 为 `None`，`rule_suppression` 无新增行，沉积分类为 `tp_validation`）。

#### 3.5 LLM 降级（清单 item 5）
- ✅ `AgentLLM` 返回 `degraded=True`（无可用 Profile / 熔断）→ 自进化仍以 **确定性摘要**（含"经验沉淀"）完成闭环，沉淀成功，不抛 500。
- ✅ `AgentLLM` 调用直接抛异常（熔断）→ 同样走确定性降级，闭环完成。
- ✅ API 层 `POST /api/kb/evolve` 在 LLM 降级下返回 200 且 `applied=1`。

#### 3.6 复用既有 KB（清单 item 6）
- ✅ **未另起平行 KB**：沉积目标为既有 `knowledge_drafts` 表（`source=kb_self_evolve`），`entry_ref` 形如 `draft_<id>`；并触发既有 `KnowledgeRetriever.rebuild_seed_index`（best-effort 索引既有向量库，测试中以 mock 替代）。
- ✅ 源码静态核对：`kb_self_evolve.py` 复用 `KnowledgeDraft` 与 `KnowledgeRetriever`，无平行沉淀表（如 `kb_self_evolve_entries` / `kb_deposits`）。

#### 3.7 回归保护（清单 item 8）
- ✅ 既有 `/api/knowledge` 知识库路由不受影响：在同时挂载 `/api/kb` 与 `/api/knowledge` 的应用中，冒烟 `GET /api/knowledge/drafts` 返回 200（`code=0`），新 `/api/kb/*` 端点同时可用。

### T-H2 · 前端（知识反馈视图）

#### 3.8 前端契约（清单 item 7）
- ✅ `api/kbFeedback.js` 路径（`/kb/feedback`、`/kb/evolve`、`/kb/stats`）与后端 `/api/kb/...` 一致（`request` baseURL=`/api`）。
- ✅ `KbFeedbackView.vue` 消费字段（stats 卡片：`total/applied/unapplied/false_positive/suppress/true_positive/deposits`；反馈表：`feedback_type/rule_name/content/source_user/applied_to_kb/kb_entry_id/created_at`；沉淀表：`feedback_type/rule_name/kb_entry_id/summary/created_at`）**全部由后端响应覆盖**（契约测试断言通过）。
- ✅ 路由 `router/index.js` 已注册 `kb-feedback` → `KbFeedbackView.vue`；`AppLayout.vue` 侧边栏「知识自进化」指向 `/kb-feedback`。

#### 3.9 前端构建
- ✅ `npm run build` 退出码 0，`✓ built in 30.51s`，产物含 `KbFeedbackView` 等 chunk（仅有非致命的 chunk 体积告警，不影响交付）。

### 端到端冒烟（清单 item 9）
- ✅ 提交误报反馈 → `POST /api/kb/evolve` → 沉淀为 approved 草稿 + 抑制记录 → `GET /api/kb/stats` 体现 `applied=1`、`deposits` 含该条、`kb_entry_id` 以 `draft_` 开头；直接 DB 证据：抑制表 +1 行、approved 草稿 +1 条。

---

## 4. 测试清单与通过数（独立 QA 文件）

| 测试类 | 用例 | 结果 |
|---|---|---|
| TestKbAuthAndRouting | test_auth_gate_all_endpoints_require_token | PASS |
| | test_routes_resolve_under_api_kb_prefix | PASS |
| | test_no_conflict_with_existing_knowledge_prefix | PASS |
| TestKbFeedbackModelCRUD | test_kb_feedback_table_and_two_indexes | PASS |
| | test_create_three_types_enum_is_source_of_truth | PASS |
| | test_invalid_type_rejected_at_model | PASS |
| | test_invalid_type_rejected_at_api_422 | PASS |
| | test_list_filter_by_feedback_type_and_applied | PASS |
| | test_list_unapplied_returns_only_unprocessed | PASS |
| | test_stats_counts_per_type_and_applied | PASS |
| TestKbSelfEvolveLoop | test_false_positive_full_loop | PASS |
| | test_suppress_type_full_loop | PASS |
| | test_true_positive_deposits_no_suppression | PASS |
| | test_evolve_all_marks_everything_applied | PASS |
| | test_llm_unavailable_degradation | PASS |
| | test_llm_circuit_breaker_deterministic | PASS |
| | test_no_parallel_kb_module_reuses_existing | PASS |
| TestKbApiEndpoints | test_existing_knowledge_routes_unaffected | PASS |
| | test_e2e_false_positive_smoke | PASS |
| | test_evolve_all_endpoint | PASS |
| | test_evolve_endpoint_degraded_no_500 | PASS |
| | test_evolve_nonexistent_feedback_404 | PASS |
| TestKbFrontendContract | test_backend_response_contract_matches_vue | PASS |
| | test_frontend_api_paths_match_backend | PASS |

**独立 QA 通过数：24 / 24** ｜ 工程师自测（基线）：12 / 12 ｜ 前端构建：1 通过

---

## 5. 覆盖率（估算，针对本批新增/改动模块）

| 文件 | 估算行覆盖 | 说明 |
|---|---|---|
| `app/models/kb_feedback.py` | ~96% | create/get_by_id/list/list_unapplied/mark_applied/get_stats/_normalize 全覆盖；仅 `mark_applied` 异常分支未强制触发 |
| `app/services/kb_self_evolve.py` | ~92% | 主链路 + 降级（degraded/raising）+ 批量 + 复用既有 KB 全覆盖；个别 best-effort except 分支未断言错误态 |
| `app/api/knowledge.py` | ~95% | 4 端点 + 401 + 422 + 404 全覆盖 |
| `app/database.py`（kb_feedback DDL+索引） | 100%（该段） | 每个隔离用例经 `init_db` 建表；索引由专门用例断言 |
| `app/main.py`（include_router /api/kb） | 已验证 | 经回归用例（knowledge_draft 仍 200）+ 路由前缀存在性验证 |
| 前端 `KbFeedbackView.vue` / `kbFeedback.js` / `router` / `AppLayout.vue` | 契约 + 构建 | 字段契约测试通过 + `vite build` 通过 |

**本批后端模块综合估算覆盖：~92%**（关键路径、错误分支、降级路径均已覆盖）。

---

## 6. Bug 详情与路由判定

### 6.1 源码 Bug
**无。** 所有独立验证用例均通过，未暴露任何源码缺陷。

### 6.2 测试代码 Bug（自修，Round 2）
- **现象**：Round 1 中 `test_routes_resolve_under_api_kb_prefix` 与 `test_no_conflict_with_existing_knowledge_prefix` 失败（`app.routes` 路径集合为空）。
- **根因**：FastAPI 0.139 将 `include_router` 的路由包装为 `_IncludedRouter`，`app.routes` 上的单个 `Route` 对象的 `path` 为 `None`，无法直接枚举路径。
- **修复**：改用 `app.openapi()["paths"]` 提取真实已注册路径（含前缀）后再断言。属 **测试自身构造问题，非源码缺陷**。
- **Round 2 结果**：24 / 24 全部通过。

---

## 7. 设计文档 vs 实现差异说明（透明度，非缺陷）

实现相对 `docs/ai_features_design.md` §4.3 原描述有两点合理扩展，且**已被 team-lead 验证清单采纳**：

1. **挂载前缀**：原设计写 `POST /api/knowledge/ingest-feedback`；实现改为独立前缀 `/api/kb`（避免与既有 `/api/knowledge` 路由冲突）。验证清单明确要求端点解析于 `/api/kb/...`。
2. **反馈 Schema**：原设计仅 `is_false_positive` / `ingested` 布尔位；实现以 `feedback_type` 枚举（false_positive/true_positive/suppress）为单一事实来源，并保留 `is_false_positive` / `applied_to_kb`（即 `ingested`）派生兼容列。验证清单明确要求 `feedback_type` 枚举为事实来源。

上述扩展在工程师代码注释中已说明，且通过全部独立验证，不视为缺陷。

---

## 8. 最终路由判定

**NoOne** — 独立验证 24/24 通过，工程师自测 12/12 通过，前端 `vite build` 通过，0 源码 Bug，安全红线全部遵守。第⑤批（P2-H 知识库自进化闭环）**验收通过**，无需回退工程修改。
