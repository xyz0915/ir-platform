import type { ID, ISODateTime, Severity } from './common';

/** 护栏策略 —— 对齐 F8 护栏（P0，上线硬前提） */
export interface GuardrailPolicy {
  policy_id: ID;
  name: string;
  /** action 正则/通配模式（如「host:isolate:*」） */
  action_pattern: string;
  /** action 白名单（命中的动作可自动放行） */
  whitelist: string[];
  risk_level: Severity;
  /** 是否强制人工确认 */
  require_confirm: boolean;
  /** 回滚预案描述 */
  rollback_plan: string;
  enabled: boolean;
}

/** 护栏命中记录（运行期统计） */
export interface GuardrailHit {
  policy_id: ID;
  run_id: ID;
  action: string;
  passed: boolean;
  timestamp: ISODateTime;
}
