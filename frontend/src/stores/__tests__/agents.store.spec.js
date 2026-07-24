/**
 * M6 人工审核台 Store（复用 agents.js）单元测试：运行列表/详情/待审队列/批准/拒绝
 * + 异常透传（批准不存在的 task）。
 * store 经 @/api/agent facade 调用，此处 vi.mock 默认导出并补全 facade 嵌套形态。
 *
 * 设计依据：01-api-spec.md §6 / T4。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  runs: {
    listAgentRuns: vi.fn(),
    getAgentRun: vi.fn(),
    createAgentRun: vi.fn(),
  },
  hitl: {
    approve: vi.fn(),
    reject: vi.fn(),
    listPendingApprovals: vi.fn(),
  },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useAgentOrchestrationStore } from '../agents'

describe('M6 HITL Store：队列 + 批准/拒绝 + 异常', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.runs.listAgentRuns.mockResolvedValue({ code: 0, data: { items: [{ run_id: 'r1' }], total: 1 }, message: 'ok' })
    api.runs.getAgentRun.mockResolvedValue({ code: 0, data: { run_id: 'r1' }, message: 'ok' })
    api.hitl.listPendingApprovals.mockResolvedValue({ code: 0, data: { items: [{ approval_id: 7, run_id: 'r1' }], total: 1 }, message: 'ok' })
    api.hitl.approve.mockResolvedValue({ code: 0, data: { approval_id: 7 }, message: 'ok' })
    api.hitl.reject.mockResolvedValue({ code: 0, data: { approval_id: 7 }, message: 'ok' })
  })

  it('fetchRuns 加载运行列表与总数', async () => {
    const store = useAgentOrchestrationStore()
    await store.fetchRuns()
    expect(store.runs.length).toBe(1)
    expect(store.total).toBe(1)
  })

  it('fetchRunDetail 加载运行详情', async () => {
    const store = useAgentOrchestrationStore()
    await store.fetchRunDetail('r1')
    expect(store.currentRun.run_id).toBe('r1')
  })

  it('fetchApprovals 加载待审队列（数组）', async () => {
    const store = useAgentOrchestrationStore()
    await store.fetchApprovals()
    expect(Array.isArray(store.approvals)).toBe(true)
    expect(store.approvals.length).toBe(1)
    expect(store.pendingCount).toBe(1)
  })

  it('startRun 返回 run 数据', async () => {
    api.runs.createAgentRun.mockResolvedValue({ code: 0, data: { run_id: 'r0' }, message: 'ok' })
    const store = useAgentOrchestrationStore()
    const r = await store.startRun({ event_id: 'E1' })
    expect(r.run_id).toBe('r0')
  })

  it('approve 透传 approval_id 并返回数据', async () => {
    const store = useAgentOrchestrationStore()
    const r = await store.approve('r1', 7)
    expect(api.hitl.approve).toHaveBeenCalledWith('r1', { approval_id: 7 })
    expect(r.approval_id).toBe(7)
  })

  it('reject 透传 approval_id 与 reason', async () => {
    const store = useAgentOrchestrationStore()
    const r = await store.reject('r1', 7, '风险过高')
    expect(api.hitl.reject).toHaveBeenCalledWith('r1', { approval_id: 7, reason: '风险过高' })
    expect(r.approval_id).toBe(7)
  })

  it('批准不存在的 task → 后端报错时透传异常（不为空壳）', async () => {
    api.hitl.approve.mockRejectedValue(new Error('approval not found'))
    const store = useAgentOrchestrationStore()
    await expect(store.approve('r1', 999)).rejects.toThrow('approval not found')
  })

  it('拒绝不存在的 task → 透传异常', async () => {
    api.hitl.reject.mockRejectedValue(new Error('approval not found'))
    const store = useAgentOrchestrationStore()
    await expect(store.reject('r1', 999)).rejects.toThrow('approval not found')
  })
})
