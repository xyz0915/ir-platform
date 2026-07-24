/**
 * M7 护栏与安全 Mock 适配器。
 *
 * 暴露：listPolicies / createPolicy / updatePolicy / deletePolicy /
 *       evaluate(action, ctx) / listHits
 * - evaluate() 严格返回 GuardrailResult（对齐 demo types/hitl.ts 的 guardrail_result）。
 * - 内存可变数组维护，CRUD 会话内即时生效（刷新页面重置，符合预览态）。
 *
 * 设计依据：01-api-spec.md §7。
 */
import { clone, delay, ok, escapeRegExp, nowISO } from './util'

/** 护栏策略（F8 P0：action 白名单 + 高危确认 + 回滚预案） */
const GUARDRAIL_POLICIES = [
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
]

/** 护栏命中记录（运行期统计，M1 护栏拦截数来源） */
const GUARDRAIL_HITS = [
  { policy_id: 'gp-host-isolate', run_id: 'run-002', action: 'host:isolate:WIN-EXP-01', passed: true, timestamp: '2026-07-06T15:55:25.000Z' },
  { policy_id: 'gp-fw-block', run_id: 'run-006', action: 'fw:block:10.20.0.0/16:out', passed: true, timestamp: '2026-07-06T11:20:15.000Z' },
  { policy_id: 'gp-db-delete', run_id: 'run-008', action: 'db:delete:audit-log', passed: false, timestamp: '2026-07-06T09:30:00.000Z' },
]

/** action 是否命中通配模式（如 'host:isolate:*'） */
function matchPattern(pattern, action) {
  if (!pattern) return false
  const re = new RegExp('^' + pattern.split('*').map(escapeRegExp).join('.*') + '$')
  return re.test(action)
}

/** 计算护栏结果（01-api-spec.md §7.3 约定） */
function computeResult(action) {
  const policy = GUARDRAIL_POLICIES.find((p) => p.enabled && matchPattern(p.action_pattern, action))
  if (!policy) {
    // 无策略命中 → 放行
    return {
      policy_id: '',
      whitelist_hit: false,
      requires_confirm: false,
      requires_rollback_plan: false,
      passed: true,
    }
  }
  const whitelist_hit = policy.whitelist.includes(action)
  const requires_confirm = !!policy.require_confirm
  const requires_rollback_plan = !!policy.rollback_plan
  const highRisk = ['high', 'critical'].includes(policy.risk_level)
  // 通过判定：非（未命中白名单 且 高危 且 未配回滚预案）
  const passed = !( !whitelist_hit && highRisk && !requires_rollback_plan )
  return {
    policy_id: policy.policy_id,
    whitelist_hit,
    requires_confirm,
    requires_rollback_plan,
    passed,
  }
}

export async function listPolicies() {
  await delay()
  return ok(clone(GUARDRAIL_POLICIES))
}

export async function createPolicy(policy) {
  await delay()
  const next = {
    ...policy,
    policy_id: policy.policy_id || `gp-${Date.now()}`,
  }
  GUARDRAIL_POLICIES.push(next)
  return ok(clone(next))
}

export async function updatePolicy(policy) {
  await delay()
  const idx = GUARDRAIL_POLICIES.findIndex((p) => p.policy_id === policy.policy_id)
  if (idx >= 0) {
    GUARDRAIL_POLICIES[idx] = { ...GUARDRAIL_POLICIES[idx], ...policy }
    return ok(clone(GUARDRAIL_POLICIES[idx]))
  }
  return ok(clone(policy))
}

export async function deletePolicy(policyId) {
  await delay()
  const idx = GUARDRAIL_POLICIES.findIndex((p) => p.policy_id === policyId)
  if (idx >= 0) GUARDRAIL_POLICIES.splice(idx, 1)
  return ok(null)
}

/**
 * 计算护栏结果（热插拔：当前 Mock，后端 F8 就绪后由 agentApi 切换为真实评估）。
 * @param {string} action - 拟执行的动作（如 'host:isolate:WIN-EXP-01'）
 * @param {Record<string,unknown>} [ctx] - 触发上下文（预留字段，对齐 demo）
 */
export async function evaluate(action, ctx) {
  await delay()
  void ctx
  const result = computeResult(action)
  // 记录一次命中（用于 M1 护栏拦截数实时统计）
  GUARDRAIL_HITS.push({
    policy_id: result.policy_id || 'none',
    run_id: (ctx && ctx.run_id) || 'mock',
    action,
    passed: result.passed,
    timestamp: nowISO(),
  })
  return ok(clone(result))
}

export async function listHits() {
  await delay()
  return ok(clone(GUARDRAIL_HITS))
}
