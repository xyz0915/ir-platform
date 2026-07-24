# 智能体编排管理 · 集成 PRD（产品需求文档）

> 文档类型：简单 PRD（集成基线，默认规格）
> 产出角色：产品经理（许清楚 / Xu）
> 输入依据：
> - 《智能体编排管理 — 优化后方案》（单底座策略 · Orchestrator 唯一执行引擎 · F1–F14 · M0–M4）
> - 前端功能预览 demo（`agent-orchestration-preview/`，React+MUI+Zustand，9 模块目标态原型）及 `docs/prd.md`、`docs/arch.md`
> - 平台现有前端代码：`frontend/src/api/*.js`（接口层）、`frontend/src/views/*`（既视视图）、`frontend/src/router/index.js`（路由体系）
> 集成路线（已确认）：**原生移植到 Vue**——用 Vue3 + Element Plus + Pinia 重写 9 模块并入 `frontend/` 的 `agent-orchestration` / `agent-management` 路由体系，优先接真实 API，缺失能力用 Mock 适配器占位。
> 适用范围：本文件仅定义**产品需求与集成范围基线**，不含技术架构与代码实现。

---

## 1. 项目信息

| 项 | 值 |
|---|---|
| Language | 简体中文 |
| Programming Language | Vue 3 + Element Plus + Pinia + vue-router + ECharts + Vite（平台既定栈，Vitest 测试） |
| Project Name | `agent_orchestration_integration` |
| 原始需求复述 | 将 React/MUI 预览 demo 的 9 个「智能体编排管理」目标态模块，原生移植进 IR 平台 Vue3/Element Plus 体系，复用既有 `AgentRunView`/`AgentManagementView` 等可用实现，接入真实后端（优先 `agentOrchestration.js`/`agentManagement.js` 已有接口），缺失能力（tools/memory/guardrail/settings 多模型·无状态/dashboard 聚合）以 Mock 适配器占位，后续零改动替换；pipeline 作为配置/DAG 定义层接入 Orchestrator 单底座。 |

---

## 2. 产品目标

**一句话目标**：把分散的 `agent-orchestration` / `agent-management` / `settings/agents` 收敛为 demo 定义的 **9 模块统一「智能体编排管理中心」**，复用既有可用视图、按真实后端优先 + Mock 占位的策略落地，并满足「安全主线（HITL + 护栏）是上线硬前提」的约束。

**具体目标（3–5 条）**：

1. **统一入口与信息架构**：以 demo 的 9 模块 IA（侧边栏导航 + 暗色 SecOps 视觉 + 3 条核心流程）为基线，重构导航结构，复用而非重写既有可用视图，降低重复建设。
2. **真实对接优先、Mock 平滑占位**：优先用现有 `agentOrchestration.js` / `agentManagement.js` 真实接口驱动 agents / HITL / observability / pipeline；tools / memory / guardrail / settings 缺失能力用 Mock 适配器占位，且 Mock 严格对齐方案真实字段语义（`AgentRun`/`AgentRunStep`/`hitl_approval`/`GuardrailPolicy`/`ToolDef`/`PipelineDef`…），后端就绪后仅替换数据层、业务组件零改动。
3. **安全主线落地（上线硬前提）**：在前端形成「高风险动作必经 HITL 审批 + 护栏校验（F8 P0）」的交互链路——HITL 上下文面板需展示护栏命中/白名单/高危确认结果，guardrail 模块提供策略配置入口。
4. **单底座对齐**：pipeline 模块作为「配置/DAG 定义层」接入 Orchestrator；废弃 PipelineEngine 坏实现的前端执行调用，跟随 M0/M1 收敛（接口层做适配抽象，避免前端硬编码 PipelineEngine 协议）。
5. **可观测与可治理**：observability 复用 `AgentRunView`/`AgentRunDetailView` 并增强（trace 树 / 结构化日志 / 续跑点），使 Agent 跑飞、工具失败可定位。

---

## 3. 用户故事

> 视角：安全运营人员（分析师）/ 平台管理员（编排管理员）/ SOC 主管。

### 3.1 概览 Dashboard（M1）
- 作为**安全运营人员**，我要在概览页一眼看到当前运行中智能体数、成功率、待我审核的 HITL 数、护栏拦截数，以便优先处理高风险动作。
- 作为**SOC 主管**，我要查看团队整体运行成功率与近期运行趋势，用于向上汇报与容量决策。

