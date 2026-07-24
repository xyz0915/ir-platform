/**
 * M9 设置 Store 单元测试（多模型 profile + 部署配置 + 异常兜底）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  settings: { listModelProfiles: vi.fn(), getDeploymentConfig: vi.fn() },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useAgentSettingsStore } from '../agentSettings'

describe('M9 AgentSettings Store：加载 + 派生', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.settings.listModelProfiles.mockResolvedValue({
      code: 0, data: [
        { profile_id: 'mp1', enabled: true }, { profile_id: 'mp2', enabled: false },
      ], message: 'ok',
    })
    api.settings.getDeploymentConfig.mockResolvedValue({
      code: 0, data: { stateless_enabled: true, redis_connected: true }, message: 'ok',
    })
  })

  it('fetchModelProfiles 写入 profile 并置 loading 完成', async () => {
    const store = useAgentSettingsStore()
    const p = store.fetchModelProfiles()
    expect(store.loading).toBe(true)
    await p
    expect(store.loading).toBe(false)
    expect(store.modelProfiles.length).toBe(2)
  })

  it('enabledProfiles 派生正确', async () => {
    const store = useAgentSettingsStore()
    await store.fetchModelProfiles()
    expect(store.enabledProfiles).toBe(1)
  })

  it('fetchDeploymentConfig 失败被 catch 且不抛错', async () => {
    api.settings.getDeploymentConfig.mockRejectedValue(new Error('cfg down'))
    const store = useAgentSettingsStore()
    await expect(store.fetchDeploymentConfig()).resolves.toBeUndefined()
  })

  it('refreshAll 并行加载 profile + config', async () => {
    const store = useAgentSettingsStore()
    await store.refreshAll()
    expect(api.settings.listModelProfiles).toHaveBeenCalled()
    expect(api.settings.getDeploymentConfig).toHaveBeenCalled()
    expect(store.deploymentConfig.stateless_enabled).toBe(true)
  })
})
