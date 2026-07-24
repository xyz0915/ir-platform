import type { ID, ISODateTime, Role } from './common';

/** HITL 审批决策状态 */
export type HitlDecision = 'pending' | 'approved' | 'rejected';

/** HITL 审批决策中文标签 */
export const HITL_DECISION_LABELS: Record<HitlDecision, string> = {
  pending: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
};

/** 护栏校验结果（与 Guardrails 联动） */
export interface GuardrailResult {
  policy_id: ID;
  /** 是否命中白名单（命中则通常可自动放行） */
  whitelist_hit: boolean;
  /** 是否需要二次确认 */
  requires_confirm: boolean;
  /** 是否需要回滚预案 */
  requires_rollback_plan: boolean;
  /** 是否通过护栏校验 */
  passed: boolean;
}

/** 人工审核任务 —— 对齐 hitl_approval 表 */
export interface HitlTask {
  approval_id: ID;
  run_id: ID;
  agent_name: string;
  /** 拟执行的动作（如「隔离主机 WIN-EXP-01」） */
  action: string;
  /** 影响范围（如「1 台主机 / 生产网段」） */
  impact_scope: string;
  /** 触发上下文（触发智能体、证据、风险等） */
  context: Record<string, unknown>;
  guardrail_result: GuardrailResult;
  status: HitlDecision;
  /** 指派给的角色 */
  assigned_to?: Role;
  created_at: ISODateTime;
  decided_at?: ISODateTime;
  /** 审批/拒绝原因（审计写回） */
  reason?: string;
}
