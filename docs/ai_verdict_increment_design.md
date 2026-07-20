# 增量设计：AI 事件研判打标（security_events.ai_verdict 生产者）

> 文档类型：系统增量设计 + 任务分解
> 角色：架构师（Bob/高见远）｜团队：software-ai-verdict
> 上游：PM 增量 PRD `docs/ai_verdict_increment_prd.md`
> 关联：消费者 `backend/app/services/incident_correlator.py`（语义归并器）

---

## 0. 设计结论速览（给主理人）

| 项 | 结论 |
| --- | --- |
| 根因 | 855 条事件 `ai_verdict={}`，无任何生产者写入 `suspicious`，归并器无数据源 |
| 方案 | 新增研判**生产者**服务 `EventVerdictService` + 端点 `POST /api/security-events/ai-verdict` |
| 关键契约（成败点） | 写回 JSON 键名 `label/confidence/reason/attack_type` 与 `incident_correlator.py` 读取键**逐字符一致**；`label∈{suspicious,false_positive,benign,unknown}` |
| 路由 | 新 router 独立前缀 `/api/security-events`，装饰器 `@router.post("/ai-verdict")` —— **不重复前缀**（规避 Batch③ 404 教训） |
| 降级 | `degraded/解析失败 → 写 {label:"unknown",...}，整批 2xx，绝不 500` |
| 幂等 | `force=False` 跳过已研判事件；`force=True` 覆盖 |
| 上限 | 200 条，超出返回 400（客户端错误，非 500） |
| 新依赖 | 无（全部复用 AgentLLM / get_current_user / data_masking / sqlite） |
| 任务数 | T-V1 服务+写回 → T-V2 端点+鉴权 → T-V3 前端按钮+徽章 → T-V4 自测+QA（共 4 个，≤5 上限） |

---

## 1. 实现方案

### 1.1 技术难点与选型

| 难点 | 选型 / 处理 |
| --- | --- |
| 补齐"生产者"且不得破坏下游契约 | 严格按 §4 契约写回；服务层做 `label` 枚举校验 + `confidence` 浮点钳制，杜绝脏数据进入 `ai_verdict` |
| LLM 不可用 / 超时 / 熔断 / 解析失败 | 复用 `AgentLLM`（内部已包裹 CircuitBreaker + 重试 + 审计 + 降级 `degraded=True`）；逐条 try/except，**单条失败不影响整批**，绝不抛 500 |
| evidence 含 PII（IP/路径/用户名/域名） | 复用 `app.services.data_masking.apply(evidence)` 构造脱敏 prompt（与既有 RootCause 等一致） |
| 批量预算/超时 | `AgentLLM` 自带 `AI_INPUT_BUDGET` 截断；端点层限制 ≤200 条；逐条 await 串行（可控、审计清晰） |
| 审计合规 | `AgentLLM.call(prompt, user=user)` 内部写 `ai_audit_log(user_id)`；`user` 来自 `get_current_user` 透传 |

架构模式：**Service + Router**（轻量分层，与 `incident_correlator` / `events.py` 现有风格一致）。不引入新框架/新依赖。

### 1.2 新增服务 `EventVerdictService`（backend/app/services/event_verdict_service.py）

```python
class EventVerdictService:
    MAX_BATCH = 200
    DEFAULT_THRESHOLD = 0.6
    ALLOWED_LABELS = {"suspicious", "false_positive", "benign", "unknown"}

    async def analyze_events(self, event_ids, user, force=False, confidence_threshold=0.6) -> dict:
        # 返回 {processed, skipped, degraded, failed, limit, details}
```

逐条处理流程（`_process_one`）：
1. `SELECT id, event_type, severity, host_id, evidence, ai_verdict FROM security_events WHERE id=?`
2. **不存在** → `detail(status="failed", reason="event_not_found")`
3. **已研判且 `force=False`** → `detail(status="skipped")`（幂等保护）
4. **需研判** → `data_masking.apply(evidence)` 脱敏 → 构造 prompt → `await self._llm.call(prompt, user=user)`
5. `resp.degraded or not resp.get("content")` → 写 `{label:"unknown", confidence:0.0, reason:"AI降级：<error>", attack_type:""}`，`detail(status="degraded")`
6. 否则 `_parse_llm(content)` → `_normalize(threshold)`（label 枚举校验、confidence 钳制 0..1、阈值降级的 suspicious→benign）→ 参数化 `UPDATE ai_verdict=? , ai_analysis=? WHERE id=?` → `detail(status="processed", label)`
7. 任一步异常 → `detail(status="failed")`，**继续下一条**