### 3.2 智能体管理（M2）
- 作为**平台管理员**，我要浏览内置 + 自定义 Agent 列表，并通过详情抽屉查看其配置（工具 / 数据来源 / 依赖），理解每个 Agent 的能力边界。
- 作为**平台管理员**，我要新建自定义 Agent（配置 display_name / 数据来源 / 依赖 / 关联工具与模型），并确认它走真实 `AgentLLM` 通道执行（非空壳）。

### 3.3 流水线编排 / DAG 画布（M3）
- 作为**编排管理员**，我要用 DAG 画布拖拽节点（调查/取证/处置/护栏/HITL）、连线定义流转，校验闭环（含护栏节点）后提交给 Orchestrator 执行，做到「所见即所得」。

### 3.4 工具与 MCP（M4）
- 作为**平台管理员**，我要在工具/MCP 页查看已注册工具的 schema、幂等键、超时与 MCP 服务器在线状态，确认 F1 工具生态的接入情况。

### 3.5 记忆与 RAG（M5）
- 作为**平台管理员**，我要查看智能体长期记忆 / 知识库概览与检索增强效果，理解跨案件经验沉淀能力。

### 3.6 人工审核台（M6）
- 作为**安全运营人员**，我在人工审核台收到待审任务时，要查看完整上下文（触发智能体 / 拟执行动作 / 影响范围 / 护栏校验结果）后做出批准或拒绝，避免误操作破坏性指令。

### 3.7 护栏与安全（M7）
- 作为**平台管理员 / SOC 主管**，我要在护栏页确认 action 白名单与高危动作确认 / 回滚预案已就位，确保 F8（P0）上线前提被满足。

### 3.8 可观测性（M8）
- 作为**安全运营人员**，我要在可观测性时间线回看某次运行的 step / trace / 结构化日志 / 续跑点，定位智能体跑飞或工具失败的原因。

### 3.9 设置（M9）
- 作为**平台管理员**，我要在设置中配置多模型 profile（F10）与切换无状态部署开关（F14），作为 M0/M3 相关能力的入口，并查看 SSE/HITL 协议对齐状态。

---

## 4. 需求池（P0 / P1 / P2）

> 优先级定义：P0 = 集成必须包含（M0 硬前置 + 安全主线 + 既有可用视图）；P1 = 应包含（核心能力展示，M1–M2）；P2 = 可后置（完整性补充，M3）。
> 「后端对接判断」依据 `frontend/src/api/*.js` 是否已有对应接口：
> - ✅ 真实后端：已有可调用接口；
> - ⚠️ 真实后端（接口层，执行待收敛）：接口存在但后端执行路径为 PipelineEngine 空壳，需 M1 收敛；
> - 🔶 Mock 占位：无对应接口，用 Mock 适配器，后端就绪后替换。

