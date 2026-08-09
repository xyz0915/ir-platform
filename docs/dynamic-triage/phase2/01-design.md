# 阶段二 设计文档 — 动态取证任务（方案 A 轮询通道 + 默认三项 scope）

> 隶属：应急动态取证方案（docs/应急动态取证方案.md）
> 阶段：Phase 2 / 3 · 设计环节
> 目标：建立「平台下发定向取证指令 → daemon 轮询领取 → 定向采集 → 回传落库」的事件驱动动态取证通道。
> 技术通道：**方案 A（轮询）**；默认取证范围：`file_hashes` / `network` / `process_subtree` 三项全勾。

## 1. 问题定义

阶段一已打通 daemon 实时事件 → 深度分析的链路，但「应急现场需要**针对性、当下时刻**的取证数据」这一诉求仍未满足：

- 快照采集是导入时刻的静态切片，无法反映「现在」易变的取证面（如当下网络连接、此刻进程子树、当前加载的模块哈希）。
- 不应让 daemon 把所有实时数据全量上报（阶段一方案已论证：带宽/存储/噪声均不可接受）。
- 需要一种**按需、定向、轻量**的取证机制：分析人员判断现场后，向指定主机的常驻 daemon 下发一条「取证指令」，daemon 在下次轮询时执行并回传。

## 2. 设计决策

### 2.1 技术通道：方案 A（轮询）

- daemon 维持既有心跳节奏，周期性（≤30s）向平台拉取 `pending` 取证任务；领到任务即定向采集并回传。
- 理由（见方案文档 §命令通道 A/B 对比）：轮询复用 daemon 已有长连接模型，实现简单、对 NAT/防火墙友好、天然具备失败重试语义；相较方案 B（服务端主动推送）省去反向连接与会话保持复杂度。
- 轮询间隔常量 `_DAEMON_TRIAGE_POLL_INTERVAL = 30`（秒），与主循环一并调度。

### 2.2 取证范围（scope）与默认值

- 允许取值集合：`{"file_hashes","network","process_subtree"}`。
- **默认值三项全勾**：`["file_hashes","network","process_subtree"]`（与阶段二需求一致）。
- 非法 scope 被服务端过滤；若过滤后为空则回退默认三项，保证任务永远可执行。
- 各项语义：
  - `file_hashes`：对当前运行进程加载的模块做哈希快照（取自 `collectors.files`）。
  - `network`：采集 daemon 轮询时刻的主机实时网络连接（取自 `collectors.network`）。
  - `process_subtree`：定向采集进程启动链/子树（取自 `collectors.processes`）。

### 2.3 落库策略：追加（source='triage'），不污染存量

- 取证结果写入既有 `file_hashes` / `network_connections` / `process_events` 表，**新增 `source` 列**标记 `triage`。
- 写入方式为 **INSERT（追加）**，绝不 DELETE 既有快照数据——保证「快照取证」与「动态取证」双轨并存、可溯源、互不覆盖。
- 进程事件复用 `ProcessEvent.batch_create`，并透传 `source='triage'`，使其与 daemon 实时 `process_start` 一样进入归一化/根因/进程树。

### 2.4 任务状态机与鉴权

- `triage_tasks` 表状态：`pending → running → done | failed`。
- daemon 轮询接口（`GET /pending`）领任务时原子置 `running`（取最旧 pending + 加锁式 UPDATE），避免重复执行。
- 平台下发/查询接口走**用户鉴权**（`get_current_user`）；daemon 轮询/回传接口走**专属 agent token 鉴权**（`get_current_agent`）+ host 绑定校验（`assert_host_binding`，防 token 跨主机复用）。

## 3. 数据模型

### 3.1 新增 triage_tasks 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 任务 ID |
| host_id | INTEGER | 目标主机 |
| scope | TEXT(JSON) | 取证范围数组 |
| status | TEXT | pending/running/done/failed |
| summary | TEXT(JSON,nullable) | 回传汇总（各类写入条数或错误） |
| error | TEXT(nullable) | 失败原因 |
| created_at / started_at / finished_at | TEXT | 时间戳 |

### 3.2 存量表新增 source 列
- `file_hashes.source`、`network_connections.source`、`process_events.source` 均为 TEXT，缺省 NULL 兼容旧行；非空时取值 `'triage'`（或 `'snapshot'`/`'process_events'` 等其他来源）。

## 4. 改动范围（file:line，详见 02-dev.md）

| 文件 | 改动 |
|------|------|
| `backend/app/database.py` | `triage_tasks` 表 DDL；`file_hashes`/`network_connections` 加 `source` 列；`_alter_add_column` 迁移 |
| `backend/app/models/triage_task.py` | 新增 `TriageTask` 模型（create/get_pending/list_by_host/complete） |
| `backend/app/api/triage_tasks.py` | 新增 4 个端点（下发/列表/轮询/回传） |
| `backend/app/main.py` | 注册 `triage_tasks` 路由（prefix `/api`） |
| `agent/collectors/triage.py` | 新增 `TriageCollector.collect_triage(scope)` |
| `agent/agent.py` | 主循环新增取证轮询调度（`_fetch_triage_task`/`_report_triage_result`/`_maybe_run_triage`） |
| `frontend/src/api/triage.js` | 前端取证 API + scope 枚举/默认值 |
| `frontend/src/views/HostDetailView.vue` | 「发起取证」按钮 + 「动态取证」Tab + 范围选择弹窗 |

## 5. 验收标准

- AC1：`POST /triage-tasks` 默认 scope 三项；非法 scope 被过滤/回退。
- AC2：`GET /triage-tasks/pending`（agent token）领任务并置 running；再轮询无 pending。
- AC3：`POST /triage-tasks/{id}/result` 将三类数据以 `source='triage'` 追加落库，且**不删除**既有快照行。
- AC4：无 token / 用户 JWT / host 绑定不匹配分别返回 401 / 401 / 403。
- AC5：前端可下发任务、查看任务列表与状态、自动轮询刷新进行中任务。
- AC6：存量库经迁移自动获得新列，无破坏。

## 6. 风险

- 均为局部逻辑 + 可重入 ALTER 列迁移，无不可逆 schema 变更。
- 轮询间隔 30s 满足应急「按需取证」时效预期（非毫秒级实时监控，符合方案 A 定位）。