**降级兜底选择 `unknown` 而非 `benign` 的原因**：下游 `_fetch_suspicious_events` 只认 `label='suspicious'`，`_verdict_agg` 默认 `unknown`；写 `unknown` 既不污染 `benign` 统计、也不会被误判为正常，且明确表达"本次未成功研判，可 force 重判"。

参数化写回（杜绝注入）：
```python
conn.execute(
    "UPDATE security_events SET ai_verdict=?, ai_analysis=?, updated_at=? WHERE id=?",
    (json.dumps(verdict, ensure_ascii=False), analysis_json_or_None, now, event_id),
)
```
`ai_analysis` 写入用 `try/except` 包裹：若列不存在（迁移未执行）则跳过该行写、不影响 `ai_verdict`。

### 1.3 端点设计（backend/app/api/event_verdict.py）

```python
router = APIRouter()  # 注意：router 自身不带前缀

@router.post("/ai-verdict")                      # 装饰器只写相对路径
async def analyze_event_verdict(
    body: dict,                                  # 与 events.py 风格一致，手动解析
    current_user: dict = Depends(get_current_user),
):
    event_ids = body.get("event_ids", [])
    force = bool(body.get("force", False))
    threshold = float(body.get("confidence_threshold", 0.6))
    # 校验：非空 / 去重 / 类型 / ≤200
    ...
    svc = EventVerdictService()
    result = await svc.analyze_events(event_ids, user=current_user, force=force, confidence_threshold=threshold)
    return {"code": 0, "data": result, "message": "success"}
```

**挂载（backend/app/main.py，新增一行，放在其他 include_router 附近）：**
```python
from app.api import event_verdict  # noqa: E402
app.include_router(event_verdict.router, prefix="/api/security-events", tags=["AI研判"])
```
✅ 最终路径 = `/api/security-events/ai-verdict`，与 PRD 一致；✅ 装饰器未重复前缀（规避 Batch③ `/api/api/analysis/...` 404 教训）。

**鉴权**：`from app.services.auth_service import get_current_user`（与 `events.py` 完全一致，不要从 `api/auth.py` 导入）。

---

## 2. 文件列表（新增 / 修改，相对路径）

### 新增
| 文件 | 任务 | 说明 |
| --- | --- | --- |
| `backend/app/services/event_verdict_service.py` | T-V1 | 研判生产者服务（核心） |
| `backend/app/api/event_verdict.py` | T-V2 | 端点 + 鉴权 |
| `backend/app/schemas/event_verdict.py` | T-V2 | 请求/响应 Pydantic 契约（清晰、利于 QA） |
| `backend/tests/test_event_verdict.py` | T-V4 | 单测 + 集成自测 |
| `docs/ai_verdict_qa_checklist.md` | T-V4 | QA 验收清单 |
| `docs/ai_verdict_sequence.mermaid` | — | 时序图（本文件提取） |
| `docs/ai_verdict_class.mermaid` | — | 类图（本文件提取） |

### 修改
| 文件 | 任务 | 说明 |
| --- | --- | --- |
| `backend/app/main.py` | T-V2 | 注册 `event_verdict.router`（`prefix="/api/security-events"`） |
| `backend/app/database.py` | T-V1 | 可选 ALTER：加 `ai_analysis TEXT`（仿 `_alter_security_events_add_ai_verdict`，PRAGMA 守卫；R7 用，缺失不阻断） |
| `frontend/src/api/events.js` | T-V3 | 新增 `triggerEventVerdict(eventIds, {force, threshold})` → `POST /security-events/ai-verdict` |
| `frontend/src/stores/analysis.js` | T-V3 | 新增 `analyzeEvents(ids, opts)` action（调 API + toast + 刷新） |
| `frontend/src/views/AnalysisCenterView.vue` | T-V3 | 工具栏新增「🤖 AI 研判打标」按钮（依赖 `store.selectedEventIds`）+ handler |
| `frontend/src/components/analysis/EventDetailPanel.vue` | T-V3 | 增强已有 `ai-verdict-section`：补 `attack_type`、按 `label` 上色徽章 |
| `frontend/src/components/analysis/EventTable.vue` | T-V3 | 列表行加"已研判"标记（读 `row.ai_verdict.label`） |

---

## 3. 数据结构与接口契约

### 3.1 ai_verdict 写回 JSON（与消费者读取键严格一致）

```json
{
  "label": "suspicious" | "false_positive" | "benign" | "unknown",
  "confidence": 0.0,
  "reason": "string",
  "attack_type": "string"
}
```

