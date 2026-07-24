import type { ID, ISODateTime } from './common';

/** 链路追踪 span */
export interface TraceSpan {
  span_id: ID;
  parent_id?: ID;
  name: string;
  started_at: ISODateTime;
  duration_ms: number;
}

/** 结构化日志条目 */
export interface LogEntry {
  ts: ISODateTime;
  level: 'debug' | 'info' | 'warn' | 'error';
  message: string;
}

/** 可观测性运行记录 —— 对齐 F7（trace / 日志 / 续跑点 resume_point） */
export interface ObservabilityRun {
  run_id: ID;
  agent_name: string;
  trace: TraceSpan[];
  logs: LogEntry[];
  /** F9 续跑点：中断时可从此 step 恢复 */
  resume_point?: ID;
}
