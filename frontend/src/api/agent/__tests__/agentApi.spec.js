import { describe, it, expect, vi } from 'vitest'

// ── 控制 USE_MOCK 开关（当前部署态：真实走 agents/pipeline/hitl/runs，Mock 走 guardrail/tools/memory/settings/observability/dashboardTrend） ──
vi.mock('../mock-config', () => ({
  USE_MOCK: {
    guardrail: true,
    tools: true,
    memory: true,
    settings: true,
    dashboardTrend: true,
    observability: true,
    pipeline: false,
    hitl: false,
    agents: false,
    runs: false,
  },
}))

// ── Mock 真实接口层（仅提供 index.js 实际引用的命名导出） ──
vi.mock('@/api/agentManagement', () => ({
  listAgents: vi.fn(() => Promise.resolve({ code: 0, data: [{ name: 'triage' }], message: 'ok' })),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  validatePipeline: vi.fn(),
  runPipeline: vi.fn(),
  getRunStatus: vi.fn(),
  cancelRun: vi.fn(),
  resumeRun: vi.fn(),
  getPipelineSSEUrl: vi.fn(),
  listPresets: vi.fn(),
}))

// ── Mock 护栏适配器（验证 Mock 路由） ──
vi.mock('../mock/guardrail', () => ({
  listPolicies: vi.fn(() =>
    Promise.resolve({ code: 0, data: [{ policy_id: 'gp-1' }], message: 'ok' })
  ),
}))

import * as agentManagementMod from '@/api/agentManagement'
import * as guardrailMockMod from '../mock/guardrail'
import agentApi from '../index'

describe('agentApi 统一适配层路由（USE_MOCK 一键切换）', () => {
  it('M2 agents 走真实接口（USE_MOCK.agents=false）', async () => {
    const res = await agentApi.listAgents()
    expect(agentManagementMod.listAgents).toHaveBeenCalled()
    expect(res.data).toEqual([{ name: 'triage' }])
  })

  it('M7 guardrail 走 Mock（USE_MOCK.guardrail=true）', async () => {
    const res = await agentApi.guardrail.listPolicies()
    expect(guardrailMockMod.listPolicies).toHaveBeenCalled()
    expect(res.code).toBe(0)
    expect(res.data[0].policy_id).toBe('gp-1')
  })

  it('返回与后端同构信封 {code,data,message}', async () => {
    const res = await agentApi.guardrail.listPolicies()
    expect(res).toHaveProperty('code')
    expect(res).toHaveProperty('data')
    expect(res).toHaveProperty('message')
  })
})
