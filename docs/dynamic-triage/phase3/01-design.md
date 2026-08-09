# 阶段三 设计文档 — 聚合稳定性（告警→聚类→events 幂等/去重）

> 隶属：应急动态取证方案（docs/应急动态取证方案.md）
> 阶段：Phase 3 / 3 · 设计环节
> 目标：核对并加固 `AlertEngine.evaluate_events → 聚类 → events 写入` 的去重/幂等，
> 确保 daemon 高频进程流**稳定、不重复**地进入分析中心事件维度，杜绝告警风暴。

## 1. 问题定义

阶段一/二打通 daemon 实时流与动态取证后，重新审视「实时段」聚合链路，发现一处**关键断点**：

- **P3-1（管道断点）**：daemon 推送的进程事件 `event_type='process_start'`（阶段一已保留原始 event_type）。
  但 `AlertEngine.evaluate_events`（`services/alert_engine.py:96`）仅按 `_EVENT_RULES`
  （`process_create/term/network_connect/...`）匹配，**不含 `process_start`** → daemon 进程流**零告警**，
  根本到不了统一告警中心 / 聚类 / events 维度。
- **P3-2（死代码）**：真正做命令级检测的 `evaluate_process_event` / `evaluate_batch_process_events`
  从未被任何调用方引用（全局 grep 仅自引用），daemon 进程流无法享受其 certutil/powershell/recon/凭据窃取判定。
- **P3-3（去重验证）**：告警层去重依赖 `Alert.create_or_aggregate`（5 分钟窗口，按 `host+rule` 聚合）。
  需验证 daemon 高频流下该机制确实生效，不产生风暴。

## 2. 设计决策

### 2.1 统一评估入口（修复 P3-1 / P3-2）

- `evaluate_events` 对进程类事件（`process_start` / `process_create` / `process_term`）**统一委托**
  `evaluate_process_event`（命令级检测 + `create_or_aggregate` 去重）；其余事件仍走通用 `process_event`。
- 收益：
  - daemon `process_start` 首次真正进入告警评估；
  - 复用既有命令级高危判定（certutil 下载→critical、powershell -enc→critical、whoami/net user→recon、mimikatz/procdump→凭据窃取）；
  - 良性进程聚合为单条"进程运行"告警（count 累加），不淹没视图。

### 2.2 去重/幂等机制（核心防御，修复 P3-3）

- `Alert.create_or_aggregate`（`models/alert.py:42`）：同 `(host_id, rule_name, status='open')`
  且 `last_seen_at > now-5min` → `UPDATE count=count+1`；否则新建。
- 推论（已测试证明）：
  - 同一良性进程流 100 次 → **1 条**告警，count=100（无风暴）；
  - 同一 certutil 下载 50 次 → **1 条** EVENT-CERTUTIL-DOWNLOAD，count=50；
  - 不同可疑命令 → 各自独立告警，但各自聚合。

### 2.3 聚类稳定性

- keyword 模式（`IncidentCorrelator._cluster_keyword`）：纯函数式，按 `rule_name` 分组，
  相同告警输入产出**确定性**分组（已测试）。
- semantic 模式：按需触发（分析/聚类动作），非 daemon 流持续触发；产出 `incident_clusters`。
  因属用户触发的按需归并，非"风暴"来源，本阶段不强制幂等去重（重复手动聚类会产生新簇，属可接受行为）。

## 3. 改动范围（file:line）

| 文件 | 位置 | 改动 |
|------|------|------|
| `backend/app/services/alert_engine.py` | `:96-120`（`evaluate_events`） | 进程类事件路由至 `evaluate_process_event`，统一评估入口 |
| （既有）`backend/app/models/alert.py` | `:42-67`（`create_or_aggregate`） | 去重机制（本阶段仅验证，未改动） |
| （既有）`backend/app/services/incident_correlator.py` | `_cluster_keyword` | 聚类确定性（本阶段仅验证，未改动） |

> 说明：`evaluate_events` 现为进程事件告警的**唯一入口**；原 `evaluate_batch_process_events`
> 与本逻辑重叠，标记为冗余（无外部调用方，保留不删以避免误伤）。

## 4. 验收标准

- AC1：daemon `process_start` 事件经 `evaluate_events` 产生告警（修复零告警断点）。
- AC2：同一规则 5 分钟内重复事件 → 聚合为单条（count 累加），不新增告警。
- AC3：高频流（100 次良性 / 50 次 certutil）→ 各 1 条告警，无风暴。
- AC4：不同可疑命令 → 各自独立告警，且各自聚合。
- AC5：通用 network/file 事件仍走通用评估路径，行为不变。
- AC6：keyword 聚类对相同输入确定性一致。

## 5. 风险

- 良性进程现会产生"进程运行"聚合告警（低频，count 累加）；若认为噪声，可在产品层对 `EVENT-PROCESS-ROUTINE` 做降噪/折叠，非本阶段阻塞项。
- `evaluate_events` 内 `asyncio.create_task(ws.broadcast)` 依赖运行事件循环（uvicorn 异步上下文满足）；同步单测环境会抛 RuntimeError 被捕获，仅告警日志，不影响去重结论。
