/**
 * M7 护栏 Store 单元测试（CRUD/评估/状态机/异常兜底）。
 * 与既有 src/stores/__tests__/guardrail.spec.js 互补（本文件侧重 store 状态机）。
 *
 * 设计依据：01-api-spec.md §7 / T6。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  guardrail: {
    listPolicies: vi.fn(), createPolicy: vi.fn(), updatePolicy: vi.fn(),
    deletePolicy: vi.fn(), evaluate: vi.fn(), listHits: vi.fn(),
  },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useGuardrailStore } from '../guardrail'

describe('M7 Guardrail Store：状态机 + CRUD + 评估', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.guardrail.listPolicies.mockResolvedValue({
      code: 0, data: [{ policy_id: 'gp-1', name: 'p', action_pattern: '*', risk_level: 'low', require_confirm: false, rollback_plan: '', enabled: true, whitelist: [] }], message: 'ok',
    })
    api.guardrail.createPolicy.mockImplementation((p) => Promise.resolve({ code: 0, data: { ...p, policy_id: 'gp-new' }, message: 'ok' }))
    api.guardrail.updatePolicy.mockImplementation((p) => Promise.resolve({ code: 0, data: { ...p }, message: 'ok' }))
    api.guardrail.deletePolicy.mockResolvedValue({ code: 0, data: null, message: 'ok' })
    api.guardrail.evaluate.mockImplementation(() => Promise.resolve({
      code: 0, data: { policy_id: 'gp-1', whitelist_hit: false, requires_confirm: false, requires_rollback_plan: false, passed: true }, message: 'ok',
    }))
    api.guardrail.listHits.mockResolvedValue({ code: 0, data: [{ policy_id: 'gp-1', passed: true }], message: 'ok' })
  })

  it('fetchPolicies 设置 loading 并写入 policies', async () => {
    const store = useGuardrailStore()
    const p = store.fetchPolicies()
    expect(store.loading).toBe(true)
    await p
    expect(store.loading).toBe(false)
    expect(store.policies.length).toBe(1)
  })

  it('createPolicy 写入本地数组并重置 submitting', async () => {
    const store = useGuardrailStore()
    await store.fetchPolicies()
    await store.createPolicy({ name: 'x', action_pattern: 'x:*', risk_level: 'low', require_confirm: false, rollback_plan: '', enabled: true, whitelist: [] })
    expect(store.submitting).toBe(false)
    expect(store.policies.some((p) => p.policy_id === 'gp-new')).toBe(true)
    expect(api.guardrail.createPolicy).toHaveBeenCalled()
  })

  it('updatePolicy 覆盖本地条目', async () => {
    const store = useGuardrailStore()
    await store.fetchPolicies()
    await store.updatePolicy({ policy_id: 'gp-1', name: 'renamed', action_pattern: '*', risk_level: 'low', require_confirm: false, rollback_plan: '', enabled: true, whitelist: [] })
    expect(store.policies[0].name).toBe('renamed')
  })

  it('deletePolicy 从本地移除', async () => {
    const store = useGuardrailStore()
    await store.fetchPolicies()
    await store.deletePolicy('gp-1')
    expect(store.policies.some((p) => p.policy_id === 'gp-1')).toBe(false)
  })

  it('evaluate 设置 lastResult 并刷新命中记录', async () => {
    const store = useGuardrailStore()
    const r = await store.evaluate('host:isolate:X')
    expect(r.passed).toBe(true)
    expect(store.lastResult).toEqual(r)
    expect(api.guardrail.evaluate).toHaveBeenCalledWith('host:isolate:X', undefined)
    expect(api.guardrail.listHits).toHaveBeenCalled() // 重新拉取命中，保证 M1 拦截数实时
  })

  it('enabledCount / blockedCount 派生正确', async () => {
    api.guardrail.listPolicies.mockResolvedValue({
      code: 0, data: [
        { policy_id: 'g1', enabled: true }, { policy_id: 'g2', enabled: false },
      ], message: 'ok',
    })
    api.guardrail.listHits.mockResolvedValue({
      code: 0, data: [{ policy_id: 'g1', passed: true }, { policy_id: 'g2', passed: false }], message: 'ok',
    })
    const store = useGuardrailStore()
    await store.fetchPolicies()
    await store.fetchHits()
    expect(store.enabledCount).toBe(1)
    expect(store.blockedCount).toBe(1)
  })

  it('fetchHits 失败时被 catch 且不抛错', async () => {
    api.guardrail.listHits.mockRejectedValue(new Error('hits down'))
    const store = useGuardrailStore()
    await expect(store.fetchHits()).resolves.toBeUndefined()
  })
})
