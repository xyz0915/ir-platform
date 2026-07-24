/**
 * M3 流水线 DAG 画布 Store 单元测试（图级校验：Kahn 环检测 + 含护栏/hitl 节点；
 * 节点/边增删；seedFromSample；run 返回 run_id）。
 *
 * 设计依据：01-api-spec.md §3 / Q3 / T11。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  pipeline: {
    getSample: vi.fn(), run: vi.fn(), validate: vi.fn(), getRunStatus: vi.fn(),
    cancel: vi.fn(), resume: vi.fn(), getSSEUrl: vi.fn(), getPresets: vi.fn(),
  },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { usePipelineCanvasStore } from '../pipelineCanvas'

describe('M3 PipelineCanvas Store：图级校验与节点/边操作', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.pipeline.getSample.mockResolvedValue({
      code: 0,
      data: {
        pipeline_id: 'pipe-1', name: '示例', status: 'draft',
        requires_guardrail: true, requires_hitl: true,
        nodes: [
          { node_id: 'n-trigger', type: 'trigger', label: '触发', position: { x: 0, y: 0 } },
          { node_id: 'n-investigate', type: 'investigate', label: '调查', position: { x: 1, y: 0 } },
          { node_id: 'n-guardrail', type: 'guardrail', label: '护栏', position: { x: 2, y: 0 } },
          { node_id: 'n-end', type: 'end', label: '结束', position: { x: 3, y: 0 } },
        ],
        edges: [
          { source: 'n-trigger', target: 'n-investigate' },
          { source: 'n-investigate', target: 'n-guardrail' },
          { source: 'n-guardrail', target: 'n-end' },
        ],
      },
      message: 'ok',
    })
    api.pipeline.run.mockResolvedValue({ code: 0, data: { run_id: 'run-A1', status: 'running' }, message: 'ok' })
  })

  it('seedFromSample 加载种子 DAG 并校验通过', async () => {
    const store = usePipelineCanvasStore()
    await store.seedFromSample()
    expect(store.nodeCount).toBe(4)
    expect(store.edgeCount).toBe(3)
    expect(store.hasGuardrail).toBe(true)
    expect(store.validation.valid).toBe(true)
    expect(store.validation.errors.length).toBe(0)
  })

  it('环检测：加入回边形成环 → validateGraph 失败', async () => {
    const store = usePipelineCanvasStore()
    await store.seedFromSample()
    store.connect('n-end', 'n-trigger') // 形成环
    const v = store.validateGraph()
    expect(v.valid).toBe(false)
    expect(v.errors.some((e) => e.includes('环路'))).toBe(true)
  })

  it('缺少护栏节点 → 仅是 warning，valid 仍为 true', async () => {
    const store = usePipelineCanvasStore()
    await store.seedFromSample()
    store.removeNode('n-guardrail')
    const v = store.validateGraph()
    expect(store.hasGuardrail).toBe(false)
    expect(v.valid).toBe(true) // 仅告警，不阻断
    expect(v.warnings.some((w) => w.includes('护栏'))).toBe(true)
  })

  it('addNode / connect / removeNode / removeEdge / clear 操作闭环', async () => {
    const store = usePipelineCanvasStore()
    await store.seedFromSample()
    const n = store.addNode('hitl', { x: 5, y: 5 })
    expect(store.nodeCount).toBe(5)
    expect(store.hasHitl).toBe(true)
    // 连接真实新增节点 id → 成功
    expect(store.connect('n-end', n.node_id)).toBe(true)
    expect(store.edgeCount).toBe(4)
    // 去重：再次连接相同边返回 false
    expect(store.connect('n-end', n.node_id)).toBe(false)
    // 自环返回 false
    expect(store.connect(n.node_id, n.node_id)).toBe(false)
    // 删除边
    store.removeEdge(`e-n-end--${n.node_id}`)
    expect(store.edgeCount).toBe(3)
    // 删除节点连带边
    store.removeNode(n.node_id)
    expect(store.nodeCount).toBe(4)
    expect(store.edgeCount).toBe(3)
    // clear
    store.clear()
    expect(store.nodeCount).toBe(0)
    expect(store.edgeCount).toBe(0)
    expect(store.running).toBe(false)
  })

  it('run() 校验通过 → 调用 pipeline.run 并返回 run_id', async () => {
    const store = usePipelineCanvasStore()
    await store.seedFromSample()
    const res = await store.run('E-A')
    expect(res.run_id).toBe('run-A1')
    expect(store.currentRunId).toBe('run-A1')
    expect(api.pipeline.run).toHaveBeenCalledWith('E-A', expect.any(Array), true)
  })

  it('run() 校验失败（有环）→ 返回 null 且不调用 pipeline.run', async () => {
    const store = usePipelineCanvasStore()
    await store.seedFromSample()
    store.connect('n-end', 'n-trigger') // 成环
    const res = await store.run('E-A')
    expect(res).toBeNull()
    expect(api.pipeline.run).not.toHaveBeenCalled()
  })
})
