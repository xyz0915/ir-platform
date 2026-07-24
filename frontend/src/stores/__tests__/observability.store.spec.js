/**
 * M8 可观测性 Store 单元测试（加载某次 run 的 trace/log + 异常兜底 + 空 runId）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  observability: { getRun: vi.fn() },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useObservabilityStore } from '../observability'

describe('M8 Observability Store：加载 + 边界', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.observability.getRun.mockResolvedValue({
      code: 0,
      data: { run_id: 'run-002', agent_name: '处置响应 Agent', trace: [{ span_id: 'sp-1' }], logs: [{ level: 'info', message: 'x' }], resume_point: 'sp-1' },
      message: 'ok',
    })
  })

  it('fetchRun(runId) 写入 run 并置 loading 完成', async () => {
    const store = useObservabilityStore()
    const p = store.fetchRun('run-002')
    expect(store.loading).toBe(true)
    await p
    expect(store.loading).toBe(false)
    expect(store.run.run_id).toBe('run-002')
    expect(store.run.trace.length).toBe(1)
    expect(store.run.resume_point).toBe('sp-1')
  })

  it('空 runId 时提前返回且不发起请求', async () => {
    const store = useObservabilityStore()
    await store.fetchRun('')
    expect(api.observability.getRun).not.toHaveBeenCalled()
  })

  it('fetchRun 失败被 catch 且 run 置 null', async () => {
    api.observability.getRun.mockRejectedValue(new Error('obs down'))
    const store = useObservabilityStore()
    await store.fetchRun('run-x')
    expect(store.run).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('clear 重置 run', async () => {
    const store = useObservabilityStore()
    await store.fetchRun('run-002')
    store.clear()
    expect(store.run).toBeNull()
  })
})
