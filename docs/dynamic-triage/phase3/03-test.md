# 阶段三 测试文档 — 聚合稳定性（告警→聚类→events 幂等/去重）

> 隶属：应急动态取证方案 · Phase 3 / 3 · 测试环节
> 测试套件：`backend/tests/test_phase3_aggregate_stability.py`（9 用例）
> 验证目标：覆盖管道修复（process_start 真正告警）、去重/幂等（防风暴）、通用事件路径、聚类确定性。

## 1. 测试基建

- DB 隔离：module-scoped 临时 SQLite（系统 temp 目录），`init_db()` 仅建库一次；每用例前 `_clear_data()` 清空 `alerts/hosts/cases`（含 `PRAGMA foreign_keys=OFF` 安全清表）。
- 鉴权：本阶段为纯服务层测试，不挂载路由、不依赖 token。
- 评估器：`AlertEngine()` 默认 `ws_manager=alert_ws_manager`；`asyncio.create_task(broadcast)` 在同步单测下抛 RuntimeError 被捕获，仅告警日志，不影响断言。

## 2. 用例清单（T1–T9）

| 编号 | 用例 | 验证点 | 预期 |
|------|------|--------|------|
| T1 | `test_daemon_process_start_now_alerts` | 管道修复 | `process_start` 经评估产出 `EVENT-PROCESS-ROUTINE` 告警 |
| T2 | `test_benign_process_stream_aggregates` | 良性流聚合 | 20 次相同良性 → 1 条，count=20 |
| T3 | `test_suspicious_certutil_stream_aggregates_no_storm` | 高危流聚合 | 50 次 certutil 下载 → 1 条 `EVENT-CERTUTIL-DOWNLOAD`，count=50，severity=critical |
| T4 | `test_high_frequency_stream_exact_single_alert` | 超高频防风暴 | 100 次良性 → 全主机仅 1 条告警，count=100 |
| T5 | `test_distinct_suspicious_commands_separate_but_aggregated` | 不同命令独立 | certutil / powershell 各 1 条，不误合并 |
| T6 | `test_repeated_evaluate_idempotent_no_new_alert` | 幂等 | 重复评估同事件 → 不新增告警，count=2 |
| T7 | `test_generic_network_event_still_alerts` | 通用路径 | `network_connect` → `EVENT-NET-CONNECT`（行为不变） |
| T8 | `test_generic_file_delete_alerts` | 通用路径 | `file_delete` → `EVENT-FILE-DELETE` |
| T9 | `test_keyword_cluster_deterministic` | 聚类确定性 | 相同告警输入两次聚类结果相等 |

## 3. 关键断言说明

- **T2/T3/T4（核心去重）**：直接断言 `Alert.list(host_id)` 返回条数 == 1 且 `count` 等于事件次数，
  证明 5 分钟窗口内 `(host, rule)` 聚合生效，杜绝风暴。
- **T1（管道修复）**：此前 `process_start` 不匹配 `_EVENT_RULES` 导致零告警；本用例锁定修复后行为，防止回归。
- **T6（幂等）**：先评一次记录告警数，再评一次断言数量不变，验证 `create_or_aggregate` 幂等。
- **T9（聚类）**：对相同 `alerts` 列表调用 `_cluster_keyword` 两次，断言分组结构全等。

## 4. 执行命令

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/test_phase3_aggregate_stability.py -v
```

## 5. 已知告警（非阻塞）

- 单测环境出现 `RuntimeWarning: coroutine 'AlertWebSocketManager.broadcast' was never awaited`：
  因同步 pytest 无运行事件循环，`asyncio.create_task` 抛 RuntimeError 被捕获后，broadcast 协程对象未 await。
  此为测试环境假象，uvicorn 异步上下文下正常；不影响去重/断言结论。生产环境 `evaluate_events` 在
  `process_events.py` 同步端点内被调用，但 uvicorn 持有运行循环，`create_task` 生效。
