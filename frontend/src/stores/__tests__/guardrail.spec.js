/**
 * GuardrailStore（M7 反空壳校验）。
 *
 * A1 后 USE_MOCK.guardrail=false，facade 已路由真实后端；本测试在无后端环境下
 * 运行，故 mock @/api/agent facade 层，仅验证 Store 的编排/归一化逻辑。
 * 真实后端契约由 QA 环节通过 Network 验证（设计 §2 A1 测试要点）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const agentApi = vi.hoisted(() => ({
  guardrail: {
    listPolicies: vi.fn(),
    createPolicy: vi.fn(),
    updatePolicy: vi.fn(),
    deletePolicy: vi.fn(),
    evaluate: vi.fn(),
    listHits: vi.fn(),
  },
}))
vi.mock('@/api/agent', () => ({ default: agentApi }))

import { useGuardrailStore } from '../guardrail'

const POLICY_1 = {
  policy_id: 'gp-host-isolate',
  name: '高危主机操作白名单',
  action_pattern: 'host:isolate:*',
  whitelist: ['host:isolate:WIN-EXP-01'],
  risk_level: 'critical',
  require_confirm: true,
  rollback_plan: '从隔离 VLAN 移除并恢复网络访问。',
  enabled: true,
}

describe('GuardrailStore（M7 反空壳校验）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    agentApi.guardrail.listPolicies.mockResolvedValue({
      code: 0, data: [POLICY_1], message: 'success',
    })
    agentApi.guardrail.listHits.mockResolvedValue({
      code: 0, data: [{ policy_id: 'gp-fw-block', action: 'fw:block:x', passed: false }], message: 'success',
    })
    agentApi.guardrail.createPolicy.mockResolvedValue({
      code: 0, data: { ...POLICY_1, policy_id: 'gp-test', name: '测试策略', action_pattern: 'test:*' }, message: 'success',
    })
  })

  it('listPolicies 返回策略且字段完整', async () => {
    const store = useGuardrailStore()
    await store.fetchPolicies()
    expect(store.policies.length).toBeGreaterThan(0)
    const p = store.policies[0]
    expect(p.policy_id).toBeTruthy()
    expect(p).toHaveProperty('action_pattern')
    expect(p).toHaveProperty('risk_level')
    expect(agentApi.guardrail.listPolicies).toHaveBeenCalledTimes(1)
  })

  it('evaluate 白名单命中 → 通过且 whitelist_hit=true', async () => {
    agentApi.guardrail.evaluate.mockResolvedValue({
      code: 0,
      data: {
        policy_id: 'gp-host-isolate',
        whitelist_hit: true,
        requires_confirm: true,
        requires_rollback_plan: true,
        passed: true,
      },
      message: 'success',
    })
    const store = useGuardrailStore()
    const r = await store.evaluate('host:isolate:WIN-EXP-01')
    expect(r).toHaveProperty('policy_id')
    expect(r).toHaveProperty('passed')
    expect(r).toHaveProperty('whitelist_hit')
    expect(r.whitelist_hit).toBe(true)
    expect(r.passed).toBe(true)
    expect(agentApi.guardrail.evaluate).toHaveBeenCalledWith('host:isolate:WIN-EXP-01', undefined)
  })

  it('evaluate 命中策略但未白名单命中（有回滚预案）→ 仍通过', async () => {
    agentApi.guardrail.evaluate.mockResolvedValue({
      code: 0,
      data: {
        policy_id: 'gp-host-isolate',
        whitelist_hit: false,
        requires_confirm: true,
        requires_rollback_plan: true,
        passed: true,
      },
      message: 'success',
    })
    const store = useGuardrailStore()
    const r = await store.evaluate('host:isolate:OTHER-HOST')
    expect(r.policy_id).toBeTruthy()
    expect(r.whitelist_hit).toBe(false)
    // 策略含回滚预案 → 按算法判定通过
    expect(r.passed).toBe(true)
  })

  it('createPolicy 会话内即时生效（CRUD 闭环）', async () => {
    const store = useGuardrailStore()
    await store.fetchPolicies()
    const before = store.policies.length
    await store.createPolicy({
      name: '测试策略',
      action_pattern: 'test:*',
      risk_level: 'low',
      require_confirm: false,
      rollback_plan: '',
      enabled: true,
      whitelist: [],
    })
    expect(store.policies.length).toBe(before + 1)
    expect(agentApi.guardrail.createPolicy).toHaveBeenCalledTimes(1)
  })
})
