# 智能体编排功能模块 — 全量代码审查报告

**日期**: 2026-07-21  
**审查范围**: orchestrator.py · api/agents.py · schemas/agent_run.py · base_agent.py · triage_agent.py · investigator_agent.py · responder_agent.py · reporter_agent.py · prompts.py · data_provider.py · agent_llm.py · ai_service.py · config.py  
**评审人**: 三组工程师并行审查  

---

## 一、P0 — 阻断级（1 项）

### P0-1: investigator_agent 核心数据源 process_events 表为空

| 文件 | 行号 | 描述 |
|------|------|------|
| `investigator_agent.py` | L133-174 | `_build_timeline()` 依赖 process_events，`_local_root_cause()` 依赖 procs，但该表当前为 **0 行** |

**影响**：调查阶段的"攻击时间线"和"根因回溯"全部落空。结果中只剩下日志数据和主机画像，信息量严重不足。

**根本原因**：process_events 需要实时 Agent 推送或批量注入，当前只有一次性的 JSON 导入，该表始终为空。

**优化建议**：
- 短期：在 process_events 表就绪前，从 `security_events` 自身字段（`event_type=process_start` 的 `_raw_extra.start_time`, `_raw_extra.name`, `_raw_extra.pid`, `_raw_extra.ppid`, `_raw_extra.command_line`）补充进程信息。
- 长期：实现 Agent 实时 ETW 进程事件采集写入 process_events。

---

## 二、P1 — 严重（14 项）

### 架构层

#### P1-1: `_state_machine` 在 multi-stage 下状态语义错误

| 文件 | 行号 | 问题 |
|------|------|------|
| `orchestrator.py` | L181-202 | 每次 dispatch 完成后设置 `status=completed`，但 pipeline 有 4 个 stage，triage 完成后 DB 中 run 显示已完成，但实际 pipeline 还在跑 |

**影响**：前端查询 run 状态会在错误的时间点显示"已完成"，引起认知混乱。

**建议**：增加 `is_final` 参数，只有最终步骤才能设为 completed；中间步骤只更新 stage。

#### P1-2: `dispatch` 全局 except 吞掉 CancelledError

| 文件 | 行号 | 问题 |
|------|------|------|
| `orchestrator.py` | L94-110 | `except Exception as exc` 捕获了 `asyncio.CancelledError`，导致编排器无法被外部取消 |

**影响**：用户取消操作、系统关闭等场景下编排器无法正常中断。

**建议**：先捕获 `asyncio.CancelledError` 并重新抛出，再捕获其他异常。

#### P1-3: `wait_hitl` 无主动通知机制

| 文件 | 行号 | 问题 |
|------|------|------|
| `orchestrator.py` | L149-178 | wait_hitl 仅写 DB，没有 WebSocket/邮件/站内信通知 |

**影响**：管理员不知道有待审批项，需要手动轮询，MTTR 风险。

**建议**：集成 WebSocket 推送或 SSE 订阅机制。

#### P1-4: `resume()` 上下文丢失

| 文件 | 行号 | 问题 |
|------|------|------|
| `orchestrator.py` | L249-308 | HITL 决议后 resume 重新构造 ctx 时只包含 `run_id`/`event_id`/`user`，丢失了 triage/investigation 的结果 |

**影响**：ReporterAgent 只能看到 hitl_decision，看不到前面的分析过程，复盘报告缺乏实质内容。

**建议**：将 ctx 持久化到 agent_runs（新增 `ctx_json` 字段），或从 agent_run_steps 重建上下文。

#### P1-5: `create_agent_run` 同步等待 pipeline 阻塞 HTTP

| 文件 | 行号 | 问题 |
|------|------|------|
| `api/agents.py` | L39-69 | 请求处理函数内 `await` 整个 pipeline，HTTP 连接保持直到 pipeline 结束 |

**影响**：大部分 HTTP 网关/负载均衡器有 30-60s 超时，pipeline 可能运行数分钟，连接强制断开。

**建议**：使用 FastAPI `BackgroundTasks` 或任务队列异步执行，前端轮询结果。

### Agent 实现层

#### P1-6: AgentResult 字段不足

| 文件 | 行号 | 问题 |
|------|------|------|
| `base_agent.py` | L11-48 | 缺少 `execution_duration_ms`, `llm_calls_count`, `usage`, `error`, `data_sources` |

**影响**：编排器无法获取阶段耗时、token 用量、错误信息，无法做 SLA 监控和成本计量。

**建议**：扩展 AgentResult dataclass，补全上述字段。

