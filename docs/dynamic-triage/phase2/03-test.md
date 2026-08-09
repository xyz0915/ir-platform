# 阶段二 测试文档 — 动态取证任务（方案 A 轮询 + 默认三项 scope）

> 隶属：应急动态取证方案 · Phase 2 / 3 · 测试环节
> 测试套件：`backend/tests/test_phase2_dynamic_triage.py`（10 用例）
> 验证目标：覆盖下发/列表/轮询/回传/鉴权/采集器六类行为，重点验证「追加落库、存量保全、scope 默认值、agent 鉴权绑定」。

## 1. 测试基建

- DB 隔离：module-scoped 临时 SQLite（系统 temp 目录，不落 `backend/data`），`init_db()` 仅建库一次；每用例前 `_clear_data()` 清空被测表（含 `PRAGMA foreign_keys=OFF` 安全清表）。
- 鉴权：`User.get_by_username("admin")` + `create_token` 生成用户 JWT；`AgentModel.register` + `AgentModel.generate_token` 复刻真实 daemon 注册并获取明文 agent token。
- 应用：仅挂载 `triage_tasks` 路由（prefix `/api`），聚焦本阶段接口。
- agent 包路径加入 `sys.path`，使 `collectors.*` 与 `collectors.triage` 可被导入（供采集器用例 monkeypatch）。

## 2. 用例清单（T1–T10）

| 编号 | 用例 | 验证点 | 预期 |
|------|------|--------|------|
| T1 | `test_create_triage_default_scope` | 默认下发 | `scope == [file_hashes, network, process_subtree]`，返回 int task_id |
| T2 | `test_create_triage_invalid_scope_falls_back_to_default` | scope 校验 | 非法项被剔除；仅非法项时回退默认三项 |
| T3 | `test_list_triage_tasks` | 列表查询 | 返回 1 条，status=pending，scope=三项 |
| T4 | `test_agent_poll_pending_marks_running` | 轮询领任务 | 首次返回任务；DB status=running；二次轮询返回 None |
| T5 | `test_agent_report_result_appends_triage_source` | 回传落库+存量保全 | written={3类各1}；file_hashes/network 各 2 行（存量1+triage1）；process_events 1 行 source=triage；任务终态 done 且 summary 正确 |
| T6 | `test_agent_endpoints_require_token` | 鉴权-401 | 无 token 401；用户 JWT 当 agent token 亦 401 |
| T7 | `test_agent_host_binding_mismatch` | 鉴权-403 | token 绑定 hostA 访问 hostB → 403 |
| T8 | `test_triage_collector_scope_shapes` | 采集器映射 | 三类各 1 条；process 映射 event_type=process_start；network 映射 local/remote 字段 |
| T9 | `test_triage_collector_partial_scope` | 采集器局部 scope | 仅 file_hashes 时，其余两类为空 |
| T10 | `test_triage_collector_degrades_on_error` | 采集器降级 | 采集器抛异常 → 该 scope 返回 `[]`，不抛异常 |

## 3. 关键断言说明

- **T5（核心）**：先 INSERT 一条 `source='snapshot'` 的 file_hashes / network_connections 存量行；回传 triage 结果后断言总行数 = 存量 + 1，且两类 source 共存 → 证明「追加而非覆盖」。
- **T4**：`get_pending` 返回体 status 仍为 `pending`（取任务瞬间快照），但 DB 实际已置 `running`；以直接查 DB 验证状态机正确性。
- **T8**：`_map_processes` 将 `name→process_name`、`create_time→start_time`、`event_time=now`；`_map_network` 保留 `local_address/remote_address` 供后端 `_insert_network` 兼容别名。

## 4. 执行命令

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/test_phase2_dynamic_triage.py -v
```

## 5. 前端验证

- `vite build --outDir dist-verify` 构建通过（2816 模块转换成功，HostDetailView 编译无错）。
- 功能点（人工/集成可验证）：「发起取证」弹窗默认三项勾选；任务下发后列表出现 pending→running→done；进行中任务 5s 自动刷新；host 无 agent 时任务将长期 pending（符合方案 A 轮询语义，待 daemon 上线领取）。
