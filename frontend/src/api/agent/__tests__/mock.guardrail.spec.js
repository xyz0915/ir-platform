/**
 * M7 护栏 Mock 适配器单元测试（直接驱动真实 mock 模块，验证 CRUD 闭环与
 * evaluate 四类结果边界：whitelist_hit / requires_confirm / requires_rollback_plan / passed）。
 *
 * 设计依据：01-api-spec.md §7.3 / §11.2。
 */
import { describe, it, expect, vi } from 'vitest'
import * as guardrailMock from '../mock/guardrail'

// 仅将网络延迟置为瞬时，保留 ok/clone/nowISO/escapeRegExp 真实实现
vi.mock('../mock/util', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, delay: () => Promise.resolve() }
})

const REQUIRED_POLICY_FIELDS = [
  'policy_id', 'name', 'action_pattern', 'risk_level',
  'require_confirm', 'rollback_plan', 'enabled', 'whitelist',
]

describe('M7 护栏 Mock：字段完整 + CRUD 闭环', () => {
  it('listPolicies 返回策略且核心字段完整', async () => {
    const res = await guardrailMock.listPolicies()
    expect(res).toMatchObject({ code: 0, message: 'ok' })
    expect(Array.isArray(res.data)).toBe(true)
    expect(res.data.length).toBeGreaterThan(0)
    const p = res.data[0]
    REQUIRED_POLICY_FIELDS.forEach((k) => expect(p).toHaveProperty(k))
  })

  it('createPolicy 会话内即时生效（CRUD 闭环）', async () => {
    const before = (await guardrailMock.listPolicies()).data.length
    const created = await guardrailMock.createPolicy({
      name: '临时策略', action_pattern: 'tmp:*', risk_level: 'low',
      require_confirm: false, rollback_plan: '', enabled: true, whitelist: [],
    })
    expect(created.code).toBe(0)
    expect(created.data.policy_id).toBeTruthy()
    const after = (await guardrailMock.listPolicies()).data
    expect(after.length).toBe(before + 1)
    await guardrailMock.deletePolicy(created.data.policy_id) // 清理
  })

  it('updatePolicy 修改字段并保留 policy_id', async () => {
    const created = (await guardrailMock.createPolicy({
      name: 'u', action_pattern: 'u:*', risk_level: 'low',
      require_confirm: false, rollback_plan: '', enabled: true, whitelist: [],
    })).data
    const upd = await guardrailMock.updatePolicy({ ...created, name: 'updated', enabled: false })
    expect(upd.data.name).toBe('updated')
    expect(upd.data.enabled).toBe(false)
    expect(upd.data.policy_id).toBe(created.policy_id)
    await guardrailMock.deletePolicy(created.policy_id) // 清理
  })

  it('deletePolicy 移除策略', async () => {
    const created = (await guardrailMock.createPolicy({
      name: 'd', action_pattern: 'd:*', risk_level: 'low',
      require_confirm: false, rollback_plan: '', enabled: true, whitelist: [],
    })).data
    const before = (await guardrailMock.listPolicies()).data.length
    await guardrailMock.deletePolicy(created.policy_id)
    const after = (await guardrailMock.listPolicies()).data.length
    expect(after).toBe(before - 1)
  })
})

describe('M7 护栏 Mock：evaluate 四类结果边界', () => {
  it('白名单命中 → passed=true, whitelist_hit=true, requires_*=true', async () => {
    const r = await guardrailMock.evaluate('host:isolate:WIN-EXP-01')
    expect(r.code).toBe(0)
    const d = r.data
    expect(d.policy_id).toBe('gp-host-isolate')
    expect(d.whitelist_hit).toBe(true)
    expect(d.requires_confirm).toBe(true)
    expect(d.requires_rollback_plan).toBe(true)
    expect(d.passed).toBe(true)
  })

  it('命中策略但未白名单命中（有回滚预案）→ 仍通过', async () => {
    const r = await guardrailMock.evaluate('host:isolate:OTHER-HOST')
    const d = r.data
    expect(d.policy_id).toBe('gp-host-isolate')
    expect(d.whitelist_hit).toBe(false)
    expect(d.requires_rollback_plan).toBe(true)
    expect(d.passed).toBe(true)
  })

  it('高危 + 无白名单 + 无回滚预案 → passed=false（护栏拦截）', async () => {
    const created = await guardrailMock.createPolicy({
      name: '拦截策略', action_pattern: 'blocktest:*', risk_level: 'critical',
      require_confirm: true, rollback_plan: '', enabled: true, whitelist: [],
    })
    try {
      const r = await guardrailMock.evaluate('blocktest:evil')
      const d = r.data
      expect(d.policy_id).toBe(created.data.policy_id)
      expect(d.whitelist_hit).toBe(false)
      expect(d.requires_confirm).toBe(true)
      expect(d.requires_rollback_plan).toBe(false)
      expect(d.passed).toBe(false) // 护栏拦截
    } finally {
      await guardrailMock.deletePolicy(created.data.policy_id)
    }
  })

  it('无策略命中 → 放行（passed=true, policy_id 空）', async () => {
    const r = await guardrailMock.evaluate('nothing:matched')
    const d = r.data
    expect(d.policy_id).toBe('')
    expect(d.passed).toBe(true)
    expect(d.whitelist_hit).toBe(false)
    expect(d.requires_confirm).toBe(false)
  })
})

describe('M7 护栏 Mock：命中记录与拦截计数', () => {
  it('listHits 返回记录且含 passed 字段', async () => {
    const res = await guardrailMock.listHits()
    expect(res.code).toBe(0)
    expect(Array.isArray(res.data)).toBe(true)
    res.data.forEach((h) => {
      expect(h).toHaveProperty('policy_id')
      expect(h).toHaveProperty('passed')
    })
  })

  it('evaluate 拦截动作后 listHits 增加一条 passed=false', async () => {
    const created = await guardrailMock.createPolicy({
      name: 'h', action_pattern: 'hblock:*', risk_level: 'critical',
      require_confirm: true, rollback_plan: '', enabled: true, whitelist: [],
    })
    try {
      const before = (await guardrailMock.listHits()).data.filter((h) => !h.passed).length
      await guardrailMock.evaluate('hblock:x')
      const after = (await guardrailMock.listHits()).data.filter((h) => !h.passed).length
      expect(after).toBe(before + 1)
    } finally {
      await guardrailMock.deletePolicy(created.data.policy_id)
    }
  })
})
