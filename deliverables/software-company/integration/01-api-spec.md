# 智能体编排管理 · 接口规范（集成基线）

> 产出角色：架构师（高见远 / Gao）
> 配套文档：`01-arch-design.md`（架构设计）、`01-tasks.md`（任务分解）。
> 约定：✅ = 真实后端（现有 `frontend/src/api/*.js`）；⚠️ = 接口层真实但执行空壳（M1 收敛）；🔶 = Mock 占位（后端未建，对齐方案字段语义）。
> 所有响应统一信封 `{ code: number, data: T, message: string }`，`code===0` 成功。

---

## 0. 总览：9 模块接口映射速查

| 模块 | 数据实体（核心） | 真实端点 / Mock 适配器 | 状态 |
|---|---|---|---|
| M1 Dashboard | `DashboardStats` | `GET /agents/runs` + `GET /agents/stats`（真实）+ `dashboardMock.getTrend/getGuardrailBlocks`（🔶） | 部分真实 |
| M2 智能体管理 | `AgentConfig` | `GET/POST/PUT/DELETE /agent-management/agents` ✅ | 真实 |
| M3 流水线 DAG | `PipelineDef` / `PipelineNode` / `PipelineEdge` | `POST /agent-management/pipeline/validate`、`POST .../run`、`GET .../run/:id`、`POST .../resume` ⚠️ + `pipelineMock` 种子 🔶 | 接口真实/执行空壳 |
| M4 工具/MCP | `ToolDef` / `McpServer` | `toolsMock.listTools/listMcpServers` 🔶 | Mock |
| M5 记忆/RAG | `KnowledgeBase` | `memoryMock.listKnowledgeBases` 🔶 | Mock |
| M6 人工审核台 | `HitlTask` / `GuardrailResult` | `GET /agents/approvals`、`POST /agents/runs/:id/approve`、`POST .../reject` ✅ | 真实 |
| M7 护栏与安全 | `GuardrailPolicy` / `GuardrailHit` / `GuardrailResult` | `guardrailMock.*` 🔶（含 `evaluate`） | Mock |
| M8 可观测性 | `ObservabilityRun` / `TraceSpan` / `LogEntry` | `GET /agents/runs/:id`（真实）+ `observabilityMock.getRun` 🔶（trace/log/resume_point） | 部分真实 |
| M9 设置 | `ModelProfile` / `DeploymentConfig` | `settingsMock.*` 🔶 | Mock |

---

## 1. M1 Dashboard（概览）

### 1.1 实体 `DashboardStats`
```ts
interface DashboardStats {
  running_agents: number          // 运行中智能体数
  success_rate: number            // 成功率（0-100，百分制）
  pending_hitl: number            // 待审 HITL 数
  guardrail_blocks: number        // 护栏拦截（未通过）数
  recent_runs: AgentRun[]         // 近期运行（见 M8）
  trend: { ts: string; success_rate: number }[]  // 近 7 日趋势（🔶 Mock）
}
```

### 1.2 接口契约
| 方法 路径 | 类型 | 说明 | 返回 |
|---|---|---|---|
| `GET /agents/runs?page=&page_size=` | ✅ 真实 | 运行列表（组合聚合用） | `{items:AgentRun[], total:number}` |
| `GET /agents/stats` | ✅ 真实 | 运行统计 | `{running:number, success_rate:number, ...}` |
| `GET /agent-guardrails/hits`（经 `guardrailMock.listHits`） | 🔶 Mock | 护栏命中（算 guardrail_blocks） | `GuardrailHit[]` |
| `GET /agent-orchestration/dashboard/trend`（经 `dashboardMock.getTrend`） | 🔶 Mock | 趋势曲线 | `{ts,success_rate}[]` |

> 无独立聚合端点：前端 `agentDashboard.fetchStats()` 并行上述调用后在 store 内计算 `DashboardStats`。

---

## 2. M2 智能体管理（复用 `agentManagement.js`）

