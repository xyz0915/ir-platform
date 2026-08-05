/**
 * pipelineEditor 画布 Store 单元测试（A8：由 pipelineCanvas.store.spec.js 迁移）。
 *
 * 覆盖：loadSample 示例加载 / 图级校验（Kahn 环检测 + trigger/output 必备）/
 * 节点与连线增删 / runPipeline 返回 run_id。
 *
 * 设计依据：01-api-spec.md §3 / Q3 / T11。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  pipeline: {
    run: vi.fn(),
  },
}))
vi.mock('@/api/agent', () => ({ default: api }))

import { usePipelineEditorStore } from '../pipelineEditor'

describe('pipelineEditor Store：图级校验与节点/边操作', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.pipeline.run.mockResolvedValue({
      code: 0, data: { run_id: 'run-A1', status: 'running' }, message: 'ok',
    })
  })

  it('loadSample 加载示例 DAG（7 节点 6 连线）并校验通过', () => {
    const store = usePipelineEditorStore()
    store.loadSample()
    expect(store.nodeCount).toBe(7)
    expect(store.connectionCount).toBe(6)
    store.validatePipeline()
    expect(store.isValid).toBe(true)
    expect(store.validationMessages.some((m) => m.includes('校验通过'))).toBe(true)
  })

  it('环检测：output → trigger 形成回边 → validatePipeline 失败', () => {
    const store = usePipelineEditorStore()
    store.loadSample()
    const firstId = store.pipelineNodes[0].id
    const lastId = store.pipelineNodes[store.pipelineNodes.length - 1].id
    store.startConnect(lastId)
    store.completeConnect(firstId) // 成环
    store.validatePipeline()
    expect(store.isValid).toBe(false)
    expect(store.validationMessages.some((m) => m.includes('循环依赖'))).toBe(true)
  })

  it('缺少 trigger / output 节点 → 校验失败', () => {
    const store = usePipelineEditorStore()
    store.loadSample()
    store.removeNode(store.pipelineNodes[0].id) // 移除 trigger
    store.validatePipeline()
    expect(store.isValid).toBe(false)
    expect(store.validationMessages.some((m) => m.includes('触发器'))).toBe(true)
  })

  it('addNode / removeNode / completeConnect / removeConnection / clearCanvas 操作闭环', () => {
    const store = usePipelineEditorStore()
    store.loadSample()
    const n = store.addNode('action', { x: 1600, y: 280 }, '补充处置')
    expect(store.nodeCount).toBe(8)
    // 连线新增节点（从 output 连向新节点）
    const outputId = store.pipelineNodes.find((x) => x.type === 'output').id
    store.startConnect(outputId)
    store.completeConnect(n.id)
    expect(store.connectionCount).toBe(7)
    // 重复连线去重
    store.startConnect(outputId)
    store.completeConnect(n.id)
    expect(store.connectionCount).toBe(7)
    // 自环忽略
    store.startConnect(n.id)
    store.completeConnect(n.id)
    expect(store.connectionCount).toBe(7)
    // 删除连线
    store.removeConnection(outputId, n.id)
    expect(store.connectionCount).toBe(6)
    // 删除节点连带边
    store.removeNode(n.id)
    expect(store.nodeCount).toBe(7)
    expect(store.connectionCount).toBe(6)
    // 清空
    store.clearCanvas()
    expect(store.nodeCount).toBe(0)
    expect(store.connectionCount).toBe(0)
  })

  it('runPipeline 校验通过 → 调用 pipeline.run 并返回 run_id', async () => {
    const store = usePipelineEditorStore()
    store.loadSample()
    const res = await store.runPipeline('E-A')
    expect(res.run_id).toBe('run-A1')
    expect(store.lastRunId).toBe('run-A1')
    expect(api.pipeline.run).toHaveBeenCalledWith('E-A', expect.any(Array), true)
  })

  it('runPipeline 校验失败（有环）→ 抛错且不调用 pipeline.run', async () => {
    const store = usePipelineEditorStore()
    store.loadSample()
    const firstId = store.pipelineNodes[0].id
    const lastId = store.pipelineNodes[store.pipelineNodes.length - 1].id
    store.startConnect(lastId)
    store.completeConnect(firstId) // 成环
    await expect(store.runPipeline('E-A')).rejects.toThrow('管道校验未通过')
    expect(api.pipeline.run).not.toHaveBeenCalled()
  })
})
