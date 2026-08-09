# 阶段一 开发文档 — 轻量打通

> 阶段：Phase 1 / 3 · 开发环节
> 对应设计：01-design.md

## 1. 代码改动清单

### 1.1 `agent/agent.py`（`_collect_incremental`，约 :239-244）

```python
# 改前
if key not in old_ids:
    item["event_type"] = name
    events.append(item)

# 改后
if key not in old_ids:
    # 保留原始 event_type（如 process_start），仅用 source 记录采集器名，
    # 避免覆盖后 process_events 表失去 process_start 类型导致归一化/根因捞不到
    item["source"] = name
    events.append(item)
```

### 1.2 `backend/app/api/analysis.py`（`analyze_host`，约 :28-39）

```python
if host.get("status") not in ("imported", "analyzed"):
    # 常驻 daemon 主机：有已注册 Agent 或实时进程事件亦允许触发分析
    from app.models.agent_model import AgentModel
    from app.models.process_event import ProcessEvent

    agent_registered = AgentModel.get_token_status(host_id).get("token_set")
    has_events = bool(ProcessEvent.list_by_host(host_id))
    if not agent_registered and not has_events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="主机尚未导入采集数据，且无在线 Agent / 实时进程事件，无法分析",
        )
```

### 1.3 `backend/app/database.py` — process_events 表加 source 列

DDL（`:465` 附近）：
```sql
collected_at    TEXT,
source          TEXT          -- 事件来源：process_events(常驻 daemon) / triage(动态取证) 等
```

init_db 迁移（`:2714` 附近）：
```python
# 进程事件来源标记（区分常驻 daemon / 动态取证 triage，支持事件流溯源）
_alter_add_column("process_events", "source", "TEXT")
```

### 1.4 `backend/app/models/process_event.py` — 模型落库 source

`create` 增加 `source: Optional[str] = None` 参数，INSERT 增加 `source` 列与值；
`batch_create` 透传 `source=ev.get("source")`。

## 2. 兼容性说明

- `source` 列缺省 NULL，存量 `process_events` 行不受影响（旧行 source 为 NULL，仍可正常查询）。
- 迁移使用既有 `_alter_add_column`（PRAGMA table_info 探测 + 幂等 ALTER），重复执行安全。
- 告警引擎、WebSocket 广播路径未改动，实时告警行为不变。

## 3. 待阶段二复用点

- `source` 列已为阶段二的 `source="triage"` 标记预留，动态取证结果可直接写入并溯源区分。
