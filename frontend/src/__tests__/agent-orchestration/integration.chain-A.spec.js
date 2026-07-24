/**
 * 集成链路 A（跨模块协同）：
 *   创建智能体(M2) → 编排执行(M3 runPipeline 返回 run_id)
 *   → 产生 HITL 任务(M6) → 批准 → 可观测(M8)出现 trace/日志。
 *
 * 三层数据源隔离：
 *   - M2 复用 store 直接依赖 @/api/agentManagement（真实接口层）
 *   - M3 / M8 经 @/api/agent 适配层（facade）
 *   - M6 复用 store 直接依赖 @/api/agentOrchestration（真实接口层）
 *
 * 设计依据：01-arch-design.md §3.1 / 01-api-spec.md §10。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// M3 / M6 / M8 走 facade（完整命名空间，对齐 07 §6 任务列表 T1-T7 后的 agentApi 结构）
const agentApi = vi.hoisted(() => ({
  pipeline: {
    getSample: vi.fn(() => Promise.resolve({
      code: 0,
      data: {
        pipeline_id: 'pipe-1',
        nodes: [
          { node_id: 'n-trigger', type: 'trigger', label: '触发', position: { x: 0, y: 0 } },
          { node_id: 'n-guardrail', type: 'guardrail', label: '护栏', position: { x: 1, y: 0 } },
          { node_id: 'n-remediate', type: 'remediate', label: '处置', position: { x: 2, y: 0 } },
          { node_id: 'n-end', type: 'end', label: '结束', position: { x: 3, y: 0 } },
        ],
        edges: [
          { source: 'n-trigger', target: 'n-guardrail' },
          { source: 'n-guardrail', target: 'n-remediate' },
          { source: 'n-remediate', target: 'n-end' },
        ],
      },
      message: 'ok',
    })),
    run: vi.fn(() => Promise.resolve({ code: 0, data: { run_id: 'run-A1', status: 'running' }, message: 'ok' })),
  },
  observability: {
    getRun: vi.fn(() => Promise.resolve({
      code: 0,
      data: {
        run_id: 'run-A1', agent_name: '处置响应 Agent',
        trace: [{ span_id: 'sp-1', name: 'run', duration_ms: 100 }],
        logs: [{ ts: '2026-07-06T15:55:00.000Z', level: 'info', message: 'run started' }],
        resume_point: 'sp-1',
      },
      message: 'ok',
    })),
  },
  // M2 顶层方法（facade 转发到 @/api/agentManagement）
  createAgent: vi.fn(() => Promise.resolve({ code: 0, data: { agent_id: 'a1' }, message: 'ok' })),
  deleteAgent: vi.fn(() => Promise.resolve({ code: 0, data: null, message: 'ok' })),
  updateAgent: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  listAgents: vi.fn(() => Promise.resolve({ code: 0, data: [], message: 'ok' })),
  // M6 HITL 命名空间
  hitl: {
    listPendingApprovals: vi.fn(() => Promise.resolve({
      code: 0,
      data: {
        items: [{
          approval_id: 1, run_id: 'run-A1', agent_name: '处置响应 Agent',
          action: 'host:isolate:X', impact_scope: '主机 WIN-X', status: 'pending',
          guardrail_result: {
            policy_id: 'gp-host', whitelist_hit: true,
            requires_confirm: true, requires_rollback_plan: true, passed: true,
          },
        }],
        total: 1,
      },
      message: 'ok',
    })),
    approve: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
    reject: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  },
}))
vi.mock('@/api/agent', () => ({ default: agentApi }))

// M2 直接依赖 @/api/agentManagement
const agentManagement = vi.hoisted(() => ({
  listAgents: vi.fn(() => Promise.resolve({ code: 0, data: [], message: 'ok' })),
  createAgent: vi.fn(() => Promise.resolve({ code: 0, data: { agent_id: 'a1', display_name: 'A1' }, message: 'ok' })),
  updateAgent: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  deleteAgent: vi.fn(() => Promise.resolve({ code: 0, data: null, message: 'ok' })),
}))
vi.mock('@/api/agentManagement', () => agentManagement)

// M6 直接依赖 @/api/agentOrchestration
const agentOrchestration = vi.hoisted(() => ({
  listAgentRuns: vi.fn(() => Promise.resolve({ code: 0, data: { items: [], total: 0 }, message: 'ok' })),
  getAgentRun: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  approveAgentRun: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  rejectAgentRun: vi.fn(() => Promise.resolve({ code: 0, data: {}, message: 'ok' })),
  listPendingApprovals: vi.fn(() => Promise.resolve({
    code: 0,
    data: {
      items: [{
        approval_id: 1, run_id: 'run-A1', agent_name: '处置响应 Agent',
        action: 'host:isolate:X', impact_scope: '主机 WIN-X', status: 'pending',
        guardrail_result: {
          policy_id: 'gp-host', whitelist_hit: true,
          requires_confirm: true, requires_rollback_plan: true, passed: true,
        },
      }],
      total: 1,
    },
    message: 'ok',
  })),
  createAgentRun: vi.fn(),
  getSSEUrl: vi.fn(),
}))
vi.mock('@/api/agentOrchestration', () => agentOrchestration)

import { useAgentManagementStore } from '@/stores/agentManagement'
import { usePipelineCanvasStore } from '@/stores/pipelineCanvas'
import { useAgentOrchestrationStore } from '@/stores/agents'
import { useObservabilityStore } from '@/stores/observability'

describe('集成链路 A：M2 → M3 → M6 → M8 跨模块协同', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('全链路贯通：创建 Agent → 编排 run_id → HITL 批准 → 可观测 trace/日志', async () => {
    const m2 = useAgentManagementStore()
    const m3 = usePipelineCanvasStore()
    const m6 = useAgentOrchestrationStore()
    const m8 = useObservabilityStore()

    // ① M2 创建自定义 Agent
    const agent = await m2.registerAgent({ agent_id: 'a1', display_name: 'A1', kind: 'custom', status: 'active' })
    expect(agent.agent_id).toBe('a1')
    expect(agentApi.createAgent).toHaveBeenCalled()

    // ② M3 加载种子 DAG 并执行，得到 run_id
    await m3.seedFromSample()
    const run = await m3.run('E-A')
    expect(run.run_id).toBe('run-A1')
    expect(m3.currentRunId).toBe('run-A1')
    expect(agentApi.pipeline.run).toHaveBeenCalled()

    // ③ M6 拉取待审队列，任务归属本次 run
    await m6.fetchApprovals()
    expect(m6.approvals.length).toBe(1)
    const task = m6.approvals[0]
    expect(task.run_id).toBe('run-A1')
    expect(task.guardrail_result.passed).toBe(true)

    // ④ 批准
    const ok = await m6.approve(task.run_id, task.approval_id)
    expect(ok).toBeDefined()
    expect(agentApi.hitl.approve).toHaveBeenCalledWith('run-A1', { approval_id: 1 })

    // ⑤ M8 可观测：出现 trace 与日志
    await m8.fetchRun('run-A1')
    expect(m8.run).not.toBeNull()
    expect(m8.run.trace.length).toBeGreaterThan(0)
    expect(m8.run.logs.length).toBeGreaterThan(0)
    expect(m8.run.resume_point).toBe('sp-1')
  })

  it('运行态在各 store 间保持不丢（currentRunId / approvals 均有效）', async () => {
    const m3 = usePipelineCanvasStore()
    const m6 = useAgentOrchestrationStore()
    await m3.seedFromSample()
    await m3.run('E-A')
    await m6.fetchApprovals()
    // run 态在 M3 留存，HITL 任务在 M6 留存，互相不覆盖
    expect(m3.currentRunId).toBe('run-A1')
    expect(m6.approvals[0].run_id).toBe('run-A1')
  })
})
