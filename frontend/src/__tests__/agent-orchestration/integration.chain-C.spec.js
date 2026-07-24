/**
 * 集成链路 C（Dashboard 聚合 + 轻量实时）：
 *   listAgentRuns + getAgentStats（真实）+ mock trend + guardrailBlocks + pending HITL
 *   验证轮询/增量刷新不会丢失运行态（store 始终持有最新全量快照）。
 *
 * 设计依据：01-arch-design.md Q5 / 01-api-spec.md §1。
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

import { useAgentDashboardStore } from '@/stores/agentDashboard'

describe('集成链路 C：Dashboard 聚合 + 轮询不丢运行态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.stats.getAgentStats.mockResolvedValue({ code: 0, data: { running: 3, success_rate: 88 }, message: 'ok' })
    api.dashboard.getTrend.mockResolvedValue({ code: 0, data: [{ ts: 't', success_rate: 88 }], message: 'ok' })
    api.dashboard.getGuardrailBlocks.mockResolvedValue({ code: 0, data: 1, message: 'ok' })
    api.hitl.listPendingApprovals.mockResolvedValue({ code: 0, data: { items: [{ approval_id: 1 }] }, message: 'ok' })
  })

  it('首次聚合：recentRuns 来自 runs，趋势来自 mock', async () => {
    api.runs.listAgentRuns.mockResolvedValueOnce({
      code: 0, data: { items: [
        { run_id: 'run-1', status: 'running' },
        { run_id: 'run-2', status: 'completed' },
      ], total: 2 }, message: 'ok',
    })
    const store = useAgentDashboardStore()
    await store.fetchStats()
    expect(store.runs.map((r) => r.run_id)).toEqual(['run-1', 'run-2'])
    expect(store.recentRuns.length).toBe(2)
    expect(store.trend.length).toBe(1)
    expect(store.runningAgents).toBe(3)
    expect(store.successRate).toBe(88)
  })

  it('轮询/增量刷新：最新全量快照包含历史运行，不丢运行态', async () => {
    api.runs.listAgentRuns
      .mockResolvedValueOnce({ code: 0, data: { items: [{ run_id: 'run-1', status: 'running' }], total: 1 }, message: 'ok' })
      .mockResolvedValueOnce({ code: 0, data: { items: [
        { run_id: 'run-1', status: 'completed' },
        { run_id: 'run-2', status: 'running' },
      ], total: 2 }, message: 'ok' })

    const store = useAgentDashboardStore()
    await store.fetchStats()
    expect(store.runs.map((r) => r.run_id)).toEqual(['run-1'])

    // 再次轮询（增量刷新）
    await store.fetchStats()

    const ids = store.runs.map((r) => r.run_id)
    expect(ids).toContain('run-1') // 历史运行态未丢失
    expect(ids).toContain('run-2') // 新增运行进入
    expect(store.loading).toBe(false)
    expect(store.lastUpdated).not.toBeNull()
  })

  it('多源并行：runs/stats/trend/blocks/hitl 均被调用', async () => {
    api.runs.listAgentRuns.mockResolvedValue({ code: 0, data: { items: [], total: 0 }, message: 'ok' })
    const store = useAgentDashboardStore()
    await store.fetchStats()
    expect(api.runs.listAgentRuns).toHaveBeenCalledWith({ page_size: 50 })
    expect(api.stats.getAgentStats).toHaveBeenCalled()
    expect(api.dashboard.getTrend).toHaveBeenCalled()
    expect(api.dashboard.getGuardrailBlocks).toHaveBeenCalled()
    expect(api.hitl.listPendingApprovals).toHaveBeenCalledWith('pending')
  })
})
