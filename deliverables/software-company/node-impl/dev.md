# 流水线节点库 11 节点真实化 — 开发说明（dev.md）

> 工程师：Alex（software-engineer）｜日期：2026-08-03
> 上游：`design.md`（A0 审计结论 / A1 需求总表 / A2 架构决策 / A3 详细设计 / A4 配置面板 / A5 接口定义 / B3 共享知识）
> 范围：T01（后端基础设施）+ T02（后端 10 runner + llm 增强）+ T03（前端类型系统）+ T04（前端配置面板）；T05 测试由 QA 执行

---

## 1. 修改 / 新建文件清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `backend/app/services/agents/pipeline_engine.py` | 修改 | runner 注册表 +10 键（含 guard P0 修复）；`_execute_agent` hitl 透传 1 行；新增 9 个 runner + 4 个公共助手；`_run_llm` 增加 `allow_default_llm` |
| `backend/app/services/agents/preset_data.py` | 修改 | `PRESET_AGENTS` 新增 10 条（guard/hitl/condition/parallel/data-process/intel-query/action/output/mcp-tool/intel-source），10 → 20 条 |
| `backend/app/services/agents/node_fixtures.py` | 修改 | 新增 10 个 simulate fixture + `_FIXTURE_MAP` 10 个键 |
| `frontend/src/constants/pipelineTypes.js` | 修改 | NodeType +6 值；NodeTypeMeta +6 条；`NODE_DEFAULT_INPUT_PARAMS`（11 类默认 input_params）；`ACTION_OPTIONS`；createNodeData 注入 `config.input_params` |
| `frontend/src/components/agents/pipeline/NodeLibrary.vue` | 修改 | 6 个新节点由字符串字面量改用 NodeType 常量（消除 guard/guardrail 类错位风险） |
| `frontend/src/components/agents/pipeline/ConfigPanel.vue` | 修改 | 新增「节点参数」区（11 种字段表单：文本/下拉/开关/JSON textarea/动态行数组） |
| `deliverables/software-company/node-impl/dev.md` | 新建 | 本文档 |

---

## 2. 后端实现说明（行号级）

### 2.1 T01 基础设施

| 改动 | 位置 | 说明 |
|------|------|------|
| runner 注册表 +10 键 | `pipeline_engine.py` L765-800（`_get_node_runner`） | 新增 `"guard": self._run_guardrail`（**P0 修复**：前端 `GUARD='guard'`，原注册表只有 `'guardrail'`）、`"hitl"`、`"condition"`、`"parallel"`、`"data-process"`、`"intel-query"`、`"action"`、`"output"`、`"mcp-tool"`、`"intel-source"`；`"guardrail"` 保留向后兼容。runner 键 = 前端 NodeType 字符串（B3 #1） |
| HITL 标志透传 | `pipeline_engine.py` L2287（`_execute_agent`） | `"hitl_triggered": result.get("hitl_triggered", False)`（原硬编码 `False`，A0 审计 #4 的 1 行修复） |
| 公共助手 | `pipeline_engine.py` L1995-2199 | `_jsonpath_get`（点路径+`[n]` 整数索引，L1996）、`_read_dep_output`（解析 `{dep:name}` 占位 + 点路径，L2029）、`_parse_literal`（L2058）、`_eval_operand`（L2086）、`_eval_condition_expr`（表达式求值，L2103）、`_extract_keywords`（output 节点 keyword 兜底，L2181） |
| preset agents | `preset_data.py` L117-288 | 10 条 `name`=runner 键、`type="custom"`、`hitl=True` 仅 hitl 节点、`depends_on=[]`；hitl 的 `config` 顶层带 `action/target/auto_rollback_plan`（供 `_create_hitl_approval` 读取）+ `config.input_params`（供 runner 合并） |
| simulate fixtures | `node_fixtures.py` L299-475 + `_FIXTURE_MAP` L476-489 | 10 个 fixture 与真实 runner 返回同构 |

### 2.2 T02 10 个 runner（统一签名 `(ctx, input_params, mode) -> dict`）

