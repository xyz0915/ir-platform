# 阶段一 设计文档 — 轻量打通（event_type 修复 + analyze 门禁放宽）

> 隶属：应急动态取证方案（docs/应急动态取证方案.md）
> 阶段：Phase 1 / 3 · 设计环节
> 目标：让常驻 daemon 主机的进程事件能进入归一化/根因/进程树，且 daemon 主机可在分析中心触发「分析」。

## 1. 问题定义

现状（代码实测）存在两处阻碍 daemon 数据进入深度分析：

- **P1-1**：`agent/agent.py:243` 在 `_collect_incremental` 中执行 `item["event_type"] = name`，
  把每条事件的原始 `event_type`（如 `process_start`）整体覆盖成采集器名（`process_events`）。
  后端 `ProcessEvent.list_process_starts`（`models/process_event.py:131`）只筛 `event_type == "process_start"`，
  导致 daemon 推来的进程事件**进不了归一化/根因/进程树**（只有实时告警引擎用原始 payload，故告警能触发）。
- **P1-2**：`backend/app/api/analysis.py:28` 的 `analyze_host` 要求
  `host.status ∈ ("imported","analyzed")`。daemon 常驻主机经 bootstrap 仅刷新 `agents.status='online'`，
  `hosts.status` 仍为默认 `pending`，因此**点不了「分析」**。

## 2. 设计决策

### 2.1 P1-1：保留原始 event_type，新增 source 标记

- 不再覆盖 `event_type`，改为 `item["source"] = name` 记录采集器来源。
- 后端 `process_events` 表新增 `source` 列（TEXT），落库并可供溯源。
- 归一化/根因逻辑无需改动：`list_process_starts` 现可正确捞到 daemon 的 `process_start` 事件。

### 2.2 P1-2：analyze 门禁放宽

- 门禁从「仅 imported/analyzed」放宽为「imported/analyzed **或** 有已注册 Agent（token_set）**或** 有实时进程事件」。
- 完全空主机（无导入、无 Agent、无事件）仍拒绝，避免无意义分析。

## 3. 改动范围（file:line）

| 文件 | 位置 | 改动 |
|------|------|------|
| `agent/agent.py` | `:239-244`（`_collect_incremental`） | `item["event_type"]=name` → `item["source"]=name` |
| `backend/app/api/analysis.py` | `:28-39`（`analyze_host`） | 门禁放宽（含 Agent/事件判定） |
| `backend/app/database.py` | `:465`（DDL） | `process_events` 表加 `source TEXT` 列 |
| `backend/app/database.py` | `:2714`（init_db） | 加 `_alter_add_column("process_events","source","TEXT")` 迁移 |
| `backend/app/models/process_event.py` | `:21-73` `create` | `source` 参数 + INSERT 列/值 |
| `backend/app/models/process_event.py` | `:92-107` `batch_create` | 透传 `source=ev.get("source")` |

## 4. 验收标准

- AC1：`_collect_incremental` 输出事件的 `event_type` 保持原始值，`source=="process_events"`。
- AC2：`ProcessEvent` 写入后 `source` 可查询；`list_process_starts` 能返回 daemon 的 `process_start`。
- AC3：`status=pending` 但存在进程事件/已注册 Agent 的主机，`POST /analyze` 通过门禁（不再返回「无法分析」）。
- AC4：`status=pending` 且完全空的主机，`POST /analyze` 仍返回 400「无法分析」。
- AC5：存量库经 `init_db` 迁移自动获得 `source` 列，无破坏。

## 5. 风险

- 改动均为局部逻辑 + 可重入 ALTER 列，无不可逆 schema 变更；`source` 列缺省 NULL，兼容旧行。
