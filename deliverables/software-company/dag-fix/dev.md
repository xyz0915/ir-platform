# DAG 流水线 HITL 全量修复 — 开发说明（dev.md）

> 开发者：寇豆码（software-engineer）
> 依据：`design.md`（739 行，架构师高见远）— 伪代码为权威规格
> 目标：修复 DAG 路径（`PipelineEngine`）HITL 审批门失效（P0×4）+ P1×4 + P2×6；
> 硬编码路径（`orchestrator.run_pipeline`）行为完全不变。
> 提交：见文末 commit hash。

---

## 1. 修改/新建文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `backend/app/services/agents/pipeline_common.py` | **新建** | 共享常量（HITL_WAIT_TIMEOUT/HITL_EXPIRE_TTL）+ 纯函数（compute_final_status/_stable_dict/_safe_sse） |
| `backend/app/services/agents/guardrail_agent.py` | **新建** | 合规门禁节点独立类（GuardrailAgent.evaluate） |
| `backend/tests/conftest.py` | **新建** | 临时 sqlite + 引擎 fixture + mock_llm（非 autouse，不影响既有测试） |
| `backend/app/services/agents/pipeline_engine.py` | **修改** | P0-1/2/3/4 + P1-1/2/3/4 + P2-1/2/3/4/5/6 全部引擎侧修复 |
| `backend/app/services/agents/orchestrator.py` | **修改** | `resume()` 按 `ctx.mode=='custom'` 分流委托 `pipeline_engine.resume`（P0-3） |
| `backend/app/api/agents.py` | **修改** | `create_agent_run` 同步 DAG 预校验 400（P1-1）；`cancel` 端点配套引擎取消（P2-6） |
| `backend/app/services/agents/agent_registry.py` | **修改** | `validate_pipeline` 追加 P2-2 引用未声明依赖告警 |
| `backend/app/services/agents/node_fixtures.py` | **修改** | 补 `guardrail` simulate fixture |
| `backend/tests/_smoke_dag_fix.py` | **新建（未提交）** | 开发期冒烟脚本（31 断言全过），供 QA 参考 |

---

## 2. 每个问题的修复位置与实现说明

### P0-1 `_run_single` 不等待 → `await Event` + 超时
- **位置**：`pipeline_engine.py::_run_single` HITL 分支（原 L324-340，现约 L355-490）
- **实现**：HITL 分支先 `HitlApproval.create` → 创建 `asyncio.Event` 存入 `_hitl_events[run_id]` →
  `await asyncio.wait_for(event.wait(), timeout=self._HITL_WAIT_TIMEOUT)`（默认 1800s，环境变量 `IR_HITL_WAIT_TIMEOUT` 覆盖）。
- **超时**：审批置 `expired`（reason=审批超时未决议）+ stage 置 failed（error=hitl_timeout）+ step failed；
  `_run_single` 返回 failed → `compute_final_status` 收敛 run 为 failed。**不无限挂起**。

### P0-2 从不写 hitl_approvals → `_create_hitl_approval`
- **位置**：`pipeline_engine.py::_create_hitl_approval`（L555 起）
- **实现**：字段语义对齐 `Orchestrator.wait_hitl`（action/target_json/auto_rollback_plan/reason/requested_by）。
  数据来源优先级：`run.ctx.responder_action` > `agent_def.config` > 兜底 `'custom'`/`{}`。
- **fail-safe**：创建失败返回 `None` → `_run_single` **不进入等待**，stage failed（error=hitl_approval_create_failed）+ run failed。
  保证审批端点 `HitlApproval.get_by_id` 永不 404。

### P0-3 `resume()` 缩进错 → 置位移出 if 块 + 孤儿续跑
- **位置**：`pipeline_engine.py::resume`（L1447 起）
- **实现**：`hitl_event.result/decided_by/set()` 移出 `if hitl_event is None:` 块（缩进修正，正常路径不再 `return False`）；
  内存无 Event 但 DB=waiting_hitl → 重建 Event 唤醒（进程重启恢复）；`_runs` 无该 run（孤儿）→
  `asyncio.create_task(self._continue_orphan_run(run_id, approved))` 尽力续跑。
- **新增 `_continue_orphan_run`**（L1502 起）：从 ctx_json 还原 `{agent_names, event_id, mode, user}`，从 `agent_run_steps`
  还原已完成节点；对 status=waiting_hitl 的节点**直接以本次决议标记完成**（不重复触发 HITL/不重复审批，设计偏差见 §3）；
  其余节点按拓扑序续跑（复用 `_run_single`）；最终收敛 completed/failed/cancelled；失败仅置 DB failed + 日志，不外抛。
