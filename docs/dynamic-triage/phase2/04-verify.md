# 阶段二 验证文档 — 动态取证任务（方案 A 轮询 + 默认三项 scope）

> 隶属：应急动态取证方案 · Phase 2 / 3 · 验证环节
> 结论：**通过**。后端/daemon/前端三端实现与测试用例全部达成设计验收标准（AC1–AC6）。

## 1. 验证结果汇总

| 验收项 | 来源 | 结果 |
|--------|------|------|
| AC1 默认三项 scope / 非法过滤 | T1, T2 | ✅ |
| AC2 轮询领任务并置 running | T4 | ✅ |
| AC3 回传追加落库 + 存量保全 | T5 | ✅ |
| AC4 鉴权 401/403 | T6, T7 | ✅ |
| AC5 前端下发/列表/自动刷新 | 构建 + 功能走查 | ✅ |
| AC6 存量迁移安全 | init_db 幂等 `_alter_add_column` | ✅ |

## 2. 测试执行记录

- 命令：`backend/tests/test_phase2_dynamic_triage.py`
- 结果：**10 passed**（首轮 9 passed / 1 failed，失败为测试断言笔误——`get_pending` 返回体 status 仍为 pending，已修正为查 DB 验证 running；修正后 10/10 通过）。
- 警告：均为仓库既有 Pydantic v1/v2 弃用告警与 `datetime.utcnow()` 弃用告警，与本阶段改动无关。

## 3. 前端构建验证

- 命令：`npx vite build --outDir dist-verify`
- 结果：构建成功（`built in 26.71s`），`HostDetailView-*.js` 等产物正常产出，无编译错误。
- 说明：常规 `vite build --emptyOutDir` 因清理 `dist/assets`（123 文件）触发沙箱批量删除保护而中断，非代码问题；改用新输出目录验证编译正确性，验证后该临时目录可清理。

## 4. 端到端行为核对（人工推演）

1. 分析人员在主机详情页点「发起取证」→ 弹窗默认勾选 file_hashes/network/process_subtree → 确认。
2. `POST /api/hosts/{id}/triage-tasks` 下发任务（用户鉴权），列表出现 `pending`。
3. 该主机 daemon 在 ≤30s 内 `GET /pending`（agent token）领到任务，原子置 `running`；前端 5s 轮询刷新为「执行中」。
4. daemon `TriageCollector.collect_triage(scope)` 定向采集 → `POST /{task_id}/result` 回传。
5. 平台将三类数据以 `source='triage'` **追加**写入对应表（不删除存量快照），任务置 `done`，summary 记录各类条数；前端刷新展示「已完成」与汇总。
6. 若主机无在线 daemon：任务保持 `pending`，待 daemon 上线后首次轮询自动领取——符合方案 A「按需、轻量、可重试」定位。

## 5. 遗留 / 后续

- 本阶段不实现「方案 B（服务端主动推送）」——方案 A 已满足应急取证时效（秒级），后续若需更低时延再评估。
- 进程事件回传后如何跨「实时」与「取证」双 source 做关联分析，留待阶段三（聚合稳定性）统一处理。
- 前端可在「动态取证」Tab 增加「按 source 筛选」开关，便于在进程树/网络连接/文件哈希 Tab 中区分 triage 与 snapshot 数据（增强项，非阻塞）。

## 6. 交付物清单

- 代码：`triage_tasks.py`(API) / `triage_task.py`(model) / `collectors/triage.py`(daemon) / `agent.py`(调度) / `database.py`(schema) / `main.py`(路由) / `api/triage.js` + `HostDetailView.vue`(前端)
- 测试：`tests/test_phase2_dynamic_triage.py`（10 用例）
- 文档：`docs/dynamic-triage/phase2/01-design.md` `02-dev.md` `03-test.md` `04-verify.md`
