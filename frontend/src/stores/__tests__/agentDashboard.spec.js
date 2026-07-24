/**
 * M1 Dashboard Store 单元测试（前端组合聚合 + 状态机 + 边界）。
 * vi.mock 掉底层 agentApi，隔离真实/Mock 数据源。
 *
 * 设计依据：01-api-spec.md §1 / Q5 / T7。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  runs: { listAgentRuns: vi.fn() },
  stats: { getAgentStats: vi.fn() },
  dashboard: { getTrend: vi.fn(), getGuardrailBlocks: vi.fn() },
  hitl: { listPendingApprovals: vi.fn() },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useAgentDashboardStore } from '../agentDashboard'

describe('M1 Dashboard Store：并行聚合 + DashboardStats 计算', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetchStats 并行聚合 5 源并计算 DashboardStats', async () => {
    api.runs.listAgentRuns.mockResolvedValue({
      code: 0, data: { items: [{ status: 'running' }, { status: 'completed' }, { status: 'completed' }], total: 3 }, message: 'ok',
    })
    api.stats.getAgentStats.mockResolvedValue({ code: 0, data: { running: 5, success_rate: 92 }, message: 'ok' })
    api.dashboard.getTrend.mockResolvedValue({ code: 0, data: [{ ts: 't', success_rate: 90 }], message: 'ok' })
    api.dashboard.getGuardrailBlocks.mockResolvedValue({ code: 0, data: 2, message: 'ok' })
    api.hitl.listPendingApprovals.mockResolvedValue({ code: 0, data: { items: [{ approval_id: 1 }, { approval_id: 2 }] }, message: 'ok' })

    const store = useAgentDashboardStore()
    await store.fetchStats()

    expect(api.runs.listAgentRuns).toHaveBeenCalledWith({ page_size: 50 })
    expect(store.loading).toBe(false)
    expect(store.runs.length).toBe(3)
    expect(store.runningAgents).toBe(5) // 来自 statsRaw.running
    expect(store.successRate).toBe(92)
    expect(store.guardrailBlocks).toBe(2)
    expect(store.pendingHitl).toBe(2)
    expect(store.stats).toMatchObject({
      running_agents: 5, success_rate: 92, pending_hitl: 2, guardrail_blocks: 2,
    })
    expect(store.stats.trend.length).toBe(1)
  })

  it('Mock 源失败（.catch 兜底）不影响整体渲染', async () => {
    api.runs.listAgentRuns.mockResolvedValue({ code: 0, data: { items: [], total: 0 }, message: 'ok' })
    api.stats.getAgentStats.mockResolvedValue({ code: 0, data: { running: 0, success_rate: 100 }, message: 'ok' })
    api.dashboard.getTrend.mockRejectedValue(new Error('trend down'))
    api.dashboard.getGuardrailBlocks.mockRejectedValue(new Error('blocks down'))
    api.hitl.listPendingApprovals.mockRejectedValue(new Error('hitl down'))

    const store = useAgentDashboardStore()
    await expect(store.fetchStats()).resolves.toBeUndefined()
    expect(store.loading).toBe(false)
    expect(store.trend).toEqual([])
    expect(store.guardrailBlocks).toBe(0)
    expect(store.pendingHitl).toBe(0)
  })

  it('空运行列表时成功率兜底为 0', async () => {
    api.runs.listAgentRuns.mockResolvedValue({ code: 0, data: { items: [], total: 0 }, message: 'ok' })
    api.stats.getAgentStats.mockResolvedValue({ code: 0, data: null, message: 'ok' })
    api.dashboard.getTrend.mockResolvedValue({ code: 0, data: [], message: 'ok' })
    api.dashboard.getGuardrailBlocks.mockResolvedValue({ code: 0, data: 0, message: 'ok' })
    api.hitl.listPendingApprovals.mockResolvedValue({ code: 0, data: { items: [] }, message: 'ok' })

    const store = useAgentDashboardStore()
    await store.fetchStats()
    expect(store.successRate).toBe(0)
    expect(store.recentRuns.length).toBe(0)
  })

  it('真实 runs 源失败时 fetchStats 抛出（不被静默，由调用方处理）', async () => {
    api.runs.listAgentRuns.mockRejectedValue(new Error('db down'))
    const store = useAgentDashboardStore()
    await expect(store.fetchStats()).rejects.toThrow('db down')
  })
})
