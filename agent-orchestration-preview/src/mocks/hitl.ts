import type { HitlTask } from '@/types';
import { clone, delay, ok, type ApiResponse } from './util';

/** 人工审核任务队列（对齐 hitl_approval 表） */
export const HITL_TASKS: HitlTask[] = [
  {
    approval_id: 'hitl-001',
    run_id: 'run-002',
    agent_name: '处置响应 Agent',
    action: '隔离主机 WIN-EXP-01',
    impact_scope: '1 台主机 / 生产网段',
    context: {
      trigger_agent: '处置响应 Agent',
      evidence: '检测到 lsass 凭据窃取行为，MITRE ATT&CK T1003',
      risk: 'critical',
      suggested_by: 'rootcause: 异常进程创建源自钓鱼文档',
    },
    guardrail_result: {
      policy_id: 'gp-host-isolate',
      whitelist_hit: false,
      requires_confirm: true,
      requires_rollback_plan: true,
      passed: true,
    },
    status: 'pending',
    assigned_to: 'soc_lead',
    created_at: '2026-07-06T15:55:26.000Z',
  },
  {
    approval_id: 'hitl-002',
    run_id: 'run-006',
    agent_name: '处置响应 Agent',
    action: '阻断出口防火墙策略 10.20.0.0/16 out',
    impact_scope: '生产网段出向流量',
    context: {
      trigger_agent: '处置响应 Agent',
      evidence: '主机与已知 C2 185.220.101.45 持续通信',
      risk: 'high',
      suggested_by: 'netflow: 异常外联峰值',
    },
    guardrail_result: {
      policy_id: 'gp-fw-block',
      whitelist_hit: false,
      requires_confirm: true,
      requires_rollback_plan: true,
      passed: true,
    },
    status: 'pending',
    assigned_to: 'analyst',
    created_at: '2026-07-06T11:20:16.000Z',
  },
  {
    approval_id: 'hitl-003',
    run_id: 'run-007',
    agent_name: '钓鱼事件快处 Agent',
    action: '冻结账户 alice.zhang',
    impact_scope: '1 个员工账户',
    context: {
      trigger_agent: '钓鱼事件快处 Agent',
      evidence: '该账户在异常地理位置登录并下载大量邮件',
      risk: 'high',
      suggested_by: '邮件网关告警',
    },
    guardrail_result: {
      policy_id: 'gp-account-freeze',
      whitelist_hit: false,
      requires_confirm: true,
      requires_rollback_plan: true,
      passed: true,
    },
    status: 'approved',
    assigned_to: 'admin',
    created_at: '2026-07-06T10:05:00.000Z',
    decided_at: '2026-07-06T10:12:30.000Z',
    reason: '已确认异常登录，批准冻结并通知主管。',
  },
];

/** 读取 HITL 任务队列 */
export const getHitlTasks = async (): Promise<ApiResponse<HitlTask[]>> => {
  await delay();
  return ok(clone(HITL_TASKS));
};

/** 按 id 读取任务 */
export const getHitlById = (id: string): HitlTask | undefined =>
  HITL_TASKS.find((t) => t.approval_id === id);
