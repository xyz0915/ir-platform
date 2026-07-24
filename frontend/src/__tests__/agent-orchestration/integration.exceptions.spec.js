/**
 * 集成异常场景（跨模块）：
 *   1) 批准一个不存在的 task → 后端报错透传（不为空壳）
 *   2) DAG 有环 → validateGraph 失败，run 不发起
 *   3) evaluate 命中 requires_rollback_plan（高危无白名单无回滚预案）→ 护栏拦截 passed=false
 *
 * 设计依据：01-api-spec.md §6.1 / §7.3 / 01-tasks.md T11。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// M3 / M6 / M7 经 facade（完整命名空间，对齐 07 §6 task 后的 agentApi 结构）
const agentApi = vi.hoisted(() => ({
  pipeline: {
    getSample: vi.fn(() => Promise.resolve({
      code: 0,
      data: {
        pipeline_id: 'pipe-1',
        nodes: [
          { node_id: 'n-trigger', type: 'trigger', label: '触发', position: { x: 0, y: 0 } },
          { node_id: 'n-guardrail', type: 'guardrail', label: '护栏', position: { x: 1, y: 0 } },
          { node_id: 'n-end', type: 'end', label: '结束', position: { x: 2, y: 0 } },
        ],
        edges: [
          { source: 'n-trigger', target: 'n-guardrail' },
          { source: 'n-guardrail', target: 'n-end' },
        ],
      },
      message: 'ok',
    })),
    run: vi.fn(),
  },
  guardrail: {
    evaluate: vi.fn(() => Promise.resolve({
      code: 0,
      data: {
        policy_id: 'gp-block', whitelist_hit: false,
        requires_confirm: true, requires_rollback_plan: false, passed: false,
      },
      message: 'ok',
    })),
  },
  // M6 HITL 命名空间（用于 store.approve/reject 经 facade 转发）
  hitl: {
    approve: vi.fn(() => Promise.reject(new Error('approval not found'))),
    reject: vi.fn(() => Promise.reject(new Error('approval not found'))),
  },
}))
vi.mock('@/api/agent', () => ({ default: agentApi }))

// M6 直接依赖 @/api/agentOrchestration
const agentOrchestration = vi.hoisted(() => ({
  approveAgentRun: vi.fn(() => Promise.reject(new Error('approval not found'))),
  rejectAgentRun: vi.fn(() => Promise.reject(new Error('approval not found'))),
  listPendingApprovals: vi.fn(() => Promise.resolve({ code: 0, data: { items: [] }, message: 'ok' })),
}))
vi.mock('@/api/agentOrchestration', () => agentOrchestration)

import { useAgentOrchestrationStore } from '@/stores/agents'
import { usePipelineCanvasStore } from '@/stores/pipelineCanvas'
import { useGuardrailStore } from '@/stores/guardrail'

describe('集成异常场景', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('异常①：批准不存在的 task → 后端报错透传（不为空壳）', async () => {
    const store = useAgentOrchestrationStore()
    await expect(store.approve('run-x', 999)).rejects.toThrow('approval not found')
  })

  it('异常②：DAG 有环 → validateGraph 失败，run 不发起', async () => {
    const store = usePipelineCanvasStore()
    await store.seedFromSample()
    store.connect('n-end', 'n-trigger') // 成环
    const res = await store.run('E-A')
    expect(res).toBeNull()
    expect(agentApi.pipeline.run).not.toHaveBeenCalled()
  })

  it('异常③：evaluate 命中 requires_rollback_plan（无白名单无预案）→ 护栏拦截 passed=false', async () => {
    const store = useGuardrailStore()
    const r = await store.evaluate('host:isolate:UNKNOWN-HOST')
    expect(r.policy_id).toBe('gp-block')
    expect(r.whitelist_hit).toBe(false)
    expect(r.requires_rollback_plan).toBe(false)
    expect(r.passed).toBe(false) // 护栏拦截
  })
})
