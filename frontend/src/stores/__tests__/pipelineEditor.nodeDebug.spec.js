/**
 * pipelineEditor Store 单元测试 — Phase 3 节点级调试（ KC-1 / BRANCH-01 ）。
 *
 * 通过 vi.mock('@/api/agent') 门控真实后端，覆盖：
 * - toggleDebug / openDebug / closeDebug
 * - ensureDebugDraft / saveDebugDraft
 * - runNodeDebug（成功 / 失败 / 历史刷新）
 * - runBranchSim + applyBranchSelection（分支模拟 → branchPath / branchSelection）
 * - loadNodeRuns（历史回填）
 *
 * 设计依据：02-design.md §3 / §5（门控 USE_MOCK.nodeDebug）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

// ── mock 门控：@/api/agent 统一适配层 ──
const agentApi = vi.hoisted(() => ({
  pipeline: {
    runNode: vi.fn(() =>
      Promise.resolve({
        data: {
          status: 'success',
          node_type: 'file_analysis',
          node_name: 'file_analysis',
          output_text: 'FAKE OUTPUT',
          structured: { count: 1 },
          confidence: 0.5,
          evidence: [],
          mode: 'real',
          run_id: 'debug-fake123',
          timestamp: '2026-07-06T00:00:00Z',
        },
      }),
    ),
    simulateBranch: vi.fn(() =>
      Promise.resolve({
        data: {
          chosen_branch: 'A',
          chosen_target: 'n-a',
          active_nodes: ['n-a', 'n-c'],
          pruned_nodes: ['n-b'],
          pruned_edges: [{ sourceId: 'n-b', targetId: 'n-d' }],
        },
      }),
    ),
    getNodeRuns: vi.fn(() =>
      Promise.resolve({
        data: {
          items: [{ run_id: 'debug-fake123', node_name: 'file_analysis' }],
          total: 1,
        },
      }),
    ),
  },
}))
vi.mock('@/api/agent', () => ({ default: agentApi }))

function makeStore() {
  setActivePinia(createPinia())
  return usePipelineEditorStore()
}

describe('pipelineEditor — Phase 3 调试开关', () => {
  let store
  beforeEach(() => {
    store = makeStore()
    vi.clearAllMocks()
    // 恢复默认 mock 实现（clearAllMocks 仅清调用记录，保留实现）
    agentApi.pipeline.runNode.mockResolvedValue({
      data: {
        status: 'success', node_type: 'file_analysis', node_name: 'file_analysis',
        output_text: 'FAKE OUTPUT', structured: { count: 1 }, confidence: 0.5,
        evidence: [], mode: 'real', run_id: 'debug-fake123', timestamp: 't',
      },
    })
    agentApi.pipeline.simulateBranch.mockResolvedValue({
      data: {
        chosen_branch: 'A', chosen_target: 'n-a',
        active_nodes: ['n-a', 'n-c'], pruned_nodes: ['n-b'],
        pruned_edges: [{ sourceId: 'n-b', targetId: 'n-d' }],
      },
    })
    agentApi.pipeline.getNodeRuns.mockResolvedValue({
      data: { items: [{ run_id: 'debug-fake123', node_name: 'file_analysis' }], total: 1 },
    })
  })

  it('toggleDebug 切换调试面板', () => {
    expect(store.debugMode).toBe(false)
    store.toggleDebug()
    expect(store.debugMode).toBe(true)
    store.toggleDebug()
    expect(store.debugMode).toBe(false)
  })

  it('closeDebug 复位 branchPath 与开关', () => {
    store.branchPath = {
      activeNodes: new Set(['n-a']),
      prunedEdges: [{ sourceId: 'x', targetId: 'y' }],
    }
    store.closeDebug()
    expect(store.debugMode).toBe(false)
    expect(store.branchPath.activeNodes).toBeNull()
    expect(store.branchPath.prunedEdges).toEqual([])
  })
})

describe('pipelineEditor — Phase 3 草稿', () => {
  let store
  beforeEach(() => { store = makeStore(); vi.clearAllMocks() })

  it('ensureDebugDraft 为节点生成默认草稿', () => {
    const n = store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    const draft = store.ensureDebugDraft(n.id)
    expect(draft).toMatchObject({ input_params: {}, mode: 'real' })
    expect(draft.context_vars).toEqual({})
    // 二次调用返回同一草稿（Pinia 将原对象包成 reactive 代理，
    // 故用深比较而非 toBe 引用相等）
    expect(store.ensureDebugDraft(n.id)).toStrictEqual(draft)
  })

  it('saveDebugDraft 更新草稿', () => {
    const n = store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    store.ensureDebugDraft(n.id)
    store.saveDebugDraft(n.id, {
      input_params: { max_files: 5 },
      context_vars: { host_id: 'h1' },
      mode: 'simulate',
    })
    const d = store.debugDraft[n.id]
    expect(d.mode).toBe('simulate')
    expect(d.context_vars).toEqual({ host_id: 'h1' })
  })
})

describe('pipelineEditor — runNodeDebug', () => {
  let store
  beforeEach(() => {
    store = makeStore()
    vi.clearAllMocks()
    agentApi.pipeline.runNode.mockResolvedValue({
      data: {
        status: 'success', node_type: 'file_analysis', node_name: 'file_analysis',
        output_text: 'OK', structured: {}, confidence: 0.9, evidence: [],
        mode: 'real', run_id: 'debug-r1', timestamp: 't',
      },
    })
    agentApi.pipeline.getNodeRuns.mockResolvedValue({
      data: { items: [{ run_id: 'debug-r1' }], total: 1 },
    })
  })

  it('成功时置 success 并回填 activeNodeRun 与历史', async () => {
    const n = store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    store.selectNode(n.id)
    const res = await store.runNodeDebug(n.id)
    expect(res.status).toBe('success')
    expect(store.nodeRunStatus[n.id]).toBe('success')
    expect(store.activeNodeRun.run_id).toBe('debug-r1')
    expect(agentApi.pipeline.runNode).toHaveBeenCalledOnce()
    // 执行后自动刷新历史
    expect(agentApi.pipeline.getNodeRuns).toHaveBeenCalledOnce()
    expect(store.nodeRunHistory).toHaveLength(1)
  })

  it('失败时置 failed 并写入错误', async () => {
    agentApi.pipeline.runNode.mockRejectedValueOnce(new Error('boom'))
    const n = store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    store.selectNode(n.id)
    const res = await store.runNodeDebug(n.id)
    expect(res).toBeNull()
    expect(store.nodeRunStatus[n.id]).toBe('failed')
    expect(store.activeNodeRun.status).toBe('failed')
    expect(store.activeNodeRun.error).toContain('boom')
  })

  it('无对应节点时直接返回 null', async () => {
    const res = await store.runNodeDebug('no-such-id')
    expect(res).toBeNull()
    expect(agentApi.pipeline.runNode).not.toHaveBeenCalled()
  })
})

describe('pipelineEditor — 分支模拟', () => {
  let store
  beforeEach(() => {
    store = makeStore()
    vi.clearAllMocks()
    agentApi.pipeline.simulateBranch.mockResolvedValue({
      data: {
        chosen_branch: 'A', chosen_target: 'n-a',
        active_nodes: ['n-a', 'n-c'], pruned_nodes: ['n-b'],
        pruned_edges: [{ sourceId: 'n-b', targetId: 'n-d' }],
      },
    })
  })

  function addBranchNode() {
    const n = store.addNode('branch', { x: 0, y: 0 }, 'branch_demo')
    n.config.branches = [
      { label: 'A', target: 'n-a' },
      { label: 'B', target: 'n-b' },
    ]
    store.connections.push({ sourceId: 'n-a', targetId: 'n-c' })
    store.connections.push({ sourceId: 'n-b', targetId: 'n-d' })
    store.selectNode(n.id)
    return n
  }

  it('runBranchSim 仅对 branch 节点生效', async () => {
    const n = store.addNode('llm', { x: 0, y: 0 }, 'llm')
    store.selectNode(n.id)
    const res = await store.runBranchSim(n.id)
    expect(res).toBeNull()
    expect(agentApi.pipeline.simulateBranch).not.toHaveBeenCalled()
  })

  it('runBranchSim 写入 branchPath 与 branchSelection', async () => {
    const n = addBranchNode()
    const res = await store.runBranchSim(n.id)
    expect(res.active_nodes).toEqual(['n-a', 'n-c'])
    expect(store.branchSelection[n.id]).toBe('A')
    expect(store.branchPath.activeNodes instanceof Set).toBe(true)
    expect([...store.branchPath.activeNodes]).toEqual(['n-a', 'n-c'])
    expect(store.branchPath.prunedEdges).toEqual([{ sourceId: 'n-b', targetId: 'n-d' }])
  })

  it('applyBranchSelection 更新选择并触发模拟', async () => {
    const n = addBranchNode()
    store.applyBranchSelection(n.id, 'A')
    await flushPromises()
    expect(store.branchSelection[n.id]).toBe('A')
    expect(agentApi.pipeline.simulateBranch).toHaveBeenCalledOnce()
    expect(store.branchPath.activeNodes instanceof Set).toBe(true)
  })
})

describe('pipelineEditor — loadNodeRuns', () => {
  let store
  beforeEach(() => {
    store = makeStore()
    vi.clearAllMocks()
    agentApi.pipeline.getNodeRuns.mockResolvedValue({
      data: {
        items: [
          { run_id: 'debug-h1', node_name: 'file_analysis' },
          { run_id: 'debug-h2' },
        ],
        total: 2,
      },
    })
  })

  it('回填 nodeRunHistory', async () => {
    const n = store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    store.selectNode(n.id)
    const items = await store.loadNodeRuns(n.id)
    expect(items).toHaveLength(2)
    expect(store.nodeRunHistory).toHaveLength(2)
    expect(agentApi.pipeline.getNodeRuns).toHaveBeenCalledWith({ node_name: 'file_analysis' })
  })

  it('无节点时清空历史', async () => {
    const items = await store.loadNodeRuns('nope')
    expect(items).toEqual([])
    expect(store.nodeRunHistory).toEqual([])
  })
})