- **orchestrator 分流**：`orchestrator.resume`（L471 起）读 `ctx_json.mode`，`mode=='custom'` → 函数级 import `pipeline_engine`
  并委托 `resume(run_id, approved, user)`，成功返回 `{resumed_by: pipeline_engine, status: running}`；
  失败/非 custom → 原有 `_finish_with_reporter` / `_resume_custom` 逻辑**零改动**。

### P0-4 处置动作无执行点 → `_run_single` 等待恢复后执行
- **位置**：`pipeline_engine.py::_run_single` HITL 分支（approved 分支）
- **实现**：等待恢复后 `approved = bool(getattr(hitl_event, 'result', False))`；approved →
  `ResponderAgent().execute_action(action, target=_jl(approval.target_json), event_id, operator)`（与 orchestrator L479-482 同一入口）。
  失败仅写 `hitl_decision.executed = {success: False, error}`，不阻断 DAG 续跑。
- **唯一执行点原则**：动作执行只在 `_run_single` 内发生；`resume()` 只 `set()` 唤醒，不执行动作（杜绝双执行）。

### P1-1 运行前无 DAG 校验 → 环检测
- **API 层**：`agents.py::create_agent_run` 在 `start_run` 前同步 `AgentRegistry().validate_pipeline(agent_names)`；
  对硬错误（not found / disabled / Circular）返 `HTTPException(400)`（即时反馈，不静默丢节点）。
  *偏差：仅阻断硬错误，advisory（缺依赖声明/P2-2）不 400，与 `default_pipeline_service.validate_default_pipeline` 既有模式一致。*
- **引擎层**：`pipeline_engine.py::run` 生成 graph 后 `detect_cycle`，有环 `raise ValueError("DAG 存在环: ...")`；
  `run()` 外层 `except ValueError` 捕获 → run failed + DB failed（错误信息可见）。

### P1-2 input_params 写死 `{}` → 透传
- **位置**：`pipeline_engine.py::_execute_agent` 节点分支（L1256 起）+ `_run_single` 缓存键处
- **实现**：`input_params = {**(agent_def.config or {}).get("input_params", {}), **(run.ctx.get("input_params") or {})}`
  （节点配置 > run 级 ctx），透传 `runner(ctx, input_params, "real")`；built-in（triage/responder/reporter）维持 `task={}` 不变。
- 节点分支返回新增 `structured` 透传（prompt_used/query 可观测）；`_run_llm` structured 回显 `query`。

### P1-3 收尾状态无条件 completed → compute_final_status
- **位置**：`pipeline_common.py::compute_final_status` + `pipeline_engine.py::run` 收尾（L231-235）
- **实现**：优先级 `cancelled > failed > waiting_hitl > completed`；`run()` 的 `final_status` 与 `AgentRun.update` 同用。

### P1-4 Guardrail 未接入 → `_run_guardrail` + 独立类
- **位置**：`pipeline_engine.py::_get_node_runner`（L755 起，新增 `"guardrail": self._run_guardrail`）、
  `_run_guardrail`（L1246 起）、`guardrail_agent.py`（新建）
- **实现**：委托 `GuardrailAgent().evaluate(input_params)`；语义=记录 + 默认放行，显式 `block=true` 才阻断
  （返回 `status="blocked"`）；`_execute_agent`/`_run_single` 将 `status != success` 反映为 stage failed → 下游不执行。
- `node_fixtures.py` 补 `SIMULATE_GUARDRAIL` 与 `_FIXTURE_MAP` 映射。

### P2-1 缓存键不含 input_params → 扩键
- **位置**：`pipeline_engine.py::_run_single`（缓存检查处）
- **实现**：`cache_params = {event_id, host_id, agent, input_params: _stable_dict(input_params)}`；
  `_stable_dict` 递归归一化（dict/list/tuple/set），CacheManager 内部 `json.dumps(sort_keys=True)+SHA256` 无需改动。

### P2-2 同批并发读半成品 → `_stage_output` 辅助 + validate 告警
- **位置**：`pipeline_engine.py::_stage_output`（L1350 起）；`_run_root_cause` 改用之；`agent_registry.py::validate_pipeline` 追加告警
- **实现**：`_stage_output` 仅返回 `status=="completed"` 的 stage 输出，未完成返回 `{}`（不抛 KeyError）；
  `validate_pipeline` 对 `config.input_params` 中 `{dep:<name>}` 引用但未声明 `depends_on` 的节点追加"建议声明依赖"提示。
  **不引入锁**（审计确认 asyncio 单线程下 list.append 原子，真正风险是逻辑竞态）。

### P2-3 waiting_hitl 永不清理 → 清理分支 + 孤儿过期
- **位置**：`pipeline_engine.py::_cleanup_expired_runs`（L1725 起）、`_expire_orphan_waiting_hitl`（L1662 起）
- **实现**：内存路径——waiting_hitl 超 `HITL_EXPIRE_TTL`（默认 86400s，`IR_HITL_EXPIRE_TTL` 覆盖）→ pending 审批置 expired
  + DB failed + 内存清理；孤儿路径——`_ensure_restored` 时扫描 DB 中超龄 waiting_hitl 做同等过期。

