# 动态取证（Triage）功能代码审计报告

| 字段 | 内容 |
| --- | --- |
| **审计对象** | 动态取证功能（方案 A 轮询通道 / Phase 2） |
| **审计人** | 应急研判组（WorkBuddy 代理执行） |
| **日期** | 2026-08-12 |
| **版本号** | v1.0.0 |
| **审计方式** | 静态代码审查 + 真实库接口实测（端到端场景矩阵） |

---

## 1. 审计范围与方法

### 1.1 范围
| 层 | 关键文件 |
| --- | --- |
| 后端 API | `backend/app/api/triage_tasks.py`（4 个端点） |
| 后端模型 | `backend/app/models/triage_task.py`（状态机） |
| 后端落库 | `backend/app/models/process_event.py:batch_create`、`app/database.py` 表结构 |
| 后端鉴权 | `backend/app/services/agent_auth.py`（get_current_agent / assert_host_binding） |
| agent 端 | `agent/agent.py`（轮询/回传）、`agent/collectors/triage.py`（定向采集） |
| 前端 | `frontend/src/api/triage.js`、`frontend/src/views/HostDetailView.vue`（动态取证 Tab） |

### 1.2 方法
- **静态审查**：4 个后端端点 + 模型状态机 + agent 主循环 + 前端交互的代码走查；
- **动态实测**：在真实库（uvicorn :8000）上创建隔离 QA 案件/主机，模拟 平台下发 → daemon 轮询 → 回传 全链路，并验证 6 组场景（S1~S6）；测试数据已通过 purge 清理（188 行）。

---

## 2. 功能链路与架构

```
平台（FastAPI, :8000）                    daemon（agent.py --daemon）
┌────────────────────────────────┐       ┌──────────────────────────────┐
│ POST /hosts/{id}/triage-tasks  │ 下发  │ 每 ~30s 轮询                │
│   → triage_tasks(pending)      │ ────▶ │ GET .../triage-tasks/pending │
│                                │       │   → 取最旧 pending 置 running│
│ GET  .../triage-tasks          │ ◀──── │ POST .../{task_id}/result    │
│   → 任务列表/进度               │ 回传  │   → file_hashes/network/     │
│                                │       │     process_events + summary │
│ GET  /agents/{id}/token (用户) │ 部署  │ 启动：python agent.py        │
└────────────────────────────────┘       │   --daemon --server ...      │
                                         │   --token <agent_token>      │
```

- 命令通道：**方案 A（轮询）**，daemon 每 30s 拉取 1 条 pending 任务（`agent.py:422`）；
- 结果落库：`source='triage'` **追加写入**，不覆盖快照存量（`triage_tasks.py:94-148`）；
- 鉴权：平台侧端点用用户 JWT；daemon 侧端点用 **agent 专属 token** + host_id 绑定（`agent_auth.py`）。

---

## 3. 可用性分析

### 3.1 功能可用性总体评价：✅ 核心链路可用

| 能力 | 结论 | 证据 |
| --- | --- | --- |
| 任务下发（用户） | ✅ 正常 | S1a：`{"code":0,"data":{"task_id":4,"scope":[...]}}` |
| daemon 轮询取任务 | ✅ 正常 | S1b：成功返回任务（含 scope 反序列化） |
| 采集执行（agent 端） | ✅ 正常 | `collectors/triage.py` 按 scope 定向采集，异常降级空列表不拖垮 daemon |
| 结果回传 + 落库 | ✅ 正常 | S1c：written {1,1,1}；三类数据 `source='triage'` 落库验证通过 |
| 任务状态流转 | ✅ 正常 | pending → running → done（S1d）；失败回传 → failed（代码路径） |
| 进度展示（前端） | ✅ 正常 | `HostDetailView.vue` 任务列表 + 5s 轮询 + 进行中徽标 |
| 鉴权与主机绑定 | ✅ 正确 | S2 矩阵：无/无效 token→401，跨 host→403，用户 token 调 agent 端点→401 |
| scope 白名单过滤 | ✅ 正确 | S4：非法 scope 全部被过滤并回退默认三项 |
| 事务原子性 | ✅ 正确 | `get_connection` 单连接 commit/rollback，create/get_pending/complete 原子 |
| 数据完整性 | ✅ 正确 | `PRAGMA foreign_keys=ON`，host 外键级联删除生效 |

