/**
 * M4 工具与 MCP Store 单元测试（加载 + 派生 + 异常兜底）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  tools: { listTools: vi.fn(), listMcpServers: vi.fn() },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useToolsStore } from '../tools'

describe('M4 Tools Store：加载 + 派生', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.tools.listTools.mockResolvedValue({
      code: 0, data: [
        { tool_id: 't1', category: '处置', status: 'available' },
        { tool_id: 't2', category: '处置', status: 'degraded' },
        { tool_id: 't3', category: '情报', status: 'available' },
      ], message: 'ok',
    })
    api.tools.listMcpServers.mockResolvedValue({
      code: 0, data: [
        { server_id: 'm1', status: 'online' }, { server_id: 'm2', status: 'offline' },
      ], message: 'ok',
    })
  })

  it('fetchTools 写入工具并置 loading 完成', async () => {
    const store = useToolsStore()
    const p = store.fetchTools()
    expect(store.loading).toBe(true)
    await p
    expect(store.loading).toBe(false)
    expect(store.tools.length).toBe(3)
  })

  it('toolCount / onlineCount / toolsByCategory 派生正确', async () => {
    const store = useToolsStore()
    await store.fetchTools()
    await store.fetchMcpServers()
    expect(store.toolCount).toBe(3)
    expect(store.onlineCount).toBe(1)
    const byCat = store.toolsByCategory
    const names = byCat.map(([k]) => k)
    expect(names).toContain('处置')
    expect(names).toContain('情报')
  })

  it('fetchMcpServers 失败时被 catch 且不抛错', async () => {
    api.tools.listMcpServers.mockRejectedValue(new Error('mcp down'))
    const store = useToolsStore()
    await expect(store.fetchMcpServers()).resolves.toBeUndefined()
  })

  it('refreshAll 并行加载工具与 MCP', async () => {
    const store = useToolsStore()
    await store.refreshAll()
    expect(api.tools.listTools).toHaveBeenCalled()
    expect(api.tools.listMcpServers).toHaveBeenCalled()
    expect(store.tools.length).toBe(3)
    expect(store.mcpServers.length).toBe(2)
  })
})