#### P1-7: LLM 降级消息的用户体验问题

| 文件 | 行号 | 问题 |
|------|------|------|
| `triage_agent.py` L109, `investigator_agent.py` L100, `responder_agent.py` L64, `reporter_agent.py` L67 | 全部 | "[LLM 摘要不可用：以上结论由真实数据直接驱动]" — 用户第一反应是"系统出错了" |

**建议**：改为中性表述：`"本阶段分析基于真实数据自动生成"`，并统一为常量。

#### P1-8: host_id 为 None 时降级路径不明确

| 文件 | 行号 | 问题 |
|------|------|------|
| `triage_agent.py` | L78-79 | host_id=None 时 logs 为空，但不提示"缺少主机信息导致无法获取日志" |

**建议**：在 output 中加入明确提示。

#### P1-9: 时间戳字段兼容性风险

| 文件 | 行号 | 问题 |
|------|------|------|
| `investigator_agent.py` | L130-150 | 使用 `event_time`/`start_time`，但 Phase 1 修复后时间戳字段可能已变 |

**建议**：统一使用 `timestamp` 字段（Phase 1 修复后的标准字段）。

#### P1-10: `_sink_case()` 写入 cases 字段不完整

| 文件 | 行号 | 问题 |
|------|------|------|
| `reporter_agent.py` | L200-219 | 只写了 name/description/status，缺少 event_ids/run_id/severity/confidence |

**影响**：沉淀的案例在 RAG 检索时无法按事件、严重度过滤，检索精度受限。

**建议**：增添 event_ids（JSON）、run_id、severity、confidence 字段。

### Prompt / 数据链路层

#### P1-11: Prompt 输出格式不明确

| 文件 | 行号 | 问题 |
|------|------|------|
| `prompts.py` | 全部 4 个 build_*_prompt | 未指定结构化输出格式（JSON/Markdown/自由文本），LLM 回复解析困难 |

**影响**：LLM 回复是不确定格式的自由文本，后续程序化解析几乎不可行。

**建议**：每个 prompt 末尾明确指定输出格式（JSON Schema 或 Markdown 模板）。

#### P1-12: "参考命中"标签语义误导

| 文件 | 行号 | 问题 |
|------|------|------|
| `prompts.py` + `data_provider.py` | 联动 | "参考命中"被标注为"命中检测规则"，LLM 可能误解为该事件确实命中了规则 |

**建议**：统一标签术语，区分"已命中检测规则"和"参考匹配线索"。

#### P1-13: 错误映射机制脆弱

| 文件 | 行号 | 问题 |
|------|------|------|
| `agent_llm.py` | L99-106 | 使用 `"ConnectionError" in type(exc).__name__` 和 `"connect" in msg.lower()` 等字符串包含检查 |

**影响**：可能误匹配（如 Exception 消息恰好包含 "connect"）。

**建议**：改用 `isinstance(exc, httpx.ConnectError)` 等类型检查。

#### P1-14: AI_ENCRYPTION_KEY 默认硬编码

| 文件 | 行号 | 问题 |
|------|------|------|
| `config.py` | L58-61 | 开发密钥 `QSLeoOZ1ZXDfBM0SrbJq1cBcRznji1L62SMCJae7nEo=` 作为默认值 |

**影响**：生产环境若未设置 `IR_AI_ENCRYPTION_KEY` 环境变量，加密形同虚设。

**建议**：生产环境检查 env var 是否被覆盖，若无则告警。

---

## 三、P2 — 可优化（21 项）

### 架构/API 层（6 项）

| # | 文件 | 问题 | 建议 |
|---|------|------|------|
| P2-1 | `orchestrator.py:205-237` | run_pipeline 串行无并行 | 无依赖阶段使用 `asyncio.gather()` |
| P2-2 | `orchestrator.py:198-201` | result.stage 未命中列表时不更新 stage | 增加 fallback |
| P2-3 | `api/agents.py:80-84` | priority 过滤在 Python 层破坏分页 | 改为 DB 层查询 |
| P2-4 | `api/agents.py` | 缺少 cancel 端点 | 新增取消运行端点 |
| P2-5 | `schemas/agent_run.py` | AgentRunCreate 缺少 priority/title | 补充字段 |
| P2-6 | `schemas/agent_run.py` | AgentRunListItem 缺少 created_at/updated_at 等 | 补充字段 |

### Agent 实现层（7 项）

