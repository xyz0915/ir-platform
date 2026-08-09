# 方案 B — 验证报告（04-verify）

## 1. 验收对照（来自 01-design §5）

| # | 验收标准 | 结果 |
|---|----------|------|
| 1 | 主侧栏「系统设置」下无 `主机 Agent`；「案件管理」下有 `主机 Agent`，进入 `/case-agents` | ✅ 已改 `AppLayout.vue` 两组菜单；路由 `case-agents` 已加 |
| 2 | 进入为空态，需先选案件；「全部案件（全平台）」= 原全局页 | ✅ `CaseAgentView.vue` 默认 `''` 空态 + `ALL` 选项 |
| 3 | 选定案件后列表/统计仅含该案件；无 agent 主机仍展示 | ✅ 后端 `case_id` 过滤 + 测试覆盖 |
| 4 | 后端 `case_id` 过滤：传入返回该案件，不传全量，不存在返回空 | ✅ 7 项后端测试通过 |
| 5 | 前端构建通过，无编译错误 | ✅ `vite build` 成功 |
| 6 | 后端测试 `test_agent_case_scope.py` 全绿 | ✅ 7 passed |

## 2. 测试结果

### 2.1 本方案后端测试
```
tests/test_agent_case_scope.py  7 passed
```

### 2.2 全量回归（四套件合跑）
```
test_phase1_event_type_source.py      7 passed
test_phase2_dynamic_triage.py        10 passed
test_phase3_aggregate_stability.py    9 passed
test_agent_case_scope.py              7 passed
─────────────────────────────────────────
合计                                 33 passed   （123.20s）
```

## 3. 手动验收要点（建议）

- 启动前后端后，左侧导航：「系统设置」分组下已无「主机 Agent」；「案件管理」分组下出现「主机 Agent」。
- 点击进入 `/case-agents`：默认空态提示"请选择案件…"。
- 选择某案件 → 列表仅显示该案件主机，统计卡片随案件变化；点击「全部案件（全平台）」→ 恢复全平台视图（等同原全局页）。
- 点任意主机「生成/重置 Token」→ 弹窗展示明文 Token 与部署命令（行为同原页面）。
- 「系统设置 → 用户与权限/审计日志/…」子侧栏不再含「主机 Agent」。

## 4. 风险与遗留

1. **权限暴露（中）**：Token 生成/重置入口现在位于「案件管理」分组，普通案件分析师可见。后端未加角色闸（仍为 `get_current_user`）。建议后续按角色限制，避免越权下发部署 Token。
2. **临时构建目录**：验证用的 `agent-nav-build/`、`dist-verify/` 构建产物可能因沙箱保护未自动清理，属无害构建产物，建议加入 `.gitignore` 或直接删除。
3. **功能重叠**：主机详情 `HostDetailView` 已有「下载 Agent」按钮；本方案在案件维度新增聚合视图，二者互补（逐主机 vs 案件内聚合），不冲突。

## 5. 交付物清单

- 代码：`backend/app/api/agents.py`、`frontend/src/api/agents.js`、`frontend/src/api/agent/index.js`、`frontend/src/views/CaseAgentView.vue`（新）、`frontend/src/router/index.js`、`frontend/src/components/AppLayout.vue`、`frontend/src/views/settings/SettingsLayout.vue`；删除 `frontend/src/views/settings/AgentManagement.vue`。
- 测试：`backend/tests/test_agent_case_scope.py`（7 用例）。
- 文档：`docs/agent-nav-case/01-design.md`、`02-dev.md`、`03-test.md`、`04-verify.md`。
