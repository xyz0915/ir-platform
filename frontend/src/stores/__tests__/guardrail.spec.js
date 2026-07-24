import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useGuardrailStore } from '../guardrail'

describe('GuardrailStore（M7 反空壳校验）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('listPolicies 返回策略且字段完整', async () => {
    const store = useGuardrailStore()
    await store.fetchPolicies()
    expect(store.policies.length).toBeGreaterThan(0)
    const p = store.policies[0]
    expect(p.policy_id).toBeTruthy()
    expect(p).toHaveProperty('action_pattern')
    expect(p).toHaveProperty('risk_level')
  })

  it('evaluate 白名单命中 → 通过且 whitelist_hit=true', async () => {
    const store = useGuardrailStore()
    const r = await store.evaluate('host:isolate:WIN-EXP-01')
    expect(r).toHaveProperty('policy_id')
    expect(r).toHaveProperty('passed')
    expect(r).toHaveProperty('whitelist_hit')
    expect(r.whitelist_hit).toBe(true)
    expect(r.passed).toBe(true)
  })

  it('evaluate 命中策略但未白名单命中（有回滚预案）→ 仍通过', async () => {
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
  })
})