| # | 模块 | 优先级 | 映射（方案依据） | 后端对接判断（依据 api 文件） | 关键交付 |
|---|---|---|---|---|---|
| M1 | **概览 Dashboard** | **P0** | Observability F7 / HITL F6 / M0 实时性 | 🔶 **部分真实 + Mock**：无独立聚合端点；运行列表/统计可由 `agentOrchestration.listAgentRuns` + `agents.getAgentStats` 组合；趋势/护栏拦截数需 Mock 或后端新增聚合端点 | 指标卡（运行中/成功率/待审 HITL/护栏拦截）、近期运行列表、运行趋势图 |
| M2 | **智能体管理** | **P0** | 自定义 Agent F2 / M0 修空壳 | ✅ **真实后端**：`agentManagement.listAgents / createAgent / updateAgent / deleteAgent` 已存在（后端自定义 Agent 修空壳属 M0 后端范畴，前端按真实接口对接） | 卡片列表（内置+自定义）、详情抽屉、新建/编辑表单（工具/数据源/依赖） |
| M3 | **流水线编排（DAG 画布）** | **P1** | PipelineEngine 配置层 / F11 / M1 | ⚠️ **真实后端（接口层，执行待收敛）**：`agentManagement.validatePipeline / runPipeline / getRunStatus / cancelRun / resumeRun / getPipelineSSEUrl / listPresets` 已存在，但执行路径为 PipelineEngine 空壳；组件 `GraphPanel.vue` 已存在（未接执行）；需 M1 收敛到 Orchestrator | DAG 画布视图、节点面板（拖拽/连线）、校验/运行、复用 GraphPanel |
| M4 | **工具与 MCP** | **P1** | ToolRegistry F1 / M2 | 🔶 **Mock 占位**：无对应接口（F1 后端未建）；用 Mock 适配器，后续替换 | 工具列表（schema/幂等键/超时/重试）、MCP 服务器状态、在线状态 |
| M5 | **记忆与 RAG** | **P2** | MemoryLayer F3 / M3 | 🔶 **Mock 占位**：无对应接口（F3 后端未建）；可酌情复用 `knowledge.js`（知识库）作种子数据 | 知识库/向量库概览、嵌入模型选择、检索增强示意 |
| M6 | **人工审核台（HITL）** | **P0** | 统一 HITL F6 / M0 | ✅ **真实后端**：`agentOrchestration.listPendingApprovals / approveAgentRun / rejectAgentRun` 已存在；resume 经 `agentManagement.resumeRun` + `getSSEUrl` | 待审队列、上下文面板（动作/影响范围/护栏联动）、approve/reject、角标同步 |
| M7 | **护栏与安全** | **P0** | Guardrails F8 (P0) / M2 | 🔶 **Mock 占位**：无对应接口（F8 后端未建，但为上线 P0 硬前提）；用 Mock 适配器，并在 HITL 上下文面板预留护栏校验接口位 | 策略列表、action 白名单、高危动作确认/回滚预案配置、与 HITL 联动展示 |
| M8 | **可观测性** | **P0** | Observability F7 / F9 续跑 / M2 | ✅ **真实后端**：`agentOrchestration.listAgentRuns / getAgentRun / getSSEUrl` 已存在；trace/日志/续跑点字段需后端 F7 补齐，前端先复用现有 detail 并增强 | 运行时间线、trace 树、结构化日志、续跑断点示意（复用 AgentRunDetailView 增强） |
| M9 | **设置** | **P1** | AgentLLM 多模型 F10 / F14 无状态 / M0·M3 | 🔶 **Mock 占位（配置项）**：多模型 profile / 无状态开关后端未建（F10/F14），用 Mock；可复用 `settings/AgentManagement.vue` 布局 | 多模型 profile 配置、无状态部署开关、SSE/HITL 协议对齐状态展示 |

### 4.1 优先级汇总

- **P0（必须进，M0 + 安全主线 + 既有可用）**：M1 Dashboard、M2 智能体管理、M6 人工审核台、M7 护栏与安全、M8 可观测性。
- **P1（M1–M2 核心能力）**：M3 流水线编排（DAG 画布）、M4 工具与 MCP、M9 设置。
- **P2（M3 完整性补充）**：M5 记忆与 RAG。

---

## 5. 集成范围边界

> 明确三类边界：**① 复用现有 Vue 实现**（既有可用视图/组件，增强而非重写）；**② 移植 demo 交互与信息架构**（9 模块的目标态 IA、SecOps 暗色视觉、3 条核心流程、组件规范，从 React/MUI 落到 Vue/Element Plus）；**③ 新增**（全新视图/路由，无既有 Vue 实现）。

