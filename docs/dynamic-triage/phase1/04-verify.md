# 阶段一 验证文档 — 轻量打通

> 阶段：Phase 1 / 3 · 验证环节
> 输入：02-dev.md（实现）、03-test.md（测试 7 passed）

## 1. 验证方法

- 静态：逐处核对代码改动与 01-design.md 的 file:line 映射一致。
- 动态：执行 `test_phase1_event_type_source.py`，7 用例全绿。
- 兼容：确认 `source` 列迁移为幂等 ALTER，存量库无破坏。

## 2. 验收对照

| 验收项 | 状态 | 证据 |
|--------|------|------|
| AC1 保留 event_type + source 标记 | ✅ | T1/T2 通过 |
| AC2 source 落库 + list_process_starts 可用 | ✅ | T3/T4 通过 |
| AC3 daemon 主机（有事件/Agent）可分析 | ✅ | T6/T7 通过 |
| AC4 完全空主机仍拒绝 | ✅ | T5 通过 |
| AC5 存量库迁移安全 | ✅ | `_alter_add_column` 幂等；init_db 已含 |

## 3. 影响评估

- **实时告警**：未改动，`process-events` 端点行为不变，告警仍正常触发/广播。
- **分析中心**：daemon 主机的 `process_start` 事件现可被归一化/根因/进程树消费，深度分析可用。
- **数据溯源**：`source` 列区分 `process_events`（常驻）与其他来源，为阶段二 `triage` 标记预留。

## 4. 结论

阶段一目标达成：**daemon 进程事件进入深度分析链路，且 daemon 主机可触发「分析」**。
无回归、无不可逆 schema 变更。可推进阶段二（动态取证任务）。
