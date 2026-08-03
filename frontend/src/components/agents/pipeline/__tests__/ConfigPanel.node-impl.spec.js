/**
 * ConfigPanel.vue — 11 节点真实化（T05-5）「节点参数」区验证。
 *
 * 覆盖：
 *  1) 挂载 SFC + pipelineEditor store：对 11 种节点类型逐一设置选中节点，
 *     断言「节点参数」区渲染出对应字段标签（读写 node.config.input_params）。
 *  2) 源码结构断言（互补）：NODE_PARAMS_TYPES 含 11 种类型；关键字段
 *     （block / require_hitl / allow_default_llm 开关）在源码中。
 *
 * 后端零改动，仅前端增量；本测试不得修改被测业务源码。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import { NodeType } from '@/constants/pipelineTypes'
import ConfigPanel from '@/components/agents/pipeline/ConfigPanel.vue'

// 11 种节点类型 → 期望渲染的字段标签（A4 配置面板表）
const NODE_PARAM_FIELDS = [
  { type: NodeType.GUARD, fields: ['策略', '阻断', '原因'] },
  { type: NodeType.HITL, fields: ['动作', '原因'] },
  { type: NodeType.CONDITION, fields: ['来源'] },
  { type: NodeType.PARALLEL, fields: [] }, // 动态行：无固定 label 区（branch 行由按钮添加）
  { type: NodeType.DATA_PROCESS, fields: ['来源'] },
  { type: NodeType.INTEL_QUERY, fields: ['类型', '指标值', '情报源'] },
  { type: NodeType.ACTION, fields: ['动作', '操作人', '需审批'] },
  { type: NodeType.OUTPUT, fields: ['关键词', '分类', '条数'] },
  { type: NodeType.MCP_TOOL, fields: ['工具ID'] },
  { type: NodeType.INTEL_SOURCE, fields: ['仅启用', '情报源'] },
  { type: NodeType.LLM, fields: ['Profile', 'Agent引用', '默认LLM'] },
]

function setupStoreWithNode(type) {
  setActivePinia(createPinia())
  const store = usePipelineEditorStore()
  const node = store.addNode(type, { x: 100, y: 100 })
  store.selectNode(node.id)
  return store
}

describe('ConfigPanel — 11 种节点「节点参数」区渲染', () => {
  it.each(NODE_PARAM_FIELDS)('$type 渲染节点参数区及字段', ({ type, fields }) => {
    setupStoreWithNode(type)
    const wrapper = mount(ConfigPanel, {
      global: {
        stubs: {
          ElSelect: { template: '<div><slot /></div>' },
          ElOption: true,
          ConfigSection: { template: '<div><slot /></div>' },
        },
      },
    })
    const nodeParams = wrapper.find('.node-params')
    expect(nodeParams.exists()).toBe(true)
    for (const f of fields) {
      expect(nodeParams.text()).toContain(f)
    }
  })

  it('未选中节点时不渲染节点参数区', () => {
    setActivePinia(createPinia())
    const wrapper = mount(ConfigPanel, {
      global: { stubs: { ElSelect: true, ElOption: true, ConfigSection: true } },
    })
    expect(wrapper.find('.node-params').exists()).toBe(false)
    expect(wrapper.find('.config-empty').exists()).toBe(true)
  })
})

describe('ConfigPanel — 源码结构断言（11 种类型 + 关键开关）', () => {
  const testDir = import.meta.dirname ?? dirname(fileURLToPath(import.meta.url))
  const source = readFileSync(join(testDir, '../ConfigPanel.vue'), 'utf-8')

  it('NODE_PARAMS_TYPES 含 11 种类型', () => {
    for (const { type } of NODE_PARAM_FIELDS) {
      expect(source).toContain(`NodeType.${Object.keys(NodeType).find((k) => NodeType[k] === type)}`)
    }
  })

  it('关键开关字段存在（block / require_hitl / allow_default_llm）', () => {
    expect(source).toContain("updateInputParam('block'")
    expect(source).toContain("updateInputParam('require_hitl'")
    expect(source).toContain("updateInputParam('allow_default_llm'")
  })
})
