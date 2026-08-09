# 阶段三 验证文档 — 聚合稳定性（告警→聚类→events 幂等/去重）

> 隶属：应急动态取证方案 · Phase 3 / 3 · 验证环节
> 结论：**通过**。管道断点已修复（daemon process_start 现真正告警），去重/幂等机制经验证可防告警风暴；
> 通用事件路径与聚类确定性均符合预期。

## 1. 验证结果汇总

| 验收项 | 来源 | 结果 |
|--------|------|------|
| AC1 daemon process_start 现告警 | T1 | ✅ |
| AC2 同规则 5 分钟内聚合、不新增 | T2, T6 | ✅ |
| AC3 高频流（100/50 次）单条无风暴 | T3, T4 | ✅ |
| AC4 不同可疑命令各自独立+聚合 | T5 | ✅ |
| AC5 通用 network/file 事件路径不变 | T7, T8 | ✅ |
| AC6 keyword 聚类确定性 | T9 | ✅ |

## 2. 测试执行记录

- 命令：`backend/tests/test_phase3_aggregate_stability.py`
- 结果：**9 passed**（164 warnings，均为仓库既有 Pydantic 弃用告警 + 单测环境 broadcast 协程未 await 告警，与本阶段改动无关）。
- 首轮即全绿，无需修正（相较阶段二，本阶段测试断言与实现一致）。

## 3. 端到端行为核对（人工推演）

1. daemon 每 5s 推送进程事件（`event_type=process_start`）→ `POST /process-events`（agent token）。
2. 端点内 `engine.evaluate_events(host_id, payload)` → 进程类事件委托 `evaluate_process_event`：
   - 良性进程（如 `svchost.exe`）→ 聚合为单条 `EVENT-PROCESS-ROUTINE`（count 累加）。
   - 命令含 certutil/powershell/whoami/mimikatz → 各自独立高危告警（各自聚合）。
3. 任一告警经 `Alert.create_or_aggregate`：5 分钟内同 `(host, rule)` → `count+1`，绝不新增行。
   → **daemon 持续高频进程流 → 分析中心告警维度稳定、不重复、无风暴**。
4. 用户触发聚类（keyword / semantic）→ 由 `alerts` 生成 `incident_clusters` 进入事件维度；
   keyword 模式对相同告警输入产出确定性分组。

## 4. 关键修复影响

- 修复前：daemon 进程流对告警中心**完全不可见**（零告警），实时段架构断链。
- 修复后：daemon 进程流正确进入告警→聚类→events，且与既有快照/取证数据在统一研判工作台汇合。
- 该修复**无需改动 `process_events.py` 端点**（仅 `evaluate_events` 内部分流），影响面最小。

## 5. 遗留 / 后续（增强项，非阻塞）

- 良性进程"进程运行"聚合告警仍会产生低频条目；如需进一步降噪，可在前端/分析层对
  `EVENT-PROCESS-ROUTINE` 做折叠或阈值抑制（如 count 低于 N 不展示）。
- semantic 聚类为按需触发，重复手动聚类会新建 `incident_clusters` 簇；若需幂等，可在聚类前
  按 (host, time_window, mode) 去重或复用既有簇，留待后续优化。
- `evaluate_batch_process_events` 与 `evaluate_events` 新逻辑重叠，建议后续统一删除以避免歧义。

## 6. 交付物清单

- 代码：`services/alert_engine.py`（`evaluate_events` 分流修复）
- 测试：`tests/test_phase3_aggregate_stability.py`（9 用例）
- 文档：`docs/dynamic-triage/phase3/01-design.md` `02-dev.md` `03-test.md` `04-verify.md`

---

## 7. 三阶段总览

| 阶段 | 主题 | 通道/默认 | 测试 | 文档 |
|------|------|-----------|------|------|
| 一 | 轻量打通（event_type 修复 + analyze 放宽） | — | 7 passed | 4 篇 |
| 二 | 动态取证任务 | 方案 A 轮询 / file_hashes+network+process_subtree | 10 passed | 4 篇 |
| 三 | 聚合稳定性（去重/幂等） | — | 9 passed | 4 篇 |

**三阶段全部完成，合计 26 测试用例通过，12 篇过程文档齐备，全过程可追溯。**
