# 方案 B：主机 Agent 迁移至「案件管理」并收敛到案件维度 — 设计

> 关联决策：用户确认采用「方案 B（挪动 + 案件维度收敛）」，取代先前评估中的方案 A（仅挪菜单）与方案 C（保留全局页、仅增强主机详情）。
> 目标：把 `主机 Agent` 入口从「系统设置」栏移到「案件管理」栏下，并使数据按案件（case）收敛，避免「全局视角放在案件分组下」的语义错配与上下文错乱。

## 1. 现状与问题（设计依据）

| 维度 | 现状 |
|------|------|
| 菜单入口 | `主机 Agent` 同时出现在两处：主侧栏 `AppLayout.vue`（`系统设置` 组）、子侧栏 `SettingsLayout.vue`（`/settings/agents` 渲染其中） |
| 路由 | `/settings/agents` 的父级是 `settings` → 组件 `SettingsLayout.vue`；点进去仍显示「系统设置」子侧栏 |
| 页面数据 | `AgentManagement.vue` 调用 `GET /agents` 与 `GET /agents/stats`，均为**全平台、无 `case_id` 过滤** |
| 重叠能力 | `HostDetailView` 已有逐主机「下载 Agent」按钮（token 下载） |
| 后端接口 | `list_agents` / `get_agent_stats` 以 `hosts` 为主表 LEFT JOIN `agents`，SELECT 已带 `case_id`，但不接受 `case_id` 入参 |

**核心痛点**：若仅把菜单项挪到「案件管理」（方案 A），会出现两个硬伤——
1. 数据仍是全平台，放在「案件管理」下会误导用户以为"这个案件的主机"；
2. 路由父级未动，点进去仍渲染「系统设置」子侧栏，上下文错乱。
因此采用方案 B：迁移 + 案件维度收敛。

## 2. 目标态（方案 B）

- 入口：在「案件管理」组新增 `主机 Agent`（`/case-agents`）；从「系统设置」组（主侧栏 + SettingsLayout 子侧栏）彻底移除。
- 数据：新建 `CaseAgentView.vue`，顶部提供「案件选择器」（默认空态提示选案件；含「全部案件（全平台）」作为显式 opt-in），选定后按 `case_id` 调用接口，仅展示该案件主机 Agent。
- 后端：`GET /agents`、`GET /agents/stats` 增加可选 `case_id` 参数；传入时按 `h.case_id = ?` 过滤，不传保持全量（向后兼容）。
- 路由：新增 `/case-agents`（避开 `cases/:id` 的路由抢占）；移除 `settings/agents` 路由；删除弃用 `AgentManagement.vue`。

## 3. 关键设计决策

### 3.1 路由路径选择 `/case-agents`
`cases/:id` 会抢匹配 `cases/agents`（`:id` 吞掉任意段），故新路径用顶层 `/case-agents`，URL 不与案件详情冲突，且天然归属「案件管理」分组。

### 3.2 案件维度收敛方式
- 前端提供案件下拉（来自 `GET /cases`，取 `id`/`name`），选项含「全部案件（全平台）」。
- 选择具体案件 → 请求带 `case_id`；选择「全部」或不传 → 全平台（等价原全局页，运维兜底）。
- 未选择 → 显示 `el-empty` 空态，强制"先看案件再管 agent"的收敛语义。

### 3.3 后端过滤实现
`hosts` LEFT JOIN `agents` 已含 `case_id`，仅需在 count 与 rows 查询追加 `WHERE h.case_id = ?`；统计三子查询同样加 `WHERE h.case_id = ?`。`case_id` 为 `Optional[int]`，缺省走原全量分支（零行为破坏）。

### 3.4 API 透传链
- `frontend/src/api/agents.js`：`getAgentStats(params)` 透传 `params` 到 `GET /agents/stats`。
- `frontend/src/api/agent/index.js`：`stats.getAgentStats` 改为 `(params) => getAgentStats(params)`，保留旧调用 `getAgentStats()` 仍可用（不传参 → 全平台）。

### 3.5 权限（记录为后续项，本次不扩范围）
生成/重置 Token + 部署命令属高敏感操作。方案 B 将其入口暴露到「案件管理」分组，普通案件分析师可见。本次**不改动后端鉴权**（保持 `get_current_user`），仅在验证文档标注该风险，建议后续按角色加闸。

## 4. 影响面评估

| 文件 | 改动 |
|------|------|
| `backend/app/api/agents.py` | `list_agents`、`get_agent_stats` 增加 `case_id` 可选参数与过滤分支 |
| `frontend/src/api/agents.js` | `getAgentStats(params)` 支持透传 |
| `frontend/src/api/agent/index.js` | `stats.getAgentStats` 透传 params |
| `frontend/src/views/CaseAgentView.vue` | 新建：案件选择器 + 统计 + 列表 + Token 弹窗 |
| `frontend/src/router/index.js` | 新增 `case-agents` 路由；移除 `settings/agents` 路由 |
| `frontend/src/components/AppLayout.vue` | 「案件管理」组加 `主机 Agent`；「系统设置」组删；`routeMeta` 加 `CaseAgentView` |
| `frontend/src/views/settings/SettingsLayout.vue` | 子侧栏删 `主机 Agent` 项、清理未用 `Monitor` 导入 |
| `frontend/src/views/settings/AgentManagement.vue` | 删除（被 `CaseAgentView` 取代） |

## 5. 验收标准

1. 主侧栏「系统设置」下无 `主机 Agent`；「案件管理」下有 `主机 Agent`，点击进入 `/case-agents`。
2. `/case-agents` 进入后为空态，需先选案件；选「全部案件（全平台）」展示全平台，等于原全局页。
3. 选定具体案件后，列表与统计仅含该案件主机；无 agent 的主机仍展示（LEFT JOIN）。
4. 后端 `case_id` 过滤正确：传入返回该案件数据，不传返回全量；不存在的 `case_id` 返回空。
5. 前端构建通过，无类型/编译错误。
6. 后端测试 `test_agent_case_scope.py` 全绿。
