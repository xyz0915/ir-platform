# QA 测试报告：AI 事件研判打标（生产者增量）

> 验证角色：software-qa-engineer（严过关）｜团队：software-ai-verdict
> 验证对象：工程师 software-engineer 交付的「AI 事件研判打标」增量（T-V1 服务 / T-V2 端点 / T-V3 前端 / 消费者链路）
> 独立测试文件：`backend/tests/test_event_verdict_qa_independent.py`
> 安全红线：全部用例基于 `IsolatedDBTestCase`（临时 SQLite），**未触碰 `backend/data/ir_platform.db`**；LLM 全部用 `unittest.mock.patch` 注入 Fake，不触达真实大模型/网络。

---

## 1. 结论速览

| 项 | 结果 |
| --- | --- |
| 后端独立测试 | **23 / 23 通过**（T-V1 11 + T-V2 6 + 生产者↔消费者契约 3 + T-V3 前端契约 3） |
| 前端 `vite build` | **通过**（✓ built in 25.42s，仅 chunk-size 警告，无错误） |
| 10 项验证清单 | **全部覆盖并通过** |
| 源码 Bug | **0**（未发现实现缺陷） |
| 测试代码 Bug | 2 个（Round 1 自修，见 §5） |
| **最终路由判定** | **NoOne**（无需回退工程师，全部通过） |

---

## 2. 逐模块结果