| 模块 | ① 复用现有 Vue 实现 | ② 移植 demo 交互/信息架构 | ③ 新增视图/路由 |
|---|---|---|---|
| M1 Dashboard | — | 指标卡/趋势/近期运行列表结构、暗色 SecOps 视觉 | 全新路由视图（聚合首屏） |
| M2 智能体管理 | `AgentManagementView`（Agent Library）+ `agentManagement.js` 接口 | 卡片列表、详情抽屉、新建表单（工具/数据源/依赖勾选）交互 | 详情抽屉 / 新建表单组件（增强现有视图） |
| M3 流水线编排 | `GraphPanel.vue`（已存在未接执行）+ `AgentManagementView` Pipeline Builder 思路 + `agentManagement.js` pipeline 接口 | DAG 画布拖拽/连线/校验/运行流程 | DAG 画布视图（配置/DAG 定义层，接入 Orchestrator） |
| M4 工具与 MCP | — | 工具列表、MCP 服务器状态卡、schema 预览 | 全新路由视图（Mock） |
| M5 记忆与 RAG | （可选）`knowledge.js` 作种子数据 | 知识库/向量库概览、检索增强示意 | 全新路由视图（Mock） |
| M6 人工审核台 | `AgentRunView` 内嵌 `HitlApprovalPanel` 组件 + `agentOrchestration.js` 接口 | HITL 模块 IA（队列 + 上下文面板 + 护栏联动 + approve/reject 流程） | HITL 专属页面（从 AgentRunView 抽取/增强） |
| M7 护栏与安全 | — | 策略列表、白名单、高危确认/回滚预案展示 | 全新路由视图（Mock 占位，F8） |
| M8 可观测性 | `AgentRunView` + `AgentRunDetailView` + `agentOrchestration.js` 接口 | observability IA（trace 树 / 日志 / 续跑点 / 时间线） | 增强现有 `AgentRunDetailView`（非从零） |
| M9 设置 | `settings/AgentManagement.vue`（`settings/agents` 布局） | 多模型 profile / 无状态开关 / SSE·HITL 协议状态展示 | 模块级 run/observability 配置项（Mock） |

**边界原则**：
- 凡是 `frontend/src/views` 已有且可用的视图（AgentRunView / AgentRunDetailView / AgentManagementView / settings/AgentManagement.vue）**优先复用并增强**，不重写。
- demo 提供的 9 模块目标态 IA、视觉规范、3 条核心流程、组件约定（StatusBadge/StatCard/StepFlow/GuardrailChip 等）**移植**为 Vue/Element Plus 等价实现，对齐平台既有 CSS 变量（`--color-*`）。
- 既有视图缺失的 5 个模块（dashboard / tools / memory / guardrail / settings 模块级）及 DAG 画布视图、HITL 专属页面为**新增**。

---

## 6. 待确认问题（需架构师/用户澄清）

1. **现有视图整合方式（合并 vs 并存）**：demo 的 `agents` 模块（含详情抽屉/新建表单/工具配置）与现有 `AgentManagementView`（Pipeline Builder + Agent Library + Execution History 三 Tab）如何整合？是**增强现有视图**还是**新增独立 `agents` 路由**？同理，HITL 模块与 `AgentRunView` 内嵌 `HitlApprovalPanel` 是抽取为独立页面还是保留内嵌并新增入口？
2. **guardrail 缺失后端的 Mock 契约形态**：F8 护栏后端未建，Mock 适配器应暴露什么接口契约（policy CRUD？`guardrail_result` 计算逻辑？），以便后端就绪后**零改动替换**？前端如何在 HITL 上下文面板预留护栏校验联动的接口位（字段：`whitelist_hit` / `requires_confirm` / `requires_rollback_plan` / `passed`）？
3. **pipeline DAG 画布与 PipelineEngine 的收敛节奏**：现有 `agentManagement.js` 的 pipeline 执行接口走 PipelineEngine（空壳）；优化方案要求 M1 收敛到 Orchestrator。前端 DAG 画布应**直接对接 Orchestrator** 还是暂保留 pipeline 接口并在 M1 切换？是否需前端做**接口适配抽象层**（隔离 PipelineEngine/Orchestrator 协议差异）？
4. **observability 路由形态**：demo 的 observability 是独立模块（trace 树/日志/续跑点），但平台已有 `/agent-orchestration/:runId`（AgentRunDetailView）。是把 observability 作为该详情页的**增强 Tab**，还是新增独立 `/observability` 路由？涉及路由体系是否扩展。
5. **dashboard 聚合数据来源**：首屏趋势/成功率/护栏拦截数无独立聚合 API，是用 `listAgentRuns` + `getAgentStats` **前端组合聚合**，还是后端**新增聚合端点**？SSE 实时刷新机制如何对接 `getSSEUrl` 与现有 `useSSE.js`（需确认前端 SSE 监听是否仍走 `step_*` 协议）。

---

> 备注：本 PRD 仅定义产品需求与集成范围基线，不含技术架构与代码实现（由架构师负责）。

---

——以下架构与接口规范由架构师补充——
