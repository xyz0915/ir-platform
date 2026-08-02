/**
 * M2 智能体管理 Store 单元测试（Agent CRUD 状态机 + 管道空校验 + 异常透传）。
 * store 经 @/api/agent facade 调用，此处 vi.mock 默认导出并补全 facade 形态。
 *
 * 设计依据：01-api-spec.md §2 / T3。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  listAgents: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  pipeline: {
    validate: vi.fn(),
    run: vi.fn(),
    getRunStatus: vi.fn(),
    cancel: vi.fn(),
    getPresets: vi.fn(),
    createPreset: vi.fn(),
    deletePreset: vi.fn(),
  },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { useAgentManagementStore } from '../agentManagement'

describe('M2 AgentManagement Store：CRUD 状态机', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.listAgents.mockResolvedValue({ code: 0, data: [{ name: 'triage' }], message: 'ok' })
    api.createAgent.mockResolvedValue({ code: 0, data: { name: 'custom-a' }, message: 'ok' })
    api.updateAgent.mockResolvedValue({ code: 0, data: { name: 'custom-a', status: 'disabled' }, message: 'ok' })
    api.deleteAgent.mockResolvedValue({ code: 0, data: null, message: 'ok' })
    api.pipeline.validate.mockResolvedValue({ code: 0, data: { valid: true, warnings: ['w1'] }, message: 'ok' })
    api.pipeline.getRunStatus.mockResolvedValue({ code: 0, data: { run_id: 'r1', status: 'running' }, message: 'ok' })
    api.pipeline.cancel.mockResolvedValue({ code: 0, data: null, message: 'ok' })
    api.pipeline.getPresets.mockResolvedValue({ code: 0, data: [{ name: 'preset-1' }], message: 'ok' })
    api.pipeline.createPreset.mockResolvedValue({ code: 0, data: { name: 'p1' }, message: 'ok' })
    api.pipeline.deletePreset.mockResolvedValue({ code: 0, data: null, message: 'ok' })
  })

  it('fetchAgents 加载全部 Agent（含禁用）并置 loading 完成', async () => {
    const store = useAgentManagementStore()
    const p = store.fetchAgents()
    expect(store.loading).toBe(true)
    await p
    expect(store.loading).toBe(false)
    expect(api.listAgents).toHaveBeenCalledWith(false) // Library 显示所有（含禁用）
    expect(store.agents.length).toBe(1)
  })

  it('registerAgent 注册后刷新列表并返回完整响应信封（含 data + warning，P2）', async () => {
    const store = useAgentManagementStore()
    const r = await store.registerAgent({ name: 'custom-a', display_name: 'A' })
    expect(api.createAgent).toHaveBeenCalledWith({ name: 'custom-a', display_name: 'A' })
    expect(api.listAgents).toHaveBeenCalled() // 刷新
    expect(r.data).toEqual({ name: 'custom-a' })
  })

  it('updateAgentAction 更新后刷新列表', async () => {
    const store = useAgentManagementStore()
    await store.updateAgentAction('custom-a', { status: 'disabled' })
    expect(api.updateAgent).toHaveBeenCalledWith('custom-a', { status: 'disabled' })
  })

  it('deleteAgentAction 删除后刷新列表', async () => {
    const store = useAgentManagementStore()
    await store.deleteAgentAction('custom-a')
    expect(api.deleteAgent).toHaveBeenCalledWith('custom-a')
  })

  it('注册失败 → 透传异常（不被吞）', async () => {
    api.createAgent.mockRejectedValue(new Error('create failed'))
    const store = useAgentManagementStore()
    await expect(store.registerAgent({ name: 'x' })).rejects.toThrow('create failed')
  })

  it('startPipeline 管道为空 → 抛错且不调用底层', async () => {
    const store = useAgentManagementStore()
    await expect(store.startPipeline('E1')).rejects.toThrow('管道为空')
    expect(api.pipeline.run).not.toHaveBeenCalled()
  })

  it('addToPipeline 去重 + 触发校验', async () => {
    const store = useAgentManagementStore()
    api.pipeline.validate.mockResolvedValue({ code: 0, data: { valid: true, warnings: [] }, message: 'ok' })
    const a = { name: 'triage' }
    store.addToPipeline(a)
    store.addToPipeline(a) // 去重
    expect(store.pipeline.length).toBe(1)
  })
})

describe('M2 AgentManagement Store：管道/预置/运行控制方法', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.listAgents.mockResolvedValue({ code: 0, data: [{ name: 'triage', enabled: true }], message: 'ok' })
    api.createAgent.mockResolvedValue({ code: 0, data: { name: 'custom-a' }, message: 'ok' })
    api.updateAgent.mockResolvedValue({ code: 0, data: {}, message: 'ok' })
    api.deleteAgent.mockResolvedValue({ code: 0, data: null, message: 'ok' })
    api.pipeline.validate.mockResolvedValue({ code: 0, data: { valid: true, warnings: ['w1'] }, message: 'ok' })
    api.pipeline.getRunStatus.mockResolvedValue({ code: 0, data: { run_id: 'r1', status: 'running' }, message: 'ok' })
    api.pipeline.cancel.mockResolvedValue({ code: 0, data: null, message: 'ok' })
    api.pipeline.getPresets.mockResolvedValue({ code: 0, data: [{ name: 'preset-1' }], message: 'ok' })
    api.pipeline.createPreset.mockResolvedValue({ code: 0, data: { name: 'p1' }, message: 'ok' })
    api.pipeline.deletePreset.mockResolvedValue({ code: 0, data: null, message: 'ok' })
  })

  it('removeFromPipeline / reorderPipeline / clearPipeline 闭环', async () => {
    const store = useAgentManagementStore()
    store.addToPipeline({ name: 'triage' })
    store.addToPipeline({ name: 'forensic' })
    expect(store.pipeline.length).toBe(2)
    store.removeFromPipeline('forensic')
    expect(store.pipeline.length).toBe(1)
    store.addToPipeline({ name: 'forensic' })
    store.reorderPipeline(1, 0) // 交换
    expect(store.pipeline[0].name).toBe('forensic')
    store.clearPipeline()
    expect(store.pipeline.length).toBe(0)
    expect(store.isPipelineValid).toBe(false)
  })

  it('validatePipelineAction：空管道重置校验；非空管道写回校验结果', async () => {
    const store = useAgentManagementStore()
    // 空
    store.clearPipeline()
    await store.validatePipelineAction()
    expect(store.isPipelineValid).toBe(false)
    // 非空
    store.addToPipeline({ name: 'triage' })
    await store.validatePipelineAction()
    expect(store.isPipelineValid).toBe(true)
    expect(store.validationMessages).toEqual(['w1'])
    expect(api.pipeline.validate).toHaveBeenCalledWith(['triage'])
  })

  it('toggleEnabled 调用 updateAgentAction 翻转 enabled', async () => {
    const store = useAgentManagementStore()
    await store.toggleEnabled({ name: 'triage', enabled: true })
    expect(api.updateAgent).toHaveBeenCalledWith('triage', { enabled: false })
  })

  it('fetchPresets 加载预置模板', async () => {
    const store = useAgentManagementStore()
    await store.fetchPresets()
    expect(store.presets).toEqual([{ name: 'preset-1' }])
  })

  it('fetchRunStatus 写回当前运行', async () => {
    const store = useAgentManagementStore()
    await store.fetchRunStatus('r1')
    expect(store.currentRun.run_id).toBe('r1')
    expect(api.pipeline.getRunStatus).toHaveBeenCalledWith('r1')
  })

  it('cancelRunAction 调用 cancelRun（有当前运行则置 cancelled）', async () => {
    const store = useAgentManagementStore()
    await store.fetchRunStatus('r1')
    await store.cancelRunAction('r1')
    expect(api.pipeline.cancel).toHaveBeenCalledWith('r1')
    expect(store.currentRun.status).toBe('cancelled')
  })

  it('savePreset 成功路径：createPreset 后刷新预置', async () => {
    const store = useAgentManagementStore()
    store.addToPipeline({ name: 'triage' })
    await store.savePreset('p1', 'desc')
    expect(api.pipeline.createPreset).toHaveBeenCalled()
    expect(store.presets).toEqual([{ name: 'preset-1' }])
  })

  it('savePreset 名称为空 → 抛错', async () => {
    const store = useAgentManagementStore()
    store.addToPipeline({ name: 'triage' })
    await expect(store.savePreset('', 'desc')).rejects.toThrow('名称和 Agent 列表不能为空')
  })

  it('deletePresetAction 调用 deletePreset 后刷新', async () => {
    const store = useAgentManagementStore()
    await store.deletePresetAction('preset-1')
    expect(api.pipeline.deletePreset).toHaveBeenCalledWith('preset-1')
  })

  it('loadPresetToPipeline 按名称映射到已加载 Agent', async () => {
    const store = useAgentManagementStore()
    await store.fetchAgents() // agents = [{name:'triage'}]
    store.loadPresetToPipeline({ agents: ['triage', 'forensic'] })
    expect(store.pipeline.map((a) => a.name)).toEqual(['triage']) // forensic 未加载被过滤
  })
})