### 2.1 实体 `AgentConfig`
```ts
interface AgentConfig {
  agent_id: string
  display_name: string
  kind: 'builtin' | 'custom'
  description: string
  data_sources: string[]
  depends_on: string[]
  tools: string[]            // ToolRegistry tool_id
  model_profile: string      // AgentLLM profile_id
  status: 'active' | 'draft' | 'disabled'
  created_at: string         // ISO8601
  updated_at: string
}
```
JSON Schema（核心字段）：
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AgentConfig",
  "type": "object",
  "required": ["agent_id","display_name","kind","status"],
  "properties": {
    "agent_id":  { "type": "string" },
    "display_name": { "type": "string" },
    "kind": { "type": "string", "enum": ["builtin","custom"] },
    "data_sources": { "type": "array", "items": { "type": "string" } },
    "depends_on": { "type": "array", "items": { "type": "string" } },
    "tools": { "type": "array", "items": { "type": "string" } },
    "model_profile": { "type": "string" },
    "status": { "type": "string", "enum": ["active","draft","disabled"] }
  }
}
```

### 2.2 接口契约（✅ 真实，来自 `agentManagement.js`）
| 方法 路径 | 说明 |
|---|---|
| `GET /agent-management/agents?enabled_only=false` | 列表（Library 需含禁用） |
| `POST /agent-management/agents` | 注册（新建自定义 Agent） |
| `PUT /agent-management/agents/:name` | 更新配置 |
| `DELETE /agent-management/agents/:name` | 注销 |
| `GET /agent-management/agents/deps?agents=a,b` | 依赖图 |

---

## 3. M3 流水线 / DAG 画布

### 3.1 实体
```ts
type NodeType = 'trigger'|'investigate'|'forensic'|'remediate'|'guardrail'|'hitl'|'end'
interface PipelineNode { node_id: string; type: NodeType; label: string; position: {x:number;y:number}; config?: Record<string,unknown> }
interface PipelineEdge { source: string; target: string }
interface PipelineDef {
  pipeline_id: string; name: string
  nodes: PipelineNode[]; edges: PipelineEdge[]
  status: 'draft'|'validated'|'running'
  requires_guardrail: boolean; requires_hitl: boolean
  created_at: string
}
```

### 3.2 接口契约（⚠️ 接口层真实，执行空壳；全部经 `agentApi.pipeline`）
| 方法 路径 | 说明 | 返回 |
|---|---|---|
| `POST /agent-management/pipeline/validate` `{agents:string[]}` | 图级后端校验 | `{valid:boolean, warnings:string[]}` |
| `POST /agent-management/pipeline/run` `{event_id, agents, use_cache}` | 启动（返回 run_id） | `{run_id, status}` |
| `GET /agent-management/pipeline/run/:runId` | 运行状态 | `currentRun` |
| `POST /agent-management/pipeline/run/:runId/cancel` | 取消 | `{code:0}` |
| `POST /agent-management/pipeline/run/:runId/resume` `{approved, comment}` | 恢复 HITL 暂停 | `{code:0}` |
| `GET /agent-management/pipeline/run/:runId/stream` | SSE URL（非请求） | `/agent-management/pipeline/run/:runId/stream` |
| `GET /agent-management/pipeline/presets` | 预置模板 | `Preset[]` |

> 🔶 画布种子（DAG 初始示例）由 `pipelineMock.getSample()` 提供（对齐 demo `mocks/pipelines.ts`），后端就绪后切换为真实 presets。
> 前端额外图级校验：环检测（Kahn）+ 必须含 `guardrail`/`hitl` 节点（镜像 demo `usePipelineStore.validate`）。

---

## 4. M4 工具与 MCP（🔶 Mock）

### 4.1 实体
```ts
type ToolStatus = 'available'|'degraded'|'disabled'
interface ToolDef {
  tool_id: string; name: string; description: string
  schema: Record<string, unknown>      // JSON Schema
  idempotency_key: string              // 反空壳：防重复执行破坏性动作
  timeout_ms: number; retries: number
  category: string; mcp_server_id?: string; status: ToolStatus
}
interface McpServer {
  server_id: string; name: string
  transport: 'stdio'|'sse'; status: 'online'|'offline'|'degraded'
  tools_count: number; last_heartbeat: string
}
```

### 4.2 接口契约（经 `toolsMock`）
| 方法 路径 | 说明 | 返回 |
|---|---|---|
| `GET /tools` 🔶 | 工具清单 | `ToolDef[]` |
| `GET /mcp/servers` 🔶 | MCP 服务器状态 | `McpServer[]` |

> 后端 F1 就绪后：`agentApi.tools` 切换为真实端点，字段严格对齐 `ToolDef`（schema / 幂等键 / 超时 / 重试）。

---

## 5. M5 记忆与 RAG（🔶 Mock）

### 5.1 实体
```ts
interface KnowledgeBase {
  kb_id: string; name: string
  embedding_model: string; vector_store: string   // Chroma / pgvector
  doc_count: number; updated_at: string
}
```

### 5.2 接口契约
| 方法 路径 | 说明 | 返回 |
|---|---|---|
| `GET /memory/knowledge-bases` 🔶 | 知识库/向量库概览 | `KnowledgeBase[]` |

> 可选复用现有 `knowledge.js` 作种子数据；后端 F3 就绪切换真实端点。

---

## 6. M6 人工审核台（✅ 真实，复用 `agentOrchestration.js`）

### 6.1 实体 `HitlTask`（对齐 `hitl_approval` 表）
```ts
type HitlDecision = 'pending'|'approved'|'rejected'
interface GuardrailResult {       // HITL 上下文面板联动字段
  policy_id: string
  whitelist_hit: boolean
  requires_confirm: boolean
  requires_rollback_plan: boolean
  passed: boolean
}
interface HitlTask {
  approval_id: string; run_id: string; agent_name: string
  action: string; impact_scope: string
  context: Record<string, unknown>
  guardrail_result: GuardrailResult     // Q2 预留接口位：直接渲染
  status: HitlDecision
  assigned_to?: 'analyst'|'soc_lead'|'admin'
  created_at: string; decided_at?: string; reason?: string
}
```

### 6.2 接口契约（✅ 真实）
| 方法 路径 | 说明 | 返回 |
|---|---|---|
| `GET /agents/approvals?status=pending` | 待审队列 | `{items:HitlTask[], total:number}` |
| `POST /agents/runs/:runId/approve` `{approval_id, decided_by?}` | 批准（后端 resume） | `{code:0,data}` |
| `POST /agents/runs/:runId/reject` `{approval_id, reason?}` | 拒绝 | `{code:0,data}` |

> `approve`/`reject` 成功后，前端 store 联动 `useAgentManagementStore` 刷新运行态（镜像 demo `useHitlStore` → `useAgentStore.resumeRun/cancelRun`）。HITL 上下文面板的护栏联动：`hitlTask.guardrail_result` 已由后端随任务返回；若后端未带，则前端调 `agentApi.guardrail.evaluate(action, context)` 计算（当前 Mock，后端就绪零改动）。

---

## 7. M7 护栏与安全（🔶 Mock — F8 P0 硬前提）

### 7.1 实体
```ts
interface GuardrailPolicy {
  policy_id: string; name: string
  action_pattern: string          // 如 'host:isolate:*'
  whitelist: string[]             // action 白名单（命中可自动放行）
  risk_level: 'low'|'medium'|'high'|'critical'
  require_confirm: boolean        // 强制人工确认
  rollback_plan: string           // 回滚预案
  enabled: boolean
}
interface GuardrailHit {
  policy_id: string; run_id: string
  action: string; passed: boolean; timestamp: string
}
```
`GuardrailResult`（计算产物，见 M6 §6.1）由 `evaluate()` 返回。

### 7.2 接口契约（经 `guardrailMock`）
| 方法 路径 | 说明 | 返回 |
|---|---|---|
| `GET /agent-guardrails/policies` 🔶 | 策略列表 | `GuardrailPolicy[]` |
| `POST /agent-guardrails/policies` 🔶 | 新增策略 | `GuardrailPolicy` |
| `PUT /agent-guardrails/policies/:id` 🔶 | 更新策略 | `GuardrailPolicy` |
| `DELETE /agent-guardrails/policies/:id` 🔶 | 删除策略 | `{code:0}` |
| `POST /agent-guardrails/evaluate` 🔶 `{action, context}` | 计算护栏结果 | `GuardrailResult` |
| `GET /agent-guardrails/hits` 🔶 | 命中记录（M1 护栏拦截数） | `GuardrailHit[]` |

### 7.3 `evaluate()` 算法约定（Mock 实现，严格对齐方案语义）
1. 按 `action` 匹配 `action_pattern`（通配 `*`）。
2. 命中策略后：`whitelist_hit = whitelist.includes(action)`。
3. `requires_confirm = policy.require_confirm`；`requires_rollback_plan = !!policy.rollback_plan`。
4. `passed = !(!whitelist_hit && risk_level 高危且未配回滚预案)`（即白名单命中或具备确认+回滚预案视为通过）。
5. 返回 `GuardrailResult`。字段与 demo `mocks/hitl.ts` 的 `guardrail_result` 完全一致。

---

## 8. M8 可观测性（✅ 真实 run + 🔶 Mock trace/log）

### 8.1 实体
```ts
interface TraceSpan { span_id: string; parent_id?: string; name: string; started_at: string; duration_ms: number }
interface LogEntry { ts: string; level: 'debug'|'info'|'warn'|'error'; message: string }
interface ObservabilityRun {
  run_id: string; agent_name: string
  trace: TraceSpan[]; logs: LogEntry[]
  resume_point?: string          // F9 续跑点（中断恢复）
}
```
> `AgentRun` / `AgentRunStep` 实体见 `agent-orchestration-preview/src/types/agent.ts`（与后端 `AgentRun`/`AgentRunStep` 落库一致），此处不重复。

### 8.2 接口契约
| 方法 路径 | 说明 | 返回 |
|---|---|---|
| `GET /agents/runs/:runId` ✅ | 运行详情（含 steps[]） | `AgentRun` |
| `GET /api/agents/runs/:runId/stream` ✅ | SSE（`step_*` 协议，复用 `useSSE`） | 事件流 |
| `GET /agents/runs/:runId/observability` 🔶（经 `observabilityMock.getRun`） | trace/log/resume_point | `ObservabilityRun` |

> 作为 `AgentRunDetailView` 的「可观测性」Tab 数据源；后端 F7 就绪后 `observabilityMock` 切换为真实端点。

---

## 9. M9 设置（🔶 Mock — F10/F14）

### 9.1 实体
```ts
interface ModelProfile { profile_id: string; name: string; provider: string; model: string; enabled: boolean }
interface DeploymentConfig {
  stateless_enabled: boolean          // F14 无状态开关
  redis_connected: boolean
  sse_protocol: string                // 'step_* (Orchestrator 统一)'
  hitl_protocol: string               // 'hitl_approval + resume'
}
```

### 9.2 接口契约（经 `settingsMock`）
| 方法 路径 | 说明 | 返回 |
|---|---|---|
| `GET /settings/model-profiles` 🔶 | 多模型 profile（F10） | `ModelProfile[]` |
| `GET /settings/deployment` 🔶 | 部署配置（F14/协议状态） | `DeploymentConfig` |

> 复用现有 `settings/AgentManagement.vue` 布局作入口；后端 F10/F14 就绪切换真实端点。

---

## 10. demo store 方法 → 真实端点 / Mock 实现 映射表

| demo store 方法（Zustand） | 模块 | 真实端点 | Mock 实现 |
|---|---|---|---|
| `useAgentStore.fetchAgents` | M2 | `GET /agent-management/agents` | — |
| `useAgentStore.addAgent` | M2 | `POST /agent-management/agents` | — |
| `useAgentStore.fetchRuns` | M1/M8 | `GET /agents/runs` | — |
| `useHitlStore.fetchTasks` | M6 | `GET /agents/approvals` | `guardrail_result` 来自 `guardrailMock.evaluate` |
| `useHitlStore.approve` | M6 | `POST /agents/runs/:id/approve` | — |
| `useHitlStore.reject` | M6 | `POST /agents/runs/:id/reject` | — |
| `usePipelineStore.seedFromSample` | M3 | `GET /agent-management/pipeline/presets` | `pipelineMock.getSample` |
| `usePipelineStore.validate` | M3 | `POST /agent-management/pipeline/validate` | — |
| `usePipelineStore.run` | M3 | `POST /agent-management/pipeline/run` | — |
| `getGuardrailPolicies` | M7 | — | `guardrailMock.listPolicies` |
| `getGuardrailHits` | M7/M1 | — | `guardrailMock.listHits` |
| `getTools` / `getMcpServers` | M4 | — | `toolsMock.listTools/listMcpServers` |
| `getKnowledgeBases` | M5 | — | `memoryMock.listKnowledgeBases` |
| `getObservabilityRun` | M8 | `GET /agents/runs/:id/observability` | `observabilityMock.getRun` |
| `getModelProfiles` / `getDeploymentConfig` | M9 | — | `settingsMock.listModelProfiles/getDeploymentConfig` |
| `getDashboardStats` | M1 | `GET /agents/runs` + `GET /agents/stats` | `dashboardMock.getTrend/getGuardrailBlocks` |

---

## 11. Mock 适配器统一接口约定

### 11.1 统一返回与延迟（镜像 demo `mocks/util.ts`）
```js
// src/api/agent/mock/util.js
export const delay = (min = 100, max = 400) => new Promise(r => setTimeout(r, Math.floor(min + Math.random() * (max - min))))
export const clone = (v) => JSON.parse(JSON.stringify(v))
export const ok = (data) => ({ code: 0, data, message: 'ok' })
// 可选错误模拟（默认关闭，Vitest 开启）
export const THROW_ON = { rate: 0, map: {} }
```

### 11.2 `createGuardrailMock()` 对外方法签名与返回
```js
// 返回结构：所有方法 => Promise<{code,data,message}>
{
  listPolicies(): Promise<{code,data:GuardrailPolicy[],message}>     // 内存数组
  createPolicy(p: Omit<GuardrailPolicy,'policy_id'>): Promise<{code,data:GuardrailPolicy}>
  updatePolicy(p: GuardrailPolicy): Promise<{code,data:GuardrailPolicy}>
  deletePolicy(id: string): Promise<{code,data:null}>
  evaluate(action: string, ctx?: Record<string,unknown>): Promise<{code,data:GuardrailResult}>
  listHits(): Promise<{code,data:GuardrailHit[]}>
}
```
- **时延**：`delay(100,400)`（模拟网络）。
- **错误模拟**：`evaluate` 在 `THROW_ON.rate>0` 时按概率 reject（用于 SSE/HITL 异常路径测试）。
- **内存状态**：模块内 `let POLICIES = [...]` 可变，CRUD 即时生效，会话内持久（刷新页面重置，符合预览态）。

### 11.3 其它 Mock 模块方法（同构）
- `toolsMock`：`listTools()` → `ToolDef[]`；`listMcpServers()` → `McpServer[]`。
- `memoryMock`：`listKnowledgeBases()` → `KnowledgeBase[]`。
- `settingsMock`：`listModelProfiles()` → `ModelProfile[]`；`getDeploymentConfig()` → `DeploymentConfig`。
- `dashboardMock`：`getTrend()` → `{ts,success_rate}[]`（近 7 日）；`getGuardrailBlocks()` → `number`（由 `guardrailMock.listHits` 中 `!passed` 计数）。
- `observabilityMock`：`getRun(runId)` → `ObservabilityRun`（按 `runId` 命中 demo `OBSERVABILITY_RUNS`，缺省返回空 trace）。

### 11.4 替换原则（零改动契约）
所有 Mock 函数签名 = 未来真实 API 的 `async (params) => {code,data,message}`。后端就绪时：
1. 在 `src/api/agent/` 新增对应真实实现（或在 `real.js` 补方法）；
2. 将 `mock-config.js` 对应键置 `false`；
3. `agentApi` 内部路由自动切换；**store 与组件代码零改动**。