### P2-4 模块导入期访问 DB → 懒初始化
- **位置**：`pipeline_engine.py::__init__`（移除 `_restore_hitl_events()` 调用）、`_ensure_restored`（L1644 起）
- **实现**：`__init__` 仅置 `_restored=False`；`run()`/`resume()` 首次调用 `_ensure_restored()` 时才 `_restore_hitl_events()`
  + `_expire_orphan_waiting_hitl()`。模块级 `pipeline_engine = PipelineEngine()` 保留但构造不触 DB（导入自测通过）。

### P2-5 SSE 回调异常被吞 → `_safe_sse`
- **位置**：`pipeline_common.py::_safe_sse` + `pipeline_engine.py::_push_sse`（L1398 起）
- **实现**：`asyncio.ensure_future(_safe_sse(on_sse, event_type, data))`；协程内 `try/except + logger.exception`，
  异常可观测且不破坏主流程。

### P2-6 取消不唤醒/不中断 → `run.tasks` + cancel 配套
- **位置**：`PipelineRun.tasks`（L71）、`run()` 批量登记（L210-228）、`cancel()`（L1416 起）、`_run_single` CancelledError 分支
- **实现**：每批 `asyncio.create_task(_run_single(...))` 登记 `run.tasks`，gather 后 discard；
  `cancel()` 置 cancelled + 唤醒 waiting_hitl（`ev.result=False; ev.set()`）+ `task.cancel()` 中断 in-flight；
  `_run_single` 捕获 `CancelledError` 标记 stage cancelled + step cancelled 后 re-raise；
  `run()` 批量用 `gather(return_exceptions=True)` 吸收子任务取消，使 run 收尾到 cancelled 并持久化 DB
  （*实现选择：比设计伪代码更稳健，run 任务本身正常返回而非被取消，DB 状态一致*）。
- **API 配套**：`agents.py::cancel_agent_run` 在置 DB cancelled 后调用 `pipeline_engine.cancel(run_id)`（函数级 import 单例）。

---

## 3. 与设计文档的偏差（均已论证）

| # | 设计原文 | 实现偏差 | 理由 |
|---|---------|---------|------|
| 1 | `create_agent_run` 对 `validate_pipeline` 全部错误返 400 | 仅阻断硬错误（not found/disabled/Circular） | 缺依赖声明、P2-2 引用告警为 advisory；全部 400 会破坏现有合法 pipeline（与 default_pipeline_service 既有过滤逻辑一致） |
| 2 | `_continue_orphan_run` 复用 `_run_single` 续跑"剩余节点"（含 waiting_hitl 节点会重新触发 HITL） | waiting_hitl 节点直接以本次决议标记完成，不重复触发 HITL | 审批刚完成又立即二次审批对用户极不友好；孤儿续跑为 best-effort，动作执行仍遵循"唯一执行点"（不重复执行） |
| 3 | `run()` 批量 gather 直接传播 CancelledError | `gather(return_exceptions=True)` + `break` 收尾到 cancelled | 使 run 任务正常返回、DB 状态一致；外部取消 run 任务本身仍正常传播 |
| 4 | `_run_llm` structured 不含 query | 新增 `query` 回显 | 支撑 P1-2 验收（断言 prompt_used/query）；纯增量字段 |

---

## 4. 变更记录（行号级，修复后文件）

### `backend/app/services/agents/pipeline_common.py`（新建，86 行）
- L22-30 `HITL_WAIT_TIMEOUT` / `HITL_EXPIRE_TTL`（环境变量可覆盖）
- L35-49 `compute_final_status`
- L54-73 `_stable_dict`
- L80-86 `_safe_sse`

### `backend/app/services/agents/guardrail_agent.py`（新建，62 行）
- L28-62 `GuardrailAgent.evaluate`

### `backend/tests/conftest.py`（新建，96 行）
- L34-55 `db_path`（function-scoped 临时 sqlite，恢复原 DB_PATH）
- L58-63 `engine`；L66-73 `run_async`；L77-92 `mock_llm`