| # | 文件 | 问题 | 建议 |
|---|------|------|------|
| P2-7 | `base_agent.py` | LLM 实例未共享，4 处重复 | 在 BaseAgent.__init__ 统一初始化 |
| P2-8 | `base_agent.py` | _build_prompt 空实现风险 | 改为 NotImplementedError |
| P2-9 | `triage_agent.py:142-170` | _data_driven 优先级推断维度不足 | 引入多维特征 |
| P2-10 | `triage_agent.py:173-197` | _build_data_summary 只取 events[0] | 聚合统计多条事件 |
| P2-11 | `responder_agent.py:97-135` | _derive_action 推导规则简单 | 纳入 investigation 根因 |
| P2-12 | `responder_agent.py:159-197` | ActionService 异常处理粗糙 | 区分成功/失败日志 |
| P2-13 | `reporter_agent.py:93-113` | 重复 JSON 解析 | 缓存解析结果 |

### Prompt / 数据 / LLM 层（8 项）

| # | 文件 | 问题 | 建议 |
|---|------|------|------|
| P2-14 | `data_provider.py` | get_events 无 LIMIT 子句 | 加 LIMIT 防止 OOM |
| P2-15 | `data_provider.py` | 多处 SELECT * | 改为 SELECT 具体字段 |
| P2-16 | `data_provider.py` | retrieve_cases 未返回相关性评分 | 增加 score 字段 |
| P2-17 | `agent_llm.py` | 输入截断逻辑为前截断（可能截掉关键数据） | 改为后截断或智能截断 |
| P2-18 | `agent_llm.py:77-116` | AiService.call_llm 超时 120s 但编排 3 次串行，CircuitBreaker 参数不匹配 | 评估 breaker 参数 |
| P2-19 | `prompts.py` | 中文字符对 token 估算偏差 | FIXME 注释表明已知问题 |
| P2-20 | `data_provider.py` | 中文 prompt 中混用英文逗号/换行 | 统一格式 |
| P2-21 | `config.py` | AI_INPUT_BUDGET 默认值检查 | 评估是否需扩容 |

---

## 四、输出价值缺乏的根因分析

### 根因 1：process_events 表为空 → 调查阶段实质性不可用（P0）

```
investigator_agent.run()
  ├─ _build_timeline()  → process_events 为空 → 时间线无进程事件
  ├─ _local_root_cause() → 无进程事件 → 返回"无法推断第一触发点"
  └─ 证据链 → extract_process_refs → 空列表
      ↓
  调查报告 ≈ "有 N 条日志，但查不到任何进程活动"
```

**建议**：从 security_events 的 `event_type=process_start` 及其 `_raw_extra` 字段补充进程数据。

### 根因 2：resume 上下文丢失 → reporter 输出空洞（P1）

```
HITL 审批后 resume()
  └─ ctx = {event_id, user}      ← 没有 triage/investigation 结果
      ↓
  reporter_agent.run()
    └─ ctx["triage"] ??        → undefined
    └─ ctx["investigation"] ?? → undefined  
        ↓
    报告 ≈ 只有 HITL 的审批结果，没有分析过程
```

**建议**：ctx 持久化到 agent_runs 表。

### 根因 3：Prompt 无结构化输出要求 → LLM 回复解析困难（P1）

```
LLM 收到: "请分析安全事件..."
LLM 回复: "该事件是可疑的，因为..."
         ↓
  无人解析这段自然语言，用户看到的是一大段 AI 自由文本
```

**建议**：每个 prompt 末尾指定 JSON Schema 输出格式。

### 根因 4：串行执行 + 同步 HTTP → 30s 超时（已修复）

已在上一版本通过增加 axios timeout 修复。

---

## 五、优先级执行路线图

```
本周（P0 + P1 快速修复）:
  ├─ P0-1: investigator_agent 补充 security_events 进程数据    → 1 天
  ├─ P1-1/P1-2: _state_machine + CancelledError 修复          → 0.5 天
  ├─ P1-4: ctx 持久化                                         → 0.5 天
  ├─ P1-5: 异步 BackgroundTasks                               → 1 天
  ├─ P1-11: Prompt 结构化输出格式                              → 1 天
  ├─ P1-13: 错误映射修复                                       → 0.5 天
  └─ P1-14: 加密密钥告警                                       → 0.5 天

下周（P2 批量化）:
  ├─ Agent 层（P2-7 到 P2-13）                                → 2 天
  ├─ 数据链路层（P2-14 到 P2-21）                              → 2 天
  ├─ API/Schema 层（P2-1 到 P2-6）                            → 1 天
  └─ notify 机制 + WebSocket                                  → 3 天
```
