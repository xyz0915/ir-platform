# 方案 B — 测试记录（03-test）

## 1. 后端单元测试：`backend/tests/test_agent_case_scope.py`

隔离策略沿用项目既有模式：module-scoped 临时 SQLite（`init_db()` 仅建库一次），每用例前清空 `process_events/file_hashes/network_connections/triage_tasks/agents/hosts/cases`；管理员 JWT 通过 `User.get_by_username("admin")` + `create_token` 生成；仅挂载 `agents` 路由到最小 FastAPI app。

### 播种辅助
- `seed_case(name)`：插入案件，返回 `case_id`。
- `seed_host(case_id, hostname, agent_online)`：在指定案件下插入主机；`agent_online` 为 `True/False/None` 控制是否插入 `agents` 行及 `last_heartbeat`（now / now-10h / 不插）。

> 注意：早期版本把"案件+主机"耦合在一个函数里，导致每次调用都新建案件，使同案件多主机的过滤断言失败（total 少 1）。修正为"先建案件、再往同一案件插主机"后通过——这是测试自身 bug，非后端逻辑问题。

### 用例清单（7 项）
| 用例 | 验证点 |
|------|--------|
| `test_list_all_without_case_id_returns_every_host` | 不传 `case_id` → 全平台 3 台，兼容旧行为 |
| `test_list_filter_by_case_id_returns_only_that_case` | 传 `case_id` → 仅返回该案件 2 台，host_id 集合精确匹配 |
| `test_list_filter_other_case_isolated` | 另一案件仅 1 台，相互隔离 |
| `test_list_host_without_agent_still_listed` | 无 agent 的主机仍展示（LEFT JOIN），`token_set=false` |
| `test_stats_all_without_case_id` | 全量统计 total=3 / online=2 / offline=1 |
| `test_stats_filter_by_case_id` | 按案件统计：caseA total=2/online=1/offline=1；caseB total=1/online=1/offline=0 |
| `test_filter_nonexistent_case_id_returns_empty` | 不存在的 `case_id` → total=0、items=[]，不报错 |

## 2. 前端构建验证

执行 `npx vite build`，全部模块（含新增 `CaseAgentView` 懒加载块）编译通过，无类型/语法错误。
- 构建产物正常生成各 vendor / 视图 chunk。
- 验证点：菜单改动、`CaseAgentView.vue`、API 透传链（`agents.js` / `agent/index.js`）均编译入包。

> 说明：构建使用临时输出目录（避免 `dist/` 的沙箱批量删除保护），验证后清理临时目录。

## 3. 回归验证

合跑既有三阶段测试 + 本方案测试：
`test_phase1_event_type_source.py` + `test_phase2_dynamic_triage.py` + `test_phase3_aggregate_stability.py` + `test_agent_case_scope.py`

结果：**33 passed**（详见 `04-verify.md`）。本次改动不影响既有 daemon 实时推送、动态取证任务、聚合去重等能力。

## 4. 未覆盖（记录）

- 前端交互级 E2E（案件选择器切换、空态、Token 弹窗）通过构建 + 代码审查确认，未引入前端单测框架用例。
- 权限闸（Token 操作暴露到案件管理分组）未在测试中强制，见设计文档风险项。
