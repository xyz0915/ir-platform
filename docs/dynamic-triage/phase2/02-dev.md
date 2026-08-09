# 阶段二 开发文档 — 动态取证任务（方案 A 轮询 + 默认三项 scope）

> 隶属：应急动态取证方案 · Phase 2 / 3 · 开发环节
> 记录本阶段实际落地的代码改动与实现要点。

## 1. 后端 Schema 与迁移（backend/app/database.py）

- 新增 `triage_tasks` 表 DDL（约 `:423-445`），字段见设计文档 §3.1。
- `file_hashes` / `network_connections` 表 DDL 增加 `source TEXT` 列。
- `init_db` 中新增幂等迁移：
  - `_alter_add_column("file_hashes", "source", "TEXT")`
  - `_alter_add_column("network_connections", "source", "TEXT")`
  - （`process_events.source` 已在阶段一迁移中加入）
  - `_alter_add_column` 具备「列已存在则跳过」的幂等保护，存量库安全。

## 2. TriageTask 模型（backend/app/models/triage_task.py，新增）

- `create(host_id, scope)`：`INSERT ... status='pending'`，返回新任务 id。
- `get_pending(host_id)`：取最旧一条 `pending` 并原子 `UPDATE status='running', started_at=now`，返回 `dict`（scope 已 `json.loads`）。无 pending 返回 `None`。
- `list_by_host(host_id)`：按 `id DESC` 列出全部任务；`scope`/`summary` 均 `json.loads` 反序列化（容错）。
- `complete(task_id, summary, error)`：`error` 非空 → `failed`，否则 `done`；写入 `summary` 与 `finished_at`。

## 3. 取证任务 API（backend/app/api/triage_tasks.py，新增）

四个端点，全部返回 `{code,data,message}` 统一信封：

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/hosts/{host_id}/triage-tasks` | 用户 | 下发任务；`scope` 缺省/全非法 → 默认三项 |
| GET | `/hosts/{host_id}/triage-tasks` | 用户 | 查询任务列表 |
| GET | `/hosts/{host_id}/triage-tasks/pending` | agent | daemon 轮询；`assert_host_binding` 校验 |
| POST | `/hosts/{host_id}/triage-tasks/{task_id}/result` | agent | 回传结果并落库 |

- `ALLOWED_SCOPE = {"file_hashes","network","process_subtree"}`，`DEFAULT_SCOPE = ["file_hashes","network","process_subtree"]`。
- 回传处理：
  - `file_hashes` → `_insert_file_hashes`（逐条 INSERT，`source='triage'`）。
  - `network_connections` → `_insert_network`（逐条 INSERT，`source='triage'`；兼容 `local_address`/`remote_address` 别名）。
  - `process_events` → 给每条加 `source='triage'` 后 `ProcessEvent.batch_create(host_id, events)`。
  - 写入为 **追加**（`INSERT`），不删除存量快照。

## 4. 路由注册（backend/app/main.py）

- `from app.api import triage_tasks`
- `app.include_router(triage_tasks.router, prefix="/api", tags=["动态取证"])`

## 5. daemon 采集器（agent/collectors/triage.py，新增）

- `TriageCollector.collect_triage(scope)` 按 scope 复用既有采集器：
  - `file_hashes` → `FilesCollector().collect()`（取 `data["file_hashes"]`）。
  - `network` → `NetworkCollector().collect()` → `_map_network`（映射为 `network_connections` 字段）。
  - `process_subtree` → `ProcessesCollector().collect()` → `_map_processes`（映射为 `event_type='process_start'` 事件）。
- 任一采集器异常仅记录 warning 并降级为空列表，**绝不抛异常拖垮 daemon**。
- 返回结构：`{"file_hashes":[], "network_connections":[], "process_events":[]}`。

## 6. daemon 主循环调度（agent/agent.py）

- 新增常量 `_DAEMON_TRIAGE_POLL_INTERVAL = 30`。
- 新增函数：
  - `_fetch_triage_task(server, token, host_id)`：`GET /pending`，失败（含非 200）返回 `None`。
  - `_report_triage_result(...)`：`POST /{task_id}/result`，返回是否成功。
  - `_maybe_run_triage(server, token, host_id)`：领任务 → `collect_triage(scope)` → 回传；异常时仍以错误体回传，保证任务终态（done/failed）。
- 主循环：初始化 `last_triage_poll_time = 0`；每轮若 `now - last >= 30` 则调用 `_maybe_run_triage` 并刷新时间戳。

## 7. 前端（frontend）

### 7.1 API 模块（frontend/src/api/triage.js，新增）
- `TRIAGE_SCOPE_OPTIONS`：三项枚举（value/label/desc）。
- `DEFAULT_TRIAGE_SCOPE = ['file_hashes','network','process_subtree']`。
- `create(hostId, scope)` / `list(hostId)`。

### 7.2 HostDetailView.vue
- 导入 `triageApi` 与常量。
- 顶部工具栏新增「发起取证」按钮（`:icon="Search"`）。
- 新增「动态取证」Tab：任务列表表格（ID/范围/状态/下发时间/完成时间/汇总），含进行中计数 tag 与「刷新」「发起取证」按钮；空态提示。
- 新增范围选择弹窗（`el-dialog`）：三项默认勾选，确认后 `submitTriage` 下发并跳到「动态取证」Tab、`ensureTriagePolling` 启动 5s 轮询刷新。
- `onMounted` 加载任务列表；`onUnmounted` 清理轮询定时器。
- 配套样式：`.triage-tip` / `.triage-opt*` 等。

## 8. 实现要点小结

- 全链路复用既有采集器与落库模型，新增面最小化。
- 鉴权严格分层：用户态管「下发/查看」，agent token 态管「轮询/回传」，并绑定 host 防越权。
- 存量保全：动态取证追加写入、标记 `source='triage'`，与快照取证双轨并存。
