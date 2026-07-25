/**
 * PipelineNode.vue — 节点角标类型标签中文化（R1 修复）专项测试。
 *
 * 验证 typeTag 计算属性（@/components/agents/pipeline/PipelineNode.vue L61）的
 * 三级取值优先级，确保画布节点角标显示中文而非英文枚举：
 *   1) 优先取 nodeData.typeLabel（createNodeData 注入的中文 label）
 *   2) 回退取 NodeTypeMeta[type]?.label（已含全部类型中文 label）
 *   3) 未知类型且无 meta 时显示原始 type，保证不崩溃、不空白
 *
 * 设计依据：R1 修复说明 + pipelineTypes.js 的 NodeTypeMeta / createNodeData。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PipelineNode from '@/components/agents/pipeline/PipelineNode.vue'
import { createNodeData } from '@/constants/pipelineTypes'

// Pinia 必须在组件 setup 调用 usePipelineEditorStore() 之前激活
function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return { pinia }
}

describe('PipelineNode — 角标类型标签中文化 (R1 修复)', () => {
  let ctx
  beforeEach(() => {
    ctx = setup()
  })

  it('优先级①：typeLabel 优先 → 文件分析节点显示「文件分析」', () => {
    // 模拟 createNodeData 真实产物（含注入的中文 typeLabel）
    const nodeData = createNodeData('file_analysis', { x: 0, y: 0 }, '文件分析')
    const wrapper = mount(PipelineNode, {
      props: { nodeData },
      global: { plugins: [ctx.pinia] },
    })

    const tag = wrapper.find('.type-tag')
    expect(tag.exists()).toBe(true)
    expect(tag.text()).toBe('文件分析')
  })

  it('优先级②：无 typeLabel 时回退 NodeTypeMeta → network_analysis 显示「网络分析」', () => {
    // 手写最小对象：仅有 type，无 typeLabel，验证回退路径
    const nodeData = {
      id: 'node-fallback-network',
      type: 'network_analysis',
      name: '网络分析',
      position: { x: 0, y: 0 },
    }
    const wrapper = mount(PipelineNode, {
      props: { nodeData },
      global: { plugins: [ctx.pinia] },
    })

    expect(wrapper.find('.type-tag').text()).toBe('网络分析')
  })

  it('优先级③：未知类型无 meta → 显示原始 type，不崩溃且不空白', () => {
    const nodeData = {
      id: 'node-unknown-x',
      type: 'some_unknown_x',
      name: 'some_unknown_x',
      position: { x: 0, y: 0 },
    }
    const wrapper = mount(PipelineNode, {
      props: { nodeData },
      global: { plugins: [ctx.pinia] },
    })

    const tag = wrapper.find('.type-tag')
    expect(tag.exists()).toBe(true)
    expect(tag.text()).toBe('some_unknown_x')
    expect(tag.text()).not.toBe('')
  })
})
