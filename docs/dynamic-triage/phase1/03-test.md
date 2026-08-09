# 阶段一 测试文档 — 轻量打通

> 阶段：Phase 1 / 3 · 测试环节
> 测试文件：`backend/tests/test_phase1_event_type_source.py`
> 运行：`backend/venv/Scripts/python.exe -m pytest tests/test_phase1_event_type_source.py -q`

## 1. 测试策略

- **隔离**：module-scoped 临时 SQLite（系统 temp 目录，不落 `backend/data`），`init_db()` 仅建库一次；
  每用例前清空 `process_events/agents/hosts/cases/audit_logs`，保证隔离且不污染真实库。
- **覆盖**：agent 侧 `_collect_incremental` 行为 + 后端模型落库 + 分析门禁三处。

## 2. 测试用例

| # | 用例 | 类型 | 验证点 |
|---|------|------|--------|
| T1 | `test_collect_incremental_preserves_event_type_and_sets_source` | 单元（agent） | 增量采集保留原始 event_type，新增 `source=="process_events"` |
| T2 | `test_collect_incremental_overwrite_regression` | 回归 | event_type 不再被改写为采集器名（≠ "process_events"） |
| T3 | `test_process_event_source_persisted` | 单元（model） | `ProcessEvent.create` 写入 `source`，`list_by_host_and_type` 可查 |
| T4 | `test_list_process_starts_picks_daemon_events` | 单元（model） | daemon 的 `process_start` 进入 `list_process_starts`（根因数据源） |
| T5 | `test_analyze_rejects_empty_pending_host` | 接口 | 完全空 pending 主机 → 400「无法分析」 |
| T6 | `test_analyze_allows_pending_host_with_events` | 接口 | 有实时进程事件的 pending 主机通过门禁 |
| T7 | `test_analyze_allows_pending_host_with_registered_agent` | 接口 | 有已注册 Agent 的 pending 主机通过门禁 |

## 3. 执行结果

```
7 passed, 164 warnings in 30.82s
```

（warnings 均为 Pydantic v2 弃用提示与 jose utcnow 弃用提示，与本次改动无关，不影响结论。）

## 4. 结论

全部 7 个用例通过，AC1–AC4 均满足（AC5 由 `_alter_add_column` 幂等迁移保证，已在 init_db 中验证可重复执行）。
阶段一功能验证通过，可进入验证环节。
