# 方案 B — 开发记录（02-dev）

按 `01-design.md` 落地，记录关键代码变更与实现要点。

## 1. 后端：`backend/app/api/agents.py`

### 1.1 `list_agents` 增加 `case_id` 过滤
```python
@router.get("/agents")
def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    case_id: Optional[int] = Query(None, description="按案件过滤；不传则返回全平台"),
    current_user: dict = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    with get_connection() as conn:
        if case_id is not None:
            count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM hosts WHERE case_id=?", (case_id,)
            ).fetchone()
            rows = conn.execute(
                "SELECT h.id AS host_id, h.hostname, h.case_id, h.ip_address, h.os_type, "
                "       a.agent_id, a.agent_version, a.last_heartbeat, a.token_hash, a.token_created_at "
                "FROM hosts h LEFT JOIN agents a ON h.id = a.host_id "
                "WHERE h.case_id = ? "
                "ORDER BY COALESCE(a.last_heartbeat, '') DESC, h.id DESC "
                "LIMIT ? OFFSET ?",
                (case_id, page_size, offset),
            ).fetchall()
        else:
            # 原全量分支（保持兼容）
            ...
    # 归一化 status / token_set，剔除 token_hash（同原逻辑）
```
要点：`case_id` 缺省走原全量分支，**零行为破坏**；过滤分支共用同一套归一化与脱敏逻辑。

### 1.2 `get_agent_stats` 增加 `case_id` 过滤
统计 total/online/offline 三子查询均追加 `WHERE h.case_id = ?`；`online` 窗口仍为 `_ONLINE_WINDOW_SECONDS`（90s）。缺省走全量分支。

## 2. 前端 API 透传

### 2.1 `frontend/src/api/agents.js`
```js
export function getAgentStats(params) {
  return request.get('/agents/stats', { params })
}
```
（原为 `getAgentStats()` 无参；加 `params` 后，旧调用 `getAgentStats()` 传 `undefined` 仍正常。）

### 2.2 `frontend/src/api/agent/index.js`
```js
stats: {
  getAgentStats: (params) => getAgentStats(params),  // 原 () => getAgentStats()
},
```
`agents.list` 已支持 `params`，无需改。

## 3. 新建 `frontend/src/views/CaseAgentView.vue`

- 复用 `AgentManagement.vue` 的结构（统计卡片、`el-table`、Token 弹窗、复制逻辑）。
- 顶部新增案件选择器 `el-select`（filterable + clearable）：
  - 选项来自 `casesApi.list(1, 200, '')` → `{ id, name }`；
  - 固定首项「全部案件（全平台）」`value='ALL'`；v-model 初始 `''`（空态）。
- `caseIdParam()`：`'ALL'` 或不选 → `undefined`（全平台）；数字 → `case_id`。
- `onCaseChange()`：切换时重置分页，未选 → 清空列表/统计并显示空态；选定 → 拉取列表 + 统计。
- `fetchAgents()`：参数 `{ page, page_size, case_id? }`。
- `fetchStats()`：`agentApi.stats.getAgentStats(case_id ? { case_id } : undefined)`。
- 标题区显示当前范围标签：选具体案件显示案件名，选「全部」显示「全平台」。

## 4. 路由与菜单

### 4.1 `frontend/src/router/index.js`
- 新增（在 `cases/:id` 之后）：
  ```js
  { path: 'case-agents', name: 'CaseAgentView',
    component: () => import('@/views/CaseAgentView.vue'), meta: { title: '案件主机 Agent' } }
  ```
- 移除 `settings` 父路由下的 `agents` 子路由（`name: 'AgentManagement'`）。

### 4.2 `frontend/src/components/AppLayout.vue`
- 「案件管理」组 children 增加：
  `{ icon: Monitor, label: '主机 Agent', path: '/case-agents', activeMatch: '/case-agents' }`
- 「系统设置」组 children 删除 `{ icon: Monitor, label: '主机 Agent', path: '/settings/agents' }`。
- `routeMeta` 增加 `'CaseAgentView': { title: '案件主机 Agent', subtitle: '案件维度主机 Agent 客户端管理与监控' }`。

### 4.3 `frontend/src/views/settings/SettingsLayout.vue`
- 子侧栏 `menuItems` 删除 `主机 Agent` 项；清理未使用的 `Monitor` 图标导入（避免 lint 报错）。

### 4.4 删除弃用文件
- `frontend/src/views/settings/AgentManagement.vue`：确认无任何引用（`grep AgentManagement.vue` 无结果）后删除，由 `CaseAgentView.vue` 取代。

## 5. 实现要点 / 踩坑

- **路由抢占**：`cases/:id` 会吞掉 `cases/agents`，故新路径用 `/case-agents`（顶层），不挂在 `cases` 父路径下。
- **API 模块真相**：`AgentManagement.vue` 引用的 `@/api/agent` 实际是目录模块 `frontend/src/api/agent/index.js`（`agentApi.agents` / `agentApi.stats` 命名空间），并非 `agents.js`。新视图沿用同一命名空间，并修正 `stats.getAgentStats` 透传参数。
- **Monitor 图标**：从 SettingsLayout 移除后必须同步清理导入，否则出现未使用导入（Vue/Vite 不报错但 lint 会告警）。

## 6. 未纳入本次范围（记录）

- 权限闸：生成/重置 Token 暴露到「案件管理」分组，未在后端加角色限制，后续建议补充。
- 「案件详情」内嵌 Agent 子页：本次用独立 `/case-agents` + 案件选择器实现，未改造 `CaseDetailView` 布局。