### `backend/app/services/agents/pipeline_engine.py`（修改，约 +585 行）
- L26-38 导入 HitlApproval / pipeline_common
- L71 `PipelineRun.tasks`
- L84-92 `__init__`：移除 `_restore_hitl_events()`，新增 `_run_complete_events` / `_restored` / `_HITL_WAIT_TIMEOUT` / `_HITL_EXPIRE_TTL`
- L133 `run()`：入口 `_ensure_restored()`；L192-197 环检测；L210-228 任务登记 + gather(return_exceptions=True)；L231-235 compute_final_status；L285-307 except ValueError 兜底；L310-320 finally 完成事件 + 清理
- L310 `_run_single`：L337-347 input_params + 缓存键；L356-382 CancelledError 分支；L391-400 节点显式失败（guardrail 阻断）；L404-490 HITL 分支完整重写（审批→等待→超时/取消→approved 执行动作）
- L555 `_create_hitl_approval`
- L755 `_get_node_runner` 增加 guardrail
- L1018 `_run_root_cause` 改用 `_stage_output`
- L1128 `_run_llm` structured 回显 query
- L1246 `_run_guardrail`
- L1256 `_execute_agent`：input_params 透传 + structured/status 透传
- L1350 `_stage_output`
- L1398 `_push_sse` 用 `_safe_sse`
- L1416 `cancel()`：唤醒 HITL + 中断任务
- L1447 `resume()`：置位移出 if 块 + DB 重建 + 孤儿调度
- L1502 `_continue_orphan_run`
- L1644 `_ensure_restored`；L1662 `_expire_orphan_waiting_hitl`
- L1725 `_cleanup_expired_runs`：waiting_hitl 分支

### `backend/app/services/agents/orchestrator.py`（修改，+16 行）
- L471-486 `resume()` 模式感知分流（mode=='custom' → pipeline_engine.resume）

### `backend/app/api/agents.py`（修改，+17 行）
- L97-106 `create_agent_run` DAG 预校验（400）
- L222-228 `cancel_agent_run` 配套 pipeline_engine.cancel

### `backend/app/services/agents/agent_registry.py`（修改，+19 行）
- L224-238 `validate_pipeline` P2-2 引用未声明依赖告警

### `backend/app/services/agents/node_fixtures.py`（修改，+14 行）
- `SIMULATE_GUARDRAIL` + `_FIXTURE_MAP["guardrail"]`

---

## 5. 自测结果

### 5.1 导入自测（P2-4：模块导入不触 DB）
```
python -c "from app.services.agents.pipeline_engine import pipeline_engine; print('pipeline_engine OK')"   → OK
python -c "from app.services.agents.orchestrator import Orchestrator; print('orchestrator OK')"             → OK
python -c "from app.services.agents.guardrail_agent import GuardrailAgent; print('guardrail OK')"          → OK
python -c "from app.services.agents.pipeline_common import ..."                                            → OK (1800.0 / 86400.0)
```

### 5.2 冒烟脚本（`backend/tests/_smoke_dag_fix.py`，31/31 断言全过）
| 场景 | 结果 |
|------|------|
| DAG run 触发 HITL → approve → 执行动作 + completed + 审批 approved | ✅ |
| DAG run 触发 HITL → reject → 仅记录 + completed | ✅ |
| HITL 超时（mock 短超时）→ 审批 expired + stage failed + run failed | ✅ |
| cancel waiting_hitl → run cancelled | ✅ |
| 有环 DAG → validate_pipeline 检测 + 引擎兜底 failed | ✅ |
| input_params 透传（run 级覆盖节点级 / prompt 保留节点级） | ✅ |
| guardrail 放行 / block 阻断 / simulate fixture | ✅ |
| compute_final_status / _stable_dict / _safe_sse | ✅ |

### 5.3 orchestrator.resume 委托链路（模块级单例）
```
resumed_by: pipeline_engine | status: running → 最终 run completed
```

### 5.4 既有回归（本修复相关文件）
| 测试 | 结果 |
|------|------|
| tests/test_pipeline_node_debug.py | ✅ 7 passed |
| tests/test_pipeline_node_triage.py | ✅ passed |
| tests/test_pipeline_branch_sim.py | ✅ passed |
| tests/test_batch2_orchestrator.py | ✅ 3 passed |
| tests/test_agent_api_e2e.py | ✅ 4 passed |
| tests/test_config_default_pipeline.py | ⚠️ 全文件运行在 TestRuleCRUD 挂起（**原始代码同样挂起**，已用 git stash 验证为既有问题；单测通过） |
| tests/test_batch2_agents.py | ⚠️ 10 项失败（**原始代码同样失败**，已 stash 验证：_derive_action 签名过期、文案变更等既有问题） |
| tests/test_batch2_agents_api.py | ⚠️ 1 项失败（**原始代码同样失败**：test_create_run_reaches_waiting_hitl 期望同步 waiting_hitl 响应，实际 API 为异步 pending，stale 测试） |

**结论：本修复未引入任何回归；上述失败/挂起均已在原始代码上通过 git stash 复现，属既有问题。**

---

## 6. 提交

- commit message: `fix: DAG pipeline HITL approval gate + validation + robustness (P0-P2)`
- commit hash: `fdd4f4fe680e971503abdb47abef1231ce86672a`
- 变更规模：9 files changed, 1068 insertions(+), 58 deletions(-)