### T-V1：EventVerdictService（研判生产者服务）
- 文件：`backend/app/services/event_verdict_service.py`
- 测试类：`TestEventVerdictServiceQa`（11 用例）
- 覆盖：写回契约（键名逐字符）、降级→unknown、解析失败→unknown、阈值降级、幂等跳过/覆盖、未知 label 归一化、confidence 越界钳制、` ```json ` 包裹容忍、事件不存在→failed、参数化写回防注入、响应结构。
- 通过：**11/11**
- 源码评估：写回 JSON 键名 `{label, confidence, reason, attack_type}` 与消费者读取键完全一致；`_normalize` 对 label 枚举/置信度钳制/阈值降级逻辑正确；逐条 try/except + 顶层 try/except 保证单条异常不逃逸、整批 2xx；UPDATE 全程参数化。

### T-V2：端点 + 鉴权 + 路由（POST /api/security-events/ai-verdict）
- 文件：`backend/app/api/event_verdict.py`、`backend/app/schemas/event_verdict.py`、`backend/app/main.py`
- 测试类：`TestEventVerdictEndpointQa`（6 用例）
- 覆盖：路由无重复前缀、鉴权闸门（无 token→401）、成功写回、空 event_ids→400、批量上限>200→400、边界恰好 200 条放行、响应包裹 `{code,data,message}`。
- 通过：**6/6**
- 源码评估：`main.py` 以 `prefix="/api/security-events"` 挂载，`router` 自身无前缀、装饰器 `@router.post("/ai-verdict")` —— 最终路径 `/api/security-events/ai-verdict`，无重复前缀；`Depends(get_current_user)` 鉴权到位；上限校验在调用服务前，返回 400（客户端错误，非 500）。

### 生产者↔消费者契约（成败关键链路）
- 消费者：`backend/app/services/incident_correlator.py`
- 测试类：`TestProducerConsumerContractQa`（3 用例）
- 覆盖：生产者写回能被 `_fetch_suspicious_events` 的 `json_extract(ai_verdict,'$.label')='suspicious'` 命中；`_verdict_agg` / `_cluster_confidence` 能正确消费 `label/attack_type/confidence`；端到端（mock LLM→端点→ai_verdict.label='suspicious'→消费者命中）。
- 通过：**3/3**
- 源码评估：生产者→消费者链路**打通**。消费者读取键与生产者写入键逐字符一致（已用黄金键集合 `CONSUMER_KEYS` 断言）。

### T-V3：前端按钮 + 详情徽章 + 列表标记
- 文件：`frontend/src/api/events.js`、`frontend/src/stores/analysis.js`、`frontend/src/views/AnalysisCenterView.vue`、`frontend/src/components/analysis/EventDetailPanel.vue`、`frontend/src/components/analysis/EventTable.vue`
- 测试类：`TestFrontendContractQa`（3 用例，静态校验源文件）
- 覆盖：`triggerEventVerdict` 请求路径 `/security-events/ai-verdict`（与 baseURL `/api` 拼接为 `/api/security-events/ai-verdict`，与后端一致）、透传 `confidence_threshold`；`EventDetailPanel` 按 `label` 上色徽章（vlabel-suspicious/benign/false_positive/unknown）并展示 `attack_type`；`AnalysisCenterView` 含「🤖 AI 研判打标」按钮与 `analyzeEvents`/`selectedEventIds` 绑定。
- 通过：**3/3**
- `vite build`：**通过**（无任何错误；`:contains()` CSS 伪类被构建容忍，仅产生 chunk 体积警告，不影响产物）。
- 源码评估：前端契约与后端一致；响应经 axios 拦截器解包为 `{code,data,message}`，store 读取 `res.data.processed/skipped/...` 与后端 `{code:0,data:{processed,...}}` 对齐正确。

---

## 3. 验证清单（10 项）对照

| # | 验证项 | 用例 | 结果 |
| --- | --- | --- | --- |
| 1 | 路由无重复前缀 `/api/security-events/ai-verdict` | test_no_duplicate_prefix | ✅ |
| 2 | 鉴权闸门（无 token→401） | test_auth_required_401 | ✅ |
| 3 | 写回契约逐字符一致 + 消费者 SQL 命中 | test_writeback_contract_char_by_char / test_consumer_fetches_producer_output | ✅ |
| 4 | 降级不 500（degraded/解析失败→unknown，整批 2xx） | test_degraded_to_unknown_no_500 / test_parse_failure_to_unknown | ✅ |
| 5 | 阈值降级（conf<阈值 suspicious→benign） | test_threshold_downgrade | ✅ |
| 6 | 幂等（force=False 跳过 / force=True 覆盖） | test_idempotent_skip_and_force | ✅ |
| 7 | 批量上限（>200→400，非 500） | test_batch_limit_400 / test_batch_limit_exact_200_ok | ✅ |
| 8 | 参数化写回（无 SQL 注入隐患） | test_parameterized_writeback_no_injection | ✅ |
| 9 | 前端契约（路径/徽章/按钮）+ vite build | TestFrontendContractQa(3) + vite build | ✅ |
| 10 | 端到端冒烟（mock LLM→端点→suspicious→消费者命中） | test_e2e_smoke_endpoint_to_consumer / test_consumer_aggregators_read_keys | ✅ |

---

## 4. 覆盖率（估计）

| 模块 | 覆盖率 | 说明 |
| --- | --- | --- |
| T-V1 `event_verdict_service.py` | ~95% | 主流程 + 全部降级/归一化/解析/写回分支覆盖；仅日志/装饰分支未逐行断言 |
| T-V2 `event_verdict.py` + `main.py` 挂载 | ~100% | 路由/鉴权/校验/成功/信封全覆盖 |
| T-V2 `schemas/event_verdict.py` | 100% | 经端点用例间接验证（Pydantic 校验生效） |
| 消费者契约链路 | 100% | 生产者写回被消费者两个读取路径（`_fetch_suspicious_events` / `_verdict_agg` / `_cluster_confidence`）消费验证 |
| T-V3 前端 | 契约+编译验证 | 静态契约校验 3 项 + `vite build` 通过；前端组件逻辑未做 js 单元测试（无 js 测试框架，按增量约定以编译+契约校验为准） |

整体后端关键路径覆盖率估计 **≥90%**。

---

## 5. Bug 详情与路由

### Round 1（自测轮，测试代码 Bug → 自修，不计入源码缺陷）
发现 2 个**测试代码**缺陷，均为 QA 自身错误，已自修：
1. `test_e2e_smoke_endpoint_to_consumer`：`self._seed(["evt-smoke"])` 误将列表当作数量参数传入 `_seed(self, n, ids=None)` → 改为 `self._seed(1, ids=["evt-smoke"])`。
2. `test_consumer_aggregators_read_keys`：断言 `agg.get("label")` 与消费者实际返回结构不符（实际返回 `{"labels": {...}, "attack_types": [...], "avg_confidence": ...}`，`label` 嵌套在 `labels` 下）→ 改为断言 `agg["labels"]["suspicious"]==1`、`"横向移动" in agg["attack_types"]`、`agg["avg_confidence"]≈0.95`。

修正后重跑 → 23/23 全绿。

### 源码缺陷
**无。** 工程师实现与设计/PRD/消费者契约自洽，未发现需要回退实现的 Bug。

### 最终路由判定
**NoOne** —— 全部验证通过，无需回退工程师（Engineer）；测试代码 Bug 已在第 1 轮内自修完毕（未超过 2 轮上限）。

---

## 6. 附：执行命令与产物

- 后端测试：
  `backend/venv/Scripts/python.exe -m pytest tests/test_event_verdict_qa_independent.py -q`
  → `23 passed`
- 前端构建：
  `cd frontend && npm run build` → `✓ built in 25.42s`
- 测试产物：`backend/tests/test_event_verdict_qa_independent.py`（23 用例）
- 构建产物：`frontend/dist/`（AnalysisCenterView、EventDetailPanel 等模块均成功打包）
