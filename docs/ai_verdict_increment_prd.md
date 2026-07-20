# 增量 PRD：AI 事件研判打标（security_events.ai_verdict 生产者）

> 文档类型：简单 PRD（默认模式，无竞品/市场分析）
> 角色：产品经理（Alice）｜团队：software-ai-verdict
> 关联需求：P1-D「语义级跨资产告警降噪 2.0」上游补丁

---

## 1. 项目信息

| 项 | 内容 |
| --- | --- |
| Language | 中文 |
| 技术栈 | 后端：FastAPI / Python（复用 `AgentLLM`、`IncidentCorrelator`）；前端：复用现有前端栈（事件列表/详情页增量） |
| Project Name | `ai_event_verdict_tagging` |
| 文档范围 | **仅描述本次新增的"研判打标"功能**，不重复已有归并器（`incident_correlator.py`）逻辑 |

### 原始需求复述（根因）

`IncidentCorrelator`（语义归并器）作为**消费者**，只对 `security_events` 表中 `ai_verdict.label = 'suspicious'` 的事件做跨主机聚类。
但实测发现：当前 855 条 `security_events` 的 `ai_verdict` 字段**全为 `{}`（空对象）**，全表没有一条被标记为 `suspicious`；且 grep 整个 `backend/app` 确认**没有任何代码路径会把 `ai_verdict.label` 写成 `suspicious`**。

结论：归并器依赖的"AI 事件研判打标"这个**生产者功能缺失**，导致事件归并页面永远为空。本次增量开发即补齐该生产者。

---

## 2. 产品定义

### 2.1 产品目标（Product Goals，正交）

| # | 目标 | 说明 |
| --- | --- | --- |
| G1 | **补全数据生产链路** | 让安全事件经 AI 研判并打标（suspicious / false_positive / benign），为下游 `IncidentCorrelator` 提供真实数据源，使归并页能聚出可疑簇 |
| G2 | **稳健降级不中断** | LLM 不可用（无激活 Profile / 断路熔断 / 超时 / 解析失败）时，批量接口**绝不返回 500**，采用确定性兜底或跳过并标记，整批仍可完成 |
| G3 | **可审计可复核** | 每条研判经 `AgentLLM` 治理封装调用，审计落 `ai_audit_log`（含 `user_id`）；研判结果写回结构化字段，可被分析师复核 |

### 2.2 用户故事（User Stories）

- **US1**：作为 SOC 分析师，我希望对一批安全事件触发 AI 研判，系统调用大模型逐条判断可疑性并打标，以便事件归并能聚出可疑簇。
- **US2**：作为 SOC 分析师，我希望在 AI 服务不可用（如熔断）时，批量研判仍能正常返回（降级/跳过并标记），而不是整页报错 500，以便我能继续处置其它事件。
- **US3**：作为 SOC 分析师，我希望在事件详情中看到 `ai_verdict` 标签徽章（可疑/误报/正常）、置信度、攻击类型与研判理由，以便快速判断该事件是否需要关注。
- **US4**：作为安全平台管理员，我希望每次研判都经统一 LLM 治理（密钥解密、审计、预算保护）并留痕，以便满足合规与成本可控要求。
- **US5（P2）**：作为分析师，我希望只把高置信度的事件标记为 suspicious（可调阈值），以便降噪更精准、减少误聚。

---

## 3. 技术规范

### 3.1 需求池（Requirements Pool）

#### P0（Must have）

- **R1 触发方式**：新增后端端点（建议 `POST /api/security-events/ai-verdict`），接收 `{event_ids: [int]}`（支持单条与批量）。端点必须 `Depends(get_current_user)` 鉴权；当前 `user` 透传给 `AgentLLM.call(prompt, user=user)` 以写入审计 `user_id`。
- **R2 调用 AgentLLM 研判**：对每条事件，基于 `event_type`、`severity`、`evidence`（脱敏/裁剪后）、`host_id` 等构造研判 prompt，调用 `AgentLLM.call(prompt, user=user)`。prompt 需指示模型**仅返回严格 JSON**，含 `label` / `confidence` / `reason` / `attack_type`。
- **R3 写回 ai_verdict**：解析 LLM 返回的 JSON，规整为 `{"label": "suspicious"|"false_positive"|"benign", "confidence": 0.x, "reason": "...", "attack_type": "..."}`，`UPDATE security_events SET ai_verdict = ? WHERE id = ?`。**字段名/取值须与下游消费者契约一致**（下游读取 `label`/`confidence`/`attack_type`/`reason`）。
- **R4 降级不 500**：当 `resp.degraded == True`（无激活 Profile / 熔断 / 超时）或 JSON 解析失败时，**不抛 500**。对该事件采用"跳过并标记"兜底——写 `ai_verdict = {"label": "benign", "confidence": 0.0, "reason": "AI 降级：<error>", "attack_type": ""}`（或保留未研判状态并记 skip 明细）。批量整体以 2xx 返回，body 携带逐条状态。
- **R5 脱敏与预算**：构造 prompt 时对 `evidence` 等敏感字段做脱敏/裁剪，与平台脱敏约定一致；依赖 `AgentLLM` 的输入预算保护（超长 prompt 自动截断），不自行实现治理。
- **R6 响应结构**：返回 `{processed: int, skipped: int, failed: int, details: [{event_id, status, label?, reason?}]}`，供前端 toast 与明细展示。

