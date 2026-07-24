import type { ID, ISODateTime, RunStatus, Severity } from './common';
import type { GuardrailHit } from './guardrail';

/** Agent 来源：内置（平台预置）或自定义 */
export type AgentKind = 'builtin' | 'custom';

/** Agent 状态 */
export type AgentStatus = 'active' | 'draft' | 'disabled';

/** 自定义 Agent 配置 —— 对齐 F2 / M0 修空壳（display_name/data_sources/depends_on） */
export interface AgentConfig {
  agent_id: ID;
  display_name: string;
  kind: AgentKind;
  description: string;
  /** F2: 数据来源（如 终端日志 / 流量镜像 / 威胁情报） */
  data_sources: string[];
  /** F2: 依赖（其它 agent_id 或能力名） */
  depends_on: string[];
  /** 关联 ToolRegistry 的工具 id 列表 */
  tools: ID[];
  /** 关联 AgentLLM 多模型（F10）profile_id */
  model_profile: ID;
  status: AgentStatus;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

/** Agent 运行步骤 —— 对齐 step_* SSE 协议 */
export interface AgentRunStep {
  step_id: ID;
  run_id: ID;
  name: string;
  kind: 'tool' | 'llm' | 'hitl' | 'guardrail' | 'plan' | 'reflect';
  status: RunStatus;
  started_at?: ISODateTime;
  finished_at?: ISODateTime;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  token_usage?: number;
  error?: string;
  /** 当 kind==='hitl' 时关联的 HitlTask id */
  hitl_ref?: ID;
}

/** Agent 运行记录 —— 对齐 AgentRun 落库（F9 续跑基础） */
export interface AgentRun {
  run_id: ID;
  agent_id: ID;
  agent_name: string;
  pipeline_id?: ID;
  status: RunStatus;
  trigger: 'manual' | 'schedule' | 'webhook';
  started_at: ISODateTime;
  finished_at?: ISODateTime;
  steps: AgentRunStep[];
  guardrail_hits: GuardrailHit[];
  hitl_tasks: ID[];
  summary: string;
  /** 触发严重级别（用于 Dashboard 排序/着色） */
  severity?: Severity;
}