| 节点 | 位置 | 实现要点 |
|------|------|----------|
| `guard` | 复用 `_run_guardrail`（L1549）+ 注册表修复 | 委托 `GuardrailAgent.evaluate`，`block=true` 返回 `status="blocked"` 阻断下游 |
| `hitl` | `_run_hitl` L1564 | 返回 `hitl_triggered=True` + action/target/auto_rollback_plan；审批创建/等待/恢复全部复用 `_run_single` L430-528 既有 HITL 分支（`_create_hitl_approval` → SSE → resume → `ResponderAgent.execute_action`） |
| `condition` | `_run_condition` L1590 | 逐条求值 `input_params.conditions`，短路取首个命中；输出 `branch_taken/condition_met/evaluations/downstream_active`；单条表达式异常只记 error 不阻断（A2 决策 1：输出控制信号，不物理剪枝） |
| `parallel` | `_run_parallel` L1635 | 纯标记节点：输出 `branches` + `parallel_mode="batch"`；下游声明 `depends_on=[parallel 节点名]` 由拓扑排序天然同批并行（A2 决策 2，零引擎改动） |
| `data-process` | `_run_data_process` L1658 | `source`（`{dep:name}.path`，缺省取全部前置 stage 输出拼接）→ `operations` 顺序执行 select/filter(regex)/rename/limit；单条 op 异常记 errors 继续 |
| `intel-query` | `_run_intel_query` L1747 | 仅 ip/domain（hash 友好报错 `unsupported_ioc_type`）；复用 `EnrichmentService.instance().enrich_ioc`，`asyncio.to_thread` + 60s 超时包裹；任何外部异常 → `status="failed"` + 可读 error |
| `action` | `_run_action` L1813 | 复用 `ActionService.execute`（7 种动作）+ `disposition_service.add_disposition` 写处置日志（失败仅 warning）；`require_hitl=true` 返回 `hitl_triggered=True` 复用审批链（注：preset `hitl=False`，整管路径下仅单节点调试/自定义 hitl agent 触发等待，见 §5 已知边界） |
| `output` | `_run_output` L1871 | 复用 `KnowledgeRetriever.retrieve`（`asyncio.to_thread`）；keyword 为空用 `_extract_keywords` 兜底；chroma 不可用由服务层关键词回退 |
| `mcp-tool` | `_run_mcp_tool` L1914 | 复用 `_run_tools_safe` 单工具路径；`input_params.args` 注入 `ctx.input_params.tool_args[tool_id]`；工具未注册/超时 → evidence 记 failed + errors，**不阻断** node |
| `intel-source` | `_run_intel_source` L1954 | 只读 `ThreatIntelProviderConfig.load()`，过滤 enabled/provider，剔除 `api_key_ref`；无外部 IO |

### 2.3 llm 增强

`_run_llm` L1182：新增 `allow_default_llm` 开关（默认 **False**，保持"零意外联网"）。开启后无显式 `model_profile` 时 `profile = self._resolve_llm_profile("")`（激活 profile 最终兜底）；structured 增加 `allow_default_llm` 标记（L1210 附近）。

---

## 3. 前端实现说明（行号级）

### 3.1 T03 类型系统（pipelineTypes.js）

- `NodeType` L34-39：新增 `CONDITION='condition'`、`PARALLEL='parallel'`、`DATA_PROCESS='data-process'`、`INTEL_QUERY='intel-query'`、`MCP_TOOL='mcp-tool'`、`INTEL_SOURCE='intel-source'`（值 = 后端 runner key）
- `NodeTypeMeta`：6 条新元信息（label/icon/phase/badgeColor/track）
- `NODE_DEFAULT_INPUT_PARAMS` L237-250：11 个节点类型的默认 `input_params` 骨架
- `ACTION_OPTIONS` L252：7 种处置动作下拉选项
- `createNodeData`：`config.input_params` 注入默认骨架（A4 存储约定：所有节点参数写入 `node.config.input_params`）

### 3.2 节点库常量化（NodeLibrary.vue）

L52-85：condition/parallel/data-process/intel-query/mcp-tool/intel-source 由字符串字面量改用 `NodeType` 常量 + `NodeTypeMeta` icon。

### 3.3 T04 配置面板（ConfigPanel.vue）

- 模板「节点参数」区 L73-187：按 `node.type` 渲染字段，读写 `node.config.input_params`
- script L190-320：`nodeParamsVisible`（11 类型集合）、`updateInputParam`、JSON 字段编辑（`updateJsonField`）、动态行数组（conditions/branches/operations 的 add/update/remove）
- 样式 L581-650：`.cfg-input` / `.cfg-switch`（开关）/ `.cfg-cond-row` / `.cfg-op-row`