#### P1（Should have）

- **R7 写回 ai_analysis**：研判结果（更丰富的分析文本/叙事）可选写入 `security_events.ai_analysis`（JSON/NULL），丰富事件详情，不影响下游归并。
- **R8 前端「AI 研判」按钮**：在事件列表/安全事件页提供批量选择 + 「AI 研判」操作按钮（选中多条 → 点击 → loading → 完成 toast）。
- **R9 详情徽章展示**：事件详情展示 `ai_verdict` 标签徽章与 `confidence`/`attack_type`/`reason`；若存在 `ai_analysis` 展示分析段落。

#### P2（Nice to have）

- **R10 研判进度/状态**：批量较大时展示异步进度（如后端任务 + 前端轮询/进度条）。
- **R11 研判历史**：可查看单事件历次研判记录，支持回滚/对比。
- **R12 可调阈值**：提供阈值参数，仅当 `confidence >= 阈值` 才标记 `suspicious`，否则降级为 `benign`/`false_positive`，提升降噪精度。

### 3.2 UI 设计稿（文字描述）

**安全事件列表页**
- 表头新增复选框列，支持多选。
- 工具栏新增「**AI 研判**」按钮（默认置灰，选中 ≥1 条后可用）。
- 交互：选中多条 → 点击按钮 → 按钮进入 loading → 调 `POST /api/security-events/ai-verdict` → 完成后 toast：「已对 N 条事件完成研判（X 条标记可疑，Y 条跳过）」。
- 列表行内可显示是否已研判状态（如 `ai_verdict` 非空则小图标）。

**事件详情（抽屉/页）**
- 顶部展示 `ai_verdict` 标签徽章：suspicious=红色、false_positive=灰色、benign=绿色。
- 徽章旁展示 `confidence`（如 0.82）、`attack_type`（如 "暴力破解"）、`reason` 文本。
- 若存在 `ai_analysis`，下方展示分析段落卡片。

### 3.3 待确认问题（Open Questions）

1. **触发方式**：研判是手动触发还是定时自动？**建议 MVP 先做手动批量触发**，定时自动作为后续迭代。
2. **批量上限**：一次批量处理多少条？**建议上限 200 条**，避免超时与prompt预算超支；超出时分批或提示。
3. **幂等策略**：是否跳过已研判（`ai_verdict != {}`）的事件？**建议默认跳过 + 提供 `force=true` 覆盖重判**。
4. **降级兜底策略**：MVP 采用"跳过并标记 degraded_reason"（R4 方案）还是"基于规则的确定性兜底"？建议前者（实现简单、可解释）。
5. **阈值默认值**：P2 可调阈值 `confidence` 默认建议 0.6（待与分析师确认业务口径）。

---

## 4. 上下游契约速查（供研发对齐）

| 字段 | 生产者（本 PRD）写入 | 消费者（`IncidentCorrelator`）读取 |
| --- | --- | --- |
| `ai_verdict.label` | `suspicious` / `false_positive` / `benign` | 过滤条件 `= 'suspicious'` |
| `ai_verdict.confidence` | 0–1 浮点 | 簇置信度均值、聚合 |
| `ai_verdict.attack_type` | 字符串 | 聚类 prompt、聚合 |
| `ai_verdict.reason` | 字符串 | 聚类 prompt（截断 80 字）、聚合 |
| `ai_analysis` | 可选分析文本（P1） | 不直接消费（详情展示） |

> 复用能力：`AgentLLM`（LLM 治理/审计/降级）、`get_current_user`（鉴权）、`security_events` 表结构。不重新实现密钥/熔断/审计。
