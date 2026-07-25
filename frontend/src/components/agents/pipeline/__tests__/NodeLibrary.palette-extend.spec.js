/**
 * NodeLibrary.vue — 调色板扩展回归测试（7 个后端分析节点）。
 *
 * 验证「调查分析」分组新增 7 个分析节点：
 *  1) 挂载 SFC，断言「调查分析」分组渲染出 7 个新中文 label。
 *  2) 源码结构断言（互补）：读取 NodeLibrary.vue 文本，
 *     - 存在 7 处 NodeType.X 枚举引用（非字符串字面量）
 *     - 7 个中文 label 字符串均在
 *     - 不应出现 type: 'file_analysis' 这类字符串字面量
 *
 * 后端零改动，仅前端增量；本测试不得修改被测业务源码。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import NodeLibrary from '@/components/agents/pipeline/NodeLibrary.vue'

// 7 个扩展节点的「枚举键名 / 后端 key / 中文 label」对应表
const EXTENSION = [
  { key: 'FILE_ANALYSIS', value: 'file_analysis', label: '文件分析' },
  { key: 'PROCESS_ANALYSIS', value: 'process_analysis', label: '进程分析' },
  { key: 'NETWORK_ANALYSIS', value: 'network_analysis', label: '网络分析' },
  { key: 'REGISTRY_ANALYSIS', value: 'registry_analysis', label: '注册表分析' },
  { key: 'TIMELINE', value: 'timeline', label: '时间线重建' },
  { key: 'ROOT_CAUSE', value: 'root_cause', label: '根因定位' },
  { key: 'THREAT_INTEL', value: 'threat_intel', label: '威胁情报' },
]

// ── 1) 挂载 SFC 验证渲染 ──
describe('NodeLibrary — 挂载渲染（调查分析分组新增 7 个节点）', () => {
  it('「调查分析」分组渲染出 7 个新中文 label', () => {
    const wrapper = mount(NodeLibrary)
    const groups = wrapper.findAll('.node-group')
    const analysisGroup = groups.find(
      (g) => g.find('.node-group-title').text() === '调查分析',
    )
    expect(analysisGroup).toBeDefined()

    // 每个 node-option 的第一个 span 是 label
    const labels = analysisGroup
      .findAll('.node-option')
      .map((opt) => opt.findAll('span')[0].text())

    for (const { label } of EXTENSION) {
      expect(labels).toContain(label)
    }
    // 分组内恰好新增这 7 个（原有 3 个：大模型调用/数据处理/外部情报查询）
    expect(labels.filter((l) => EXTENSION.some((e) => e.label === l))).toHaveLength(7)
  })
})

// ── 2) 源码结构断言（互补，验证非字符串字面量引用）──
describe('NodeLibrary — 源码结构断言（7 个 NodeType 枚举引用 + 7 个中文 label）', () => {
  const testDir = import.meta.dirname ?? dirname(fileURLToPath(import.meta.url))
  const source = readFileSync(join(testDir, '../NodeLibrary.vue'), 'utf-8')

  it('存在 7 处 NodeType.X 枚举引用（type 一律引用枚举，避免字符串字面量）', () => {
    for (const { key } of EXTENSION) {
      expect(source).toContain(`NodeType.${key}`)
    }
  })

  it('7 个中文 label 字符串均在源码中', () => {
    for (const { label } of EXTENSION) {
      expect(source).toContain(label)
    }
  })

  it('不应出现 7 个后端 key 的字符串字面量 type 赋值', () => {
    for (const { value } of EXTENSION) {
      expect(source).not.toContain(`type: '${value}'`)
      expect(source).not.toContain(`type: "${value}"`)
    }
  })
})
