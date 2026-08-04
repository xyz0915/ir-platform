/**
 * agentApi 统一适配层契约测试（真实/Mock 路由切换 + 信封同构 + 异常透传）。
 *
 * 策略：
 *  - 仅 mock 三个真实接口模块（agentManagement/agentOrchestration/agents），
 *    其余 Mock 适配器（guardrail/tools/...）保持真实以验证经适配层返回的同构信封。
 *  - 验证 USE_MOCK 一键切换下，store 调用的 20 个方法均能正确路由并产出 {code,data,message}。
 *
 * 设计依据：01-arch-design.md §4 / 01-api-spec.md §0 / §11。
 */
import { describe, it, expect, vi } from 'vitest'

vi.mock('../mock-config', () => ({
  USE_MOCK: {
    guardrail: true, tools: true, memory: true,
    // 拆键：settings→settings+settingsDeployment（07 §5.5）
    settings: true, settingsDeployment: true,
    // 拆键：dashboardTrend→dashboardTrend+dashboardGuardrailBlocks
    dashboardTrend: true, dashboardGuardrailBlocks: true,
    observability: true, pipeline: false,
    hitl: false, agents: false, runs: false,
  },
}))

vi.mock('@/api/agentManagement', () => ({
  listAgents: vi.fn(() => Promise.resolve({ code: 0, data: [{ name: 'triage' }], message: 'ok' })),
  createAgent: vi.fn(() => Promise.resolve({ code: 0, data: { agent_id: 'a1' }, message: 'ok' })),
  updateAgent: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  deleteAgent: vi.fn(() => Promise.resolve({ code: 0, data: null, message: 'ok' })),
  validatePipeline: vi.fn(() => Promise.resolve({ code: 0, data: { valid: true, warnings: [] }, message: 'ok' })),
  runPipeline: vi.fn(() => Promise.resolve({ code: 0, data: { run_id: 'r-1', status: 'running' }, message: 'ok' })),
  getRunStatus: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  cancelRun: vi.fn(() => Promise.resolve({ code: 0, data: null, message: 'ok' })),
  resumeRun: vi.fn(() => Promise.resolve({ code: 0, data: null, message: 'ok' })),
  getPipelineSSEUrl: vi.fn(() => '/x'),
  listPresets: vi.fn(() => Promise.resolve({ code: 0, data: [], message: 'ok' })),
}))
vi.mock('@/api/agentOrchestration', () => ({
  createAgentRun: vi.fn(() => Promise.resolve({ code: 0, data: { run_id: 'r-0' }, message: 'ok' })),
  listAgentRuns: vi.fn(() => Promise.resolve({ code: 0, data: { items: [], total: 0 }, message: 'ok' })),
  getAgentRun: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  approveAgentRun: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  rejectAgentRun: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  listPendingApprovals: vi.fn(() => Promise.resolve({ code: 0, data: { items: [] }, message: 'ok' })),
  getSSEUrl: vi.fn(() => '/y'),
}))
vi.mock('@/api/agents', () => ({
  getAgents: vi.fn(() => Promise.resolve({ code: 0, data: [], message: 'ok' })),
  getAgentStats: vi.fn(() => Promise.resolve({ code: 0, data: { running: 0, success_rate: 100 }, message: 'ok' })),
}))
// 加速 Mock 适配器内部 delay
vi.mock('../mock/util', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, delay: () => Promise.resolve() }
})

import agentApi, { useGuardrail } from '../index'
import * as am from '@/api/agentManagement'
import * as ao from '@/api/agentOrchestration'
import * as ag from '@/api/agents'

