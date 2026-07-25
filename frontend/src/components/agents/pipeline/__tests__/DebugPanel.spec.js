/**
 * DebugPanel.vue 组件测试（Phase 3 节点级调试容器）。
 *
 * 通过 stub 5 个调试子组件与 el-*，隔离 Element Plus 与后端，
 * 验证：渲染、调试开关类切换、执行按钮触发 runNodeDebug、模式切换写草稿。
 *
 * 设计依据：02-design.md §6（右 Drawer 覆盖式 DebugPanel）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DebugPanel from '@/components/agents/pipeline/DebugPanel.vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

// ── mock 门控：@/api/agent ──
const agentApi = vi.hoisted(() => ({
  pipeline: {
    runNode: vi.fn(() =>
      Promise.resolve({
        data: {
          status: 'success', node_type: 'file_analysis', node_name: 'file_analysis',
          output_text: 'OK', structured: {}, confidence: 0.9, evidence: [],
          mode: 'real', run_id: 'debug-dp', timestamp: 't',
        },
      }),
    ),
    simulateBranch: vi.fn(() =>
      Promise.resolve({ data: { active_nodes: ['n-a'], pruned_edges: [] } }),
    ),
    getNodeRuns: vi.fn(() => Promise.resolve({ data: { items: [], total: 0 } })),
  },
}))
vi.mock('@/api/agent', () => ({ default: agentApi }))

// ── stub 子组件与 Element Plus 单选组 ──
const stubs = {
  DebugInputEditor: { template: '<div class="stub-input" />' },
  DebugOutputViewer: { template: '<div class="stub-output" />' },
  BranchSimulator: { template: '<div class="stub-branch" />' },
  DataFlowTrace: { template: '<div class="stub-flow" />' },
  DebugHistoryList: { template: '<div class="stub-history" />' },
  'el-radio-group': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    // 转发 slot 内子组件抛出的 update:modelValue 事件到外层 v-model
    template: '<div class="el-rg" @update:modelValue="$emit(\'update:modelValue\', $event)"><slot /></div>',
  },
  'el-radio-button': {
    props: ['label'],
    emits: ['update:modelValue'],
    template: '<button class="el-rb" @click="$emit(\'update:modelValue\', label)">{{label}}</button>',
  },
}

function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = usePipelineEditorStore()
  return { pinia, store }
}

describe('DebugPanel — 渲染与开关', () => {
  let ctx
  beforeEach(() => { ctx = setup(); vi.clearAllMocks() })

  it('默认渲染 aside 且未展开（无 open 类）', () => {
    const wrapper = mount(DebugPanel, { global: { stubs, plugins: [ctx.pinia] } })
    expect(wrapper.find('.dbg-panel').exists()).toBe(true)
    expect(wrapper.find('.dbg-panel').classes()).not.toContain('open')
  })

  it('debugMode=true 时展开 open 类', () => {
    ctx.store.debugMode = true
    const wrapper = mount(DebugPanel, { global: { stubs, plugins: [ctx.pinia] } })
    expect(wrapper.find('.dbg-panel').classes()).toContain('open')
  })

  it('未选节点时提示先选择节点', () => {
    ctx.store.debugMode = true
    const wrapper = mount(DebugPanel, { global: { stubs, plugins: [ctx.pinia] } })
    expect(wrapper.find('.dbg-no-node').exists()).toBe(true)
  })
})

describe('DebugPanel — 选中节点后的调试视图', () => {
  let ctx
  beforeEach(() => { ctx = setup(); vi.clearAllMocks() })

  it('渲染输入/输出/流/历史子组件与执行按钮（非 branch 不显示分支模拟）', () => {
    const n = ctx.store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    ctx.store.selectNode(n.id)
    ctx.store.debugMode = true
    const wrapper = mount(DebugPanel, { global: { stubs, plugins: [ctx.pinia] } })
    expect(wrapper.find('.dbg-run').exists()).toBe(true)
    expect(wrapper.find('.stub-input').exists()).toBe(true)
    expect(wrapper.find('.stub-output').exists()).toBe(true)
    expect(wrapper.find('.stub-flow').exists()).toBe(true)
    expect(wrapper.find('.stub-history').exists()).toBe(true)
    expect(wrapper.find('.stub-branch').exists()).toBe(false)
  })

  it('点击执行按钮触发 store.runNodeDebug', async () => {
    const n = ctx.store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    ctx.store.selectNode(n.id)
    ctx.store.debugMode = true
    const spy = vi.spyOn(ctx.store, 'runNodeDebug')
    const wrapper = mount(DebugPanel, { global: { stubs, plugins: [ctx.pinia] } })
    await wrapper.find('.dbg-run').trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalledWith(n.id)
  })
})

describe('DebugPanel — 模式切换', () => {
  let ctx
  beforeEach(() => { ctx = setup(); vi.clearAllMocks() })

  it('模式切换写入 debugDraft.mode', async () => {
    const n = ctx.store.addNode('llm', { x: 0, y: 0 }, 'file_analysis')
    ctx.store.selectNode(n.id)
    ctx.store.debugMode = true
    const wrapper = mount(DebugPanel, { global: { stubs, plugins: [ctx.pinia] } })
    // mode 为 <script setup> 中用于 v-model 的 computed，已暴露到 vm。
    // 直接赋值触发其 setter → store.saveDebugDraft。
    expect(wrapper.vm.mode).toBe('real')
    wrapper.vm.mode = 'simulate'
    await flushPromises()
    expect(ctx.store.debugDraft[n.id].mode).toBe('simulate')
  })
})