字段覆盖（A4 表）：
- guard：policy / checks(JSON) / block(switch) / reason
- hitl：action(下拉) / target(JSON) / reason
- condition：source + conditions[]（label/expr 动态行）
- parallel：branches[]（label/target 动态行）
- data-process：source + operations[]（op 下拉 + select fields / filter field+regex / rename mapping / limit n）
- intel-query：ioc_type(下拉 ip/domain) / ioc_value / provider_name
- action：action(下拉) / target(JSON) / operator / require_hitl(switch)
- output：keyword / category / limit(number)
- mcp-tool：tool_id / args(JSON)
- intel-source：enabled_only(switch) / provider
- llm：model_profile / agent_ref / allow_default_llm(switch)

---

## 4. 自测结果

### 4.1 后端导入 + runner 注册

```
engine OK
presets: 20
guard runner: OK / condition runner: OK / hitl runner: OK
data-process runner: OK / intel-query runner: OK / action runner: OK
output runner: OK / mcp-tool runner: OK / intel-source runner: OK
parallel runner: OK / guardrail runner (compat): OK
```

### 4.2 10 runner 功能自测（脚本化，零外部 IO）

| 节点 | 结果 |
|------|------|
| condition `{dep:root_cause}.structured.used_llm == true` | branch=高危, met=True |
| condition 无命中 | branch=None, met=False |
| condition contains / regex / 非法表达式 | c=True, r=True, bad=False（fail-safe） |
| hitl | hitl_triggered=True, action=block_ip |
| parallel | branch_count=2, mode=batch |
| data-process select→filter→rename→limit | `[{"name":"a.dll"}]`, errors=[] |
| intel-query hash 类型 | status=failed, error=unsupported_ioc_type |
| intel-query 缺 ioc_value | status=failed, error=missing_ioc_value |
| action require_hitl | hitl_triggered=True, mode=hitl |
| mcp-tool 缺 tool_id | status=failed, error=missing_tool_id |
| intel-source | count=1, 无 api_key_ref 泄露 |
| output keyword 检索 | count=3, kw=勒索软件（chroma 不可用走关键词回退） |
| llm 默认（allow_default_llm=false） | used_llm=False, allow=False（零意外联网） |
| `_jsonpath_get({'a':{'b':[10,20]}}, 'a.b[1]')` | 20 |
| `_read_dep_output(ctx, '{dep:root_cause}.structured.used_llm')` | True |

### 4.3 回归

- 前端 `vitest run`：**37 passed**（pipelineTypes.palette-extend 24 + NodeLibrary 4 + DebugPanel 6 + PipelineNode.typeTag 3）
- 前端 `npx vite build --outDir <临时目录>`：**构建成功**（38.57s，仅 chunk>500kB 警告；验证后已清理临时 dist）
- 后端 `pytest`（test_pipeline_node_debug / test_pipeline_branch_sim / test_dag_hitl_flow / test_preset_meta / test_p0_custom_agent_real_execution / test_p1_llm_agent_ref）：**52 passed**（仅 Pydantic 弃用警告）

---

## 5. 已知边界与设计取舍（偏离/说明）

1. **action(require_hitl) 在整管路径不自动等待审批**：`_run_single` L430 触发 HITL 需 `agent_def.hitl == True`，而按团队指令 preset `hitl=True 仅 hitl 节点`，action preset `hitl=False`。因此 action 节点配置 `require_hitl=true` 时返回 `hitl_triggered=True` 信号（单节点调试可见；自定义 agent 若将 hitl 置 True 即走同一审批链）。这是对 A3.7 与 A2 决策 4 的显式取舍，符合任务指令。
2. **condition 不物理剪枝**（A2 决策 1）：输出 `condition_met/branch_taken` 信号，被裁剪分支若仍声明依赖会被执行；后续迭代可支持"节点级 skip"（输入参数约定）。
3. **表达式求值为子集实现**：比较运算符按 `>= <= == != > <` 顺序 `split(op,1)`，字面量中含运算符的极端表达式（如字符串值内含 `==`）可能解析偏差；单条异常 fail-safe 为 `result=false`，不阻断节点。
4. **整管路径节点名 = 注册 agent 名**（B3 #5 历史脆弱性）：新节点均注册 name=type 的 preset agent，画布节点名请使用类型字符串或与预设一致（本期不重构前端 runPipeline 的 name 发送逻辑）。

---

## 6. 提交

`feat: implement 11 pipeline node types — guard/hitl/condition/parallel/data-process/intel-query/action/output/mcp-tool/intel-source + llm enhance`
