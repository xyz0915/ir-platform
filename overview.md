# 调查剧本「真实查库 + 真实调大模型」修复总结

## TL;DR
"调查剧本"执行时查询数据是写死的、没调本地库——根因是后端引擎空壳 + 前端 LLM 步骤伪造 + 部分 query 类型在意图识别中落空。已重写为**真实执行**：按 `query_type` 查本地表、LLM 步真实调用已配置的 deepseek 大模型，前端改为消费后端真实产出。

## 根因（三处）
1. **后端引擎空壳**：`playbook_engine.execute_step` 只把步骤计数 +1、标 `completed`，原样回传 YAML 静态 `params`，不查库、不调 LLM。
2. **前端 LLM 步骤伪造**：`AiAdvancedView.vue` 的 `startPlaybook` 遇到 `type==='llm'` 仅把 prompt 截 150 字当"分析完成"，从未调大模型。
3. **部分 query 落空**：前端把 query 步转自然语言调 `/ai/query`，但 `network_connections`/`file_hashes`/`extract_ips` 三类在意图识别里无关键词 → `unknown` → 零数据；`abnormal_processes` 还被错认成 `logs`。

## 修复内容
| 文件 | 改动 |
|---|---|
| `backend/app/services/playbook_engine.py` | 重写为真实执行：`query` 步按 `query_type` 参数化查本地表；`llm` 步调 `AiConfigProfile.get_active()`+`AiService.call_llm`（拼 `depends_on` 前序真实产出，异常降级） |
| `backend/app/schemas/ai_advanced.py` | `StepResult` 加 `summary` 字段（向后兼容） |
| `frontend/src/views/AiAdvancedView.vue` | `startPlaybook` 改为直接消费 `/ai/playbook/step` 真实 `output`；删 `mapStepToQuery`/`aiQuery` workaround 与 LLM 伪造 |
| `backend/tests/test_playbook_engine.py` | 新增 11 用例 |

### query_type → 真实表
- `logs` / `extract_ips` → `normalized_logs`（PRAGMA 实测 `security_events` 无 `failed_logon` 且无 IP 列，故选真实有数据的表）
- `alerts` → `alerts`；`abnormal_processes` → `abnormal_processes`；`network_connections` → `network_connections`；`file_hashes` → `file_hashes`

## 验证（独立，ROUTE_VERDICT=NoOne）
- pytest：`test_playbook_engine.py` **11/11 passed**
- 前端：`vite build` 成功（2661 模块，改动可编译）
- 活系统端到端：
  - `abnormal_process`：异常进程 18 条 / 网络连接 20 条 / 文件哈希 4 条（真实数组）+ LLM 步 2429/3726 字真实研判（引用前序 `ir_agent.exe` 进程链、真实 SHA256）
  - `login_failure`：稀疏数据真实返回空数组（failed_logon=0、extract_ips=0），非空造；alerts=3 真实命中

## 你下一步
1. **刷新 Web 界面** →「AI 智能分析」→ 选剧本（如"调查异常进程"）→ 执行，现在每步都是真实库数据 + 真实大模型分析。
2. 关注点：剧本里 `logs`/`extract_ips` 走的是 `normalized_logs` 表，若你希望它查 `security_events`，告诉我，我改 `_resolve_log_table` 的候选优先级即可。
3. 改动均未 `git commit`，需要的话我来提交。