### 3.2 健壮性短板：⚠️ 非法输入与异常恢复存在缺口

| 短板 | 影响 | 缺陷编号 |
| --- | --- | --- |
| 不存在 host 下发 → 500 | 接口语义错误（应 404） | D-1 |
| 结果回传无幂等 | 重复回传重复写库 | D-2 |
| process_events 非 dict → 500 且任务卡死 | 非法输入击穿 + 状态卡死 | D-3 |
| running 任务无超时回收 | 失联 daemon 的任务永久卡死 | D-4 |
| pending 接口返回旧状态值 | 返回 status 与实际落库不一致 | D-0 |

---

## 4. 使用方法（实测可用）

### 4.1 平台侧（Web 前端）
1. 进入 **案件管理 → 案件详情 → 主机列表 → 主机详情**；
2. 打开 **「动态取证」Tab**；
3. 点 **「发起取证」**，勾选取证范围（默认三项全勾：文件哈希 / 实时网络连接 / 进程子树），**确认下发**；
4. 前端 5s 自动轮询刷新进度；daemon 下次轮询（≤30s）执行并回传后，任务状态变为 **完成/失败**。

### 4.2 主机 daemon（agent 端）
```bash
# 1. 前端「主机 Agent 页」为该主机生成专属 token（POST /api/agents/{host_id}/token）
# 2. 部署 daemon（带 token 自举认领 host_id）
python agent.py --daemon --server http://<平台IP>:8000 --token atk_xxx
```
- daemon 每 30s 心跳 + 每 30s 轮询动态取证任务（`_DAEMON_TRIAGE_POLL_INTERVAL=30`）；
- 无 token/daemon-id 时进入 snapshot-only 模式，**动态取证不可用**（不会拉取任务）。

### 4.3 后端接口（REST）
| 端点 | 鉴权 | 说明 |
| --- | --- | --- |
| `POST /api/hosts/{host_id}/triage-tasks` | 用户 JWT | body `{"scope":["file_hashes","network","process_subtree"]}`（可选，默认三项） |
| `GET /api/hosts/{host_id}/triage-tasks` | 用户 JWT | 任务列表（含 summary/error） |
| `GET /api/hosts/{host_id}/triage-tasks/pending` | agent token | daemon 轮询：取最旧 pending 并置 running |
| `POST /api/hosts/{host_id}/triage-tasks/{task_id}/result` | agent token | 回传 `{file_hashes, network_connections, process_events, summary, error}` |

---

## 5. 实测结果（场景矩阵）

| 场景 | 操作 | 预期 | 实测 | 结论 |
| --- | --- | --- | --- | --- |
| S1 正常链路 | 下发→轮询→回传→列表 | 全链路 done | 任务 done，summary `{1,1,1}`，三类数据 `source='triage'` 落库 | ✅ 通过 |
| S2a 无效 token | pending + 错误 token | 401 | 401 `Invalid agent token` | ✅ 通过 |
| S2b 无 token | pending 无头 | 401 | 401 | ✅ 通过 |
| S2c 跨主机 token | token 查 host 45 | 403 | 403 `host 绑定不匹配` | ✅ 通过 |
| S2d 用户 token | 用户 JWT 调 pending | 401 | 401（agent 端点专属） | ✅ 通过 |
| S3 不存在 host | 对 host 999999 下发 | 404 | **500 Internal Server Error** | ❌ 缺陷 D-1 |
| S4 非法 scope | `["bogus_scope"]` | 回退默认 | 200，回退 `["file_hashes","network","process_subtree"]` | ✅ 通过（语义见 §6.2） |
| S5 重复回传 | 同一 task 回传 2 次 | 幂等 | **network 表记录 1→3，重复写入** | ❌ 缺陷 D-2 |
| S6 非法元素 | process_events 含 `["oops"]` | 拒绝/降级 | **500；任务永久卡 running** | ❌ 缺陷 D-3 |
| D-4 失联模拟 | 拉取任务后不回传 | 超时回收 | **任务永久 running，无回收** | ❌ 缺陷 D-4（代码审查确认） |

---

## 6. 缺陷清单

