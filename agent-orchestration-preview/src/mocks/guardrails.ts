import type { GuardrailHit, GuardrailPolicy } from '@/types';
import { clone, delay, ok, type ApiResponse } from './util';

/** 护栏策略（F8 P0：action 白名单 + 高危确认 + 回滚预案） */
const GUARDRAIL_POLICIES: GuardrailPolicy[] = [
  {
    policy_id: 'gp-host-isolate',
    name: '高危主机操作白名单',
    action_pattern: 'host:isolate:*',
    whitelist: ['host:isolate:WIN-EXP-01'],
    risk_level: 'critical',
    require_confirm: true,
    rollback_plan: '从隔离 VLAN 移除并恢复网络访问（EDR 一键回连）。',
    enabled: true,
  },
  {
    policy_id: 'gp-fw-block',
    name: '网络阻断确认',
    action_pattern: 'fw:block:*',
    whitelist: [],
    risk_level: 'high',
    require_confirm: true,
    rollback_plan: '删除对应防火墙策略条目即可恢复出向。',
    enabled: true,
  },
  {
    policy_id: 'gp-account-freeze',
    name: '账户冻结确认',
    action_pattern: 'account:freeze:*',
    whitelist: [],
    risk_level: 'high',
    require_confirm: true,
    rollback_plan: '解冻账户并重置临时口令。',
    enabled: true,
  },
  {
    policy_id: 'gp-db-delete',
    name: '数据删除回滚',
    action_pattern: 'db:delete:*',
    whitelist: [],
    risk_level: 'critical',
    require_confirm: true,
    rollback_plan: '执行前必须创建数据库快照（tool:db-snapshot）用于回滚。',
    enabled: false,
  },
];

/** 护栏命中记录（运行期统计） */
export const GUARDRAIL_HITS: GuardrailHit[] = [
  {
    policy_id: 'gp-host-isolate',
    run_id: 'run-002',
    action: 'host:isolate:WIN-EXP-01',
    passed: true,
    timestamp: '2026-07-06T15:55:25.000Z',
  },
  {
    policy_id: 'gp-fw-block',
    run_id: 'run-006',
    action: 'fw:block:10.20.0.0/16:out',
    passed: true,
    timestamp: '2026-07-06T11:20:15.000Z',
  },
  {
    policy_id: 'gp-db-delete',
    run_id: 'run-008',
    action: 'db:delete:audit-log',
    passed: false,
    timestamp: '2026-07-06T09:30:00.000Z',
  },
];

/** 读取护栏策略 */
export const getGuardrailPolicies = async (): Promise<ApiResponse<GuardrailPolicy[]>> => {
  await delay();
  return ok(clone(GUARDRAIL_POLICIES));
};

/** 读取护栏命中记录 */
export const getGuardrailHits = async (): Promise<ApiResponse<GuardrailHit[]>> => {
  await delay();
  return ok(clone(GUARDRAIL_HITS));
};