### 3.2 契约速查表（生产者↔消费者）

| 键 | 生产者写 | 消费者读（`incident_correlator.py`） | 必须一致 |
| --- | --- | --- | --- |
| `ai_verdict.label` | `suspicious/false_positive/benign/unknown` | `_fetch_suspicious_events`: `json_extract(ai_verdict,'$.label')='suspicious'`；`_verdict_agg`: `verdict.get("label","unknown")` | ✅ 取值集合 + 键名 |
| `ai_verdict.confidence` | float 0..1 | `_cluster_confidence`: `verdict.get("confidence")`；`_verdict_agg` 均值 | ✅ 键名 + 数值类型 |
| `ai_verdict.attack_type` | string | `_try_llm_cluster`: `verdict.get("attack_type","")`；`_verdict_agg` 聚合 | ✅ 键名 |
| `ai_verdict.reason` | string | `_try_llm_cluster`: `(verdict.get("reason") or "")[:80]` | ✅ 键名 |
| `ai_analysis` | TEXT/JSON/NULL（P1，可选） | 不消费（仅详情展示） | — |

> ⚠️ **成败关键**：任一键名拼写/取值偏差，下游 `cluster()` 仍读不到，`event_stats` 的 `ai_suspicious` 计数与归并页永远为空。服务层 `_normalize` 强制校验上述 4 键。

### 3.3 端点请求 / 响应

**请求** `POST /api/security-events/ai-verdict`（body JSON）：
```json
{ "event_ids": [101, 102], "force": false, "confidence_threshold": 0.6 }
```

**响应**（统一 `{code,data,message}`）：
```json
{
  "code": 0,
  "data": {
    "processed": 1, "skipped": 0, "degraded": 1, "failed": 0,
    "limit": 200,
    "details": [
      {"event_id": "101", "status": "processed", "label": "suspicious", "reason": "..."},
      {"event_id": "102", "status": "degraded", "label": "unknown", "reason": "AI降级：断路器已熔断"}
    ]
  },
  "message": "success"
}
```
`status ∈ {processed, skipped, degraded, failed}`。

### 3.4 类图（Mermaid）

见 `docs/ai_verdict_class.mermaid`，核心类：
- `EventVerdictService`（生产者，`analyze_events` + 私有 `_fetch/_build_prompt/_parse_llm/_normalize/_write_back`）
- `AiVerdict`（写回数据结构，`label/confidence/reason/attack_type`）
- `AgentLLM`（既有，返回 `{content,degraded,error}`）
- `VerdictRouter` / `VerdictRequest` / `VerdictResponse` / `VerdictDetail`

### 3.5 时序图（Mermaid）

见 `docs/ai_verdict_sequence.mermaid`：前端 → Router(鉴权+校验) → Service(逐条 fetch→脱敏→AgentLLM→解析/降级→参数化UPDATE) → 返回聚合 → 下游 `IncidentCorrelator` 读 `label='suspicious'` 聚簇。

---

## 4. 程序调用流（关键路径）

参见 `docs/ai_verdict_sequence.mermaid`。要点：
- 端点 `async` + `await svc.analyze_events`（因 `AgentLLM.call` 是 async）。
- 逐条串行 `await`，每条独立 try/except，单条异常计入 `failed` 并继续。
- 写回一律参数化 `UPDATE ... WHERE id=?`，`ai_verdict` 以 `json.dumps` 字符串存储。
- 批量结束返回 2xx（即使全 degraded），由 `details` 暴露逐条状态供前端 toast。

---

## 5. 任务分解（有序、含依赖）

> 说明：本增量不新增"项目基础设施"（无新构建配置/依赖），故**首个任务直接为服务层**（T-V1）。这是相对于通用模板"首任务=基础设施"的合理偏离，遵循主理人指定的 T-V1..T-V4 划分；强行套基础设施任务会空转。

| Task | 名称 | 源文件 | 依赖 | 优先级 |
| --- | --- | --- | --- | --- |
| **T-V1** | 研判服务 + 写回 + 可选 ai_analysis 列迁移 | `backend/app/services/event_verdict_service.py`（新）、`backend/app/database.py`（改：可选 ALTER） | 无 | P0 |
| **T-V2** | 端点 + 鉴权 + 路由挂载 + 契约 schema | `backend/app/api/event_verdict.py`（新）、`backend/app/schemas/event_verdict.py`（新）、`backend/app/main.py`（改） | T-V1 | P0 |
| **T-V3** | 前端按钮 + 详情徽章 + 列表标记 | `frontend/src/api/events.js`（改）、`frontend/src/stores/analysis.js`（改）、`frontend/src/views/AnalysisCenterView.vue`（改）、`frontend/src/components/analysis/EventDetailPanel.vue`（改）、`frontend/src/components/analysis/EventTable.vue`（改） | T-V2 | P1 |
| **T-V4** | 自测 + QA 准备 | `backend/tests/test_event_verdict.py`（新）、`docs/ai_verdict_qa_checklist.md`（新） | T-V1, T-V2 | P1 |