| 编号 | 严重度 | 位置 | 问题 | 实测证据 | 修复建议 |
| --- | --- | --- | --- | --- | --- |
| **D-1** | 中 | `api/triage_tasks.py:44-53` | `create_triage_task` 不校验 host 存在性，外键约束异常未被捕获 → 500 | host 999999 → 500 | 先 `CaseService/HostService` 判空返回 404；或捕获 `sqlite3.IntegrityError` 转 404 |
| **D-2** | 中 | `api/triage_tasks.py:72-91` | 结果回传无幂等：不校验任务状态，重复回传重复 INSERT | task 6 回传 2 次 → network 记录 1→3 | 回传前查任务状态，仅允许 `running` 回传；`done/failed` 直接拒绝或幂等去重 |
| **D-3** | 高 | `api/triage_tasks.py:85` | `{**e, "source":"triage"}` 遇非 dict 元素抛 TypeError → 500，且 `complete()` 未执行 → 任务卡 running | task 7 回传 `["oops"]` → 500，状态永久 running | 逐元素 `isinstance(e, dict)` 过滤；`try/except` 包裹写库并确保异常路径也调用 `complete(error=...)` |
| **D-4** | 中 | `models/triage_task.py:37-60` + `agent/agent.py:285-289` | `get_pending` 置 running 后无超时回收；agent 回传失败（网络/HTTP 错误）仅 warning 不重试不置 failed | 拉取后不回传 → 永久 running；前端"进行中"徽标永不消失 | 增加超时回收（如 running 超 N 分钟重置 pending/failed）；agent 端回传失败重试或主动报 failed |
| **D-0** | 低 | `models/triage_task.py:43-60` | `get_pending` 返回的任务 `status` 为旧值（`dict(row)` 构造于 UPDATE 前） | S1b 返回 `status:"pending"`，落库实际 running | 返回前 `task["status"]="running"` 或改查 `RETURNING` |

### 6.1 关联风险提示
- **D-3+D-4 叠加**：非法输入使任务卡 running 后，虽然 `get_pending` 只取 pending（不挡队列），但「进行中」计数虚增、任务历史不闭合，且无法自动恢复；
- **D-2 数据一致性**：重复回传会污染 `file_hashes/network_connections/process_events` 的取证数据（同一条记录多份），影响后续关联分析与审计溯源。

### 6.2 设计语义说明（非缺陷，记录备案）
- **非法 scope 静默回退默认三项**：用户传全非法 scope 时返回 200 并全量取证（S4）。语义安全（不会越权采集白名单外数据），但可能出乎用户预期，建议响应中附带 `filtered` 提示。

---

## 7. 设计合理项（正向确认）

- **单连接事务**：`get_connection()` yield 后 commit、异常 rollback，任务状态流转原子；
- **鉴权分层**：用户 JWT（管理侧）与 agent token（daemon 侧）隔离；token 哈希存储（`sha256(token:SECRET)`），明文仅生成时返回一次；
- **主机绑定**：`assert_host_binding` 防 token 跨主机复用（实测 403）；
- **追加写不覆盖**：`source='triage'` 与快照数据（`source='snapshot'`）并存，保留取证现场；
- **agent 采集容错**：`TriageCollector` 每 scope 独立 try/except，单类采集失败不影响其余；
- **前端轮询节流**：仅在有进行中任务时启动 5s 轮询，无任务自动停止。

---

## 8. 总体结论与建议

### 8.1 结论
动态取证功能**核心链路完整可用**：下发 → 轮询 → 采集 → 回传 → 落库 → 前端进度闭环已实测通过，鉴权/绑定/scope 白名单/事务/追加写设计良好。主要风险集中在**健壮性与状态恢复**：非法输入可击穿接口（D-3）并造成任务卡死（D-4），重复回传污染取证数据（D-2），接口语义错误（D-1）与状态返回不一致（D-0）。

### 8.2 建议优先级
| 优先级 | 缺陷 | 原因 |
| --- | --- | --- |
| **P0** | D-3 | 非法输入可致 500 + 任务永久卡死，属可用性击穿 |
| **P1** | D-2、D-4 | 数据重复污染 + 状态不闭合，影响取证可信度与可观测性 |
| **P2** | D-1、D-0 | 接口语义与返回值准确性 |

### 8.3 后续动作
1. 按 P0→P2 修复缺陷（D-3 优先），修复后补充 `test_triage_tasks.py` 隔离测试（沿用 `--noconftest` + 临时库模式）；
2. 将动态取证测试纳入 CI（`.github/workflows/backend-ci.yml` test 步骤）；
3. daemon 端回传失败增加重试与主动 failed 上报，形成状态闭环。
