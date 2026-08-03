/**
 * NodeLibrary.vue — 11 节点真实化（T05-5）渲染验证。
 *
 * 覆盖：
 *  1) 挂载 SFC：断言 6 个新节点（condition/parallel/data-process/intel-query/mcp-tool/intel-source）
 *     在对应分组渲染出中文 label；同时验证 guard/hitl/action/output 也渲染。
 *  2) 源码结构断言（互补）：6 个新节点 type 一律引用 NodeType 枚举（非字符串字面量）。
 *
 * 后端零改动，仅前端增量；本测试不得修改被测业务源码。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import NodeLibrary from '@/components/agents/pipeline/NodeLibrary.vue'

// 6 个新节点（T03）：枚举键名 / 后端 key / 分组名 / 中文 label
const NEW_NODES = [
  { key: 'CONDITION', value: 'condition', group: '流程控制', label: '条件分支' },
  { key: 'PARALLEL', value: 'parallel', group: '流程控制', label: '并行分支' },
  { key: 'DATA_PROCESS', value: 'data-process', group: '调查分析', label: '数据处理' },
  { key: 'INTEL_QUERY', value: 'intel-query', group: '调查分析', label: '外部情报查询' },
  { key: 'MCP_TOOL', value: 'mcp-tool', group: '数据源', label: 'MCP 工具' },
  { key: 'INTEL_SOURCE', value: 'intel-source', group: '数据源', label: '情报源接入' },
]

// 本期新增/映射的其余节点（guard/hitl/action/output）也应在节点库渲染
const OTHER_IMPL = [
  { group: '安全控制', label: '护栏' },
  { group: '安全控制', label: '人工审核' },
  { group: '安全控制', label: '处置执行' },
  { group: '数据源', label: '知识库' },
]

describe('NodeLibrary — 挂载渲染（11 节点-impl 全部可见）', () => {
  const wrapper = mount(NodeLibrary)
  const groups = wrapper.findAll('.node-group')
  const labelsByGroup = {}
  for (const g of groups) {
    const title = g.find('.node-group-title').text()
    labelsByGroup[title] = g.findAll('.node-option').map((opt) => opt.findAll('span')[0].text())
  }

  it.each(NEW_NODES)('$label 在「$group」分组渲染', ({ group, label }) => {
    expect(labelsByGroup[group]).toBeDefined()
    expect(labelsByGroup[group]).toContain(label)
  })

  it.each(OTHER_IMPL)('$label 在「$group」分组渲染', ({ group, label }) => {
    expect(labelsByGroup[group]).toBeDefined()
    expect(labelsByGroup[group]).toContain(label)
  })
})

describe('NodeLibrary — 源码结构断言（6 个新节点引用 NodeType 枚举）', () => {
  const testDir = import.meta.dirname ?? dirname(fileURLToPath(import.meta.url))
  const source = readFileSync(join(testDir, '../NodeLibrary.vue'), 'utf-8')

  it.each(NEW_NODES)('存在 NodeType.$key 枚举引用', ({ key }) => {
    expect(source).toContain(`NodeType.${key}`)
  })

  it.each(NEW_NODES)('不应出现 type: "$value" 字符串字面量', ({ value }) => {
    expect(source).not.toContain(`type: '${value}'`)
    expect(source).not.toContain(`type: "${value}"`)
  })
})