依赖关系：`T-V2 → T-V1`；`T-V3 → T-V2`；`T-V4 → T-V1,T-V2`。T-V3/T-V4 不互相依赖，可并行。

---

## 6. 依赖包

**无新第三方依赖。** 全部复用既有：
- 后端：`fastapi`、`pydantic`（仅 schema）、`sqlite3`（标准库）、`json`（标准库）
- 既有自研：`AgentLLM`、`get_current_user`、`data_masking`、`SecurityEvent` 常量
- 前端：`element-plus`（已有）、`axios`（已有，baseURL `/api`）

---

## 7. 共享知识（跨成员速查）

- **脱敏调用**：`from app.services.data_masking import apply; masked = apply(evidence_dict)`（递归脱敏 IP/路径/用户名/域名），用于构造 prompt 前。
- **AgentLLM 调用范式**：`resp = await AgentLLM().call(prompt, user=current_user)`；判降级 `if resp.get("degraded") or not resp.get("content"): ...`；成功取 `resp["content"]`。**必须 `await`**（async）。
- **UPDATE 参数化约定**：`conn.execute("UPDATE security_events SET ai_verdict=? WHERE id=?", (json_str, event_id))`；`ai_verdict` 永远 `json.dumps(...)` 成字符串；勿字符串拼接 SQL。
- **鉴权依赖导入**：`from app.services.auth_service import get_current_user`（非 `api/auth.py`）。
- **路由前缀约定**：新 router 自带无前缀，`main.py` 用 `prefix="/api/security-events"` 挂载；装饰器写 `@router.post("/ai-verdict")`（**不重复前缀**）。
- **响应包裹**：返回 `{"code":0,"data":...,"message":"success"}`（与 `events.py` 的 `success()` 一致）。
- **契约键名**（写入 `ai_verdict`）：`label / confidence / reason / attack_type` —— **逐字符**匹配 `incident_correlator.py` 读取键。

---

## 8. 待明确事项 → 建议默认值（已采纳进设计）

| # | 待确认 | 建议默认值 | 落地位置 |
| --- | --- | --- | --- |
| 1 | 触发方式 | **手动批量**（选中事件 → 按钮触发）；定时自动留待后续迭代 | T-V3 按钮 + T-V2 端点 |
| 2 | 批量上限 | **200 条**；超出返回 `400`（客户端错误，非 500） | `EventVerdictService.MAX_BATCH` + 端点校验 |
| 3 | 幂等策略 | `force=False` 默认**跳过** `ai_verdict!={}` 的事件；`force=True` 覆盖重判 | `_process_one` 步骤 3 |
| 4 | 降级兜底 | **跳过并标记** → 写 `{label:"unknown", confidence:0.0, reason:"AI降级：<err>", attack_type:""}`；整批 2xx，绝不 500（选 unknown 而非 benign，避免污染统计） | `_process_one` 步骤 5 |
| 5 | 阈值默认 | **0.6**；`confidence<0.6` 时即便 LLM 给 suspicious 也降级为 `benign`（P2 可调，经请求体 `confidence_threshold` 传入） | `_normalize(threshold)` |

---

## 9. 风险与未决

- **`ai_analysis` 列缺失**：`security_events` 当前无此列。`database.py` 加 PRAGMA 守卫 ALTER；服务层写 `ai_analysis` 用 try/except 包裹，**缺失不阻断** `ai_verdict` 写回（R7 为 P1 可选，不影响消费者）。
- **Prompt 质量**：LLM 可能返回非严格 JSON。服务层用稳健提取（容忍 ```json 包裹 / 前后噪声）+ 异常兜底；解析失败按 `degraded` 处理。
- **批量耗时**：200 条串行 await，按每条 ~1–3s 估算最坏 ~10min。依赖 `AgentLLM` 内部超时/重试；前端按钮 loading + 完成 toast。P2（R10）异步任务/进度条留待后续。
- **label 取值漂移**：若后续 LLM 返回 `malicious` 等未知值，`_normalize` 强制落入 `unknown`，不会写入非法值。