describe('agentApi 适配层：真实/Mock 路由切换', () => {
  it('M2 agents → 真实接口（USE_MOCK.agents=false）', async () => {
    const res = await agentApi.listAgents()
    expect(am.listAgents).toHaveBeenCalled()
    expect(res).toMatchObject({ code: 0, data: [{ name: 'triage' }], message: 'ok' })
  })

  it('M2 createAgent/updateAgent/deleteAgent 转发真实', async () => {
    await agentApi.createAgent({ agent_id: 'a' })
    expect(am.createAgent).toHaveBeenCalledWith({ agent_id: 'a' })
    await agentApi.updateAgent('a', { status: 'disabled' })
    expect(am.updateAgent).toHaveBeenCalledWith('a', { status: 'disabled' })
    await agentApi.deleteAgent('a')
    expect(am.deleteAgent).toHaveBeenCalledWith('a')
  })

  it('M3 pipeline.run → 真实 runPipeline 且返回 run_id', async () => {
    const res = await agentApi.pipeline.run('E1', ['triage'], true)
    expect(am.runPipeline).toHaveBeenCalledWith('E1', ['triage'], true)
    expect(res.data.run_id).toBe('r-1')
  })

  it('M3 pipeline.getSample → Mock 种子（pipeline:false 但 getSample 走 Mock）', async () => {
    const res = await agentApi.pipeline.getSample()
    expect(res.code).toBe(0)
    expect(Array.isArray(res.data.nodes)).toBe(true)
  })

  it('M1 runs.listAgentRuns + stats.getAgentStats → 真实', async () => {
    await agentApi.runs.listAgentRuns({ page_size: 50 })
    expect(ao.listAgentRuns).toHaveBeenCalledWith({ page_size: 50 })
    await agentApi.stats.getAgentStats()
    expect(ag.getAgentStats).toHaveBeenCalled()
  })

  it('M6 hitl.approve/reject → 真实且参数透传', async () => {
    await agentApi.hitl.approve('r', { approval_id: 1 })
    expect(ao.approveAgentRun).toHaveBeenCalledWith('r', { approval_id: 1 })
    await agentApi.hitl.reject('r', { approval_id: 1, reason: 'x' })
    expect(ao.rejectAgentRun).toHaveBeenCalledWith('r', { approval_id: 1, reason: 'x' })
  })

  it('M7 guardrail.* → Mock（信封同构 {code,data,message}）', async () => {
    const res = await agentApi.guardrail.listPolicies()
    expect(res).toHaveProperty('code')
    expect(res).toHaveProperty('data')
    expect(res).toHaveProperty('message')
    expect(res.code).toBe(0)
  })

  it('M4 tools.* → Mock（字段完整）', async () => {
    const res = await agentApi.tools.listTools()
    expect(res.code).toBe(0)
    expect(Array.isArray(res.data)).toBe(true)
    expect(res.data.length).toBeGreaterThan(0)
  })

  it('M5 memory.* → Mock', async () => {
    const res = await agentApi.memory.listKnowledgeBases()
    expect(res.code).toBe(0)
    expect(res.data.length).toBeGreaterThan(0)
  })

  it('M5 memory P2 长期记忆 → Mock（信封同构，list/search/create/delete 均可路由）', async () => {
    const list = await agentApi.memory.listMemories({ page: 1, page_size: 10 })
    expect(list.code).toBe(0)
    expect(list.data).toMatchObject({ items: [], total: 0 })

    const search = await agentApi.memory.searchMemories('powershell', { memory_type: 'conclusion' })
    expect(search.code).toBe(0)
    expect(search.data).toMatchObject({ items: [], total: 0 })

    const created = await agentApi.memory.createMemory({ content: 'x', memory_type: 'summary' })
    expect(created.code).toBe(0)
    expect(created.data.content).toBe('x')
    expect(created.data.id).toBeTruthy()

    const del = await agentApi.memory.deleteMemory(1)
    expect(del.code).toBe(0)
    expect(del.data.deleted).toBe(true)
  })

  it('M9 settings.* → Mock', async () => {
    const profiles = await agentApi.settings.listModelProfiles()
    const cfg = await agentApi.settings.getDeploymentConfig()
    expect(profiles.code).toBe(0)
    expect(cfg.code).toBe(0)
  })

  it('M1 dashboard.getTrend/getGuardrailBlocks → Mock 且 guardrailBlocks 为数字', async () => {
    const t = await agentApi.dashboard.getTrend()
    const b = await agentApi.dashboard.getGuardrailBlocks()
    expect(t.code).toBe(0)
    expect(b.code).toBe(0)
    expect(typeof b.data).toBe('number')
  })

  it('M8 observability.getRun → Mock 且命中返回 run_id', async () => {
    const res = await agentApi.observability.getRun('run-002')
    expect(res.code).toBe(0)
    expect(res.data.run_id).toBe('run-002')
  })

  it('useGuardrail() 热插拔入口返回 guardrail 命名空间', () => {
    const g = useGuardrail()
    expect(g).toBe(agentApi.guardrail)
    expect(typeof g.evaluate).toBe('function')
  })
})

describe('agentApi 适配层：异常与信封透传（store 负责 catch）', () => {
  it('真实接口网络错误 → 透传 reject', async () => {
    am.listAgents.mockImplementationOnce(() => Promise.reject(new Error('network')))
    await expect(agentApi.listAgents()).rejects.toThrow('network')
  })

  it('非 0 code 信封 → 原样返回（不抛错，由 store 判读）', async () => {
    am.listAgents.mockImplementationOnce(() =>
      Promise.resolve({ code: 409, data: null, message: 'conflict' }))
    const res = await agentApi.listAgents()
    expect(res.code).toBe(409)
    expect(res.message).toBe('conflict')
  })
})
