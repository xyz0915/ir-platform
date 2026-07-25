/**
 * pipelineTypes — 调色板扩展回归测试（7 个后端分析节点）。
 *
 * 验证「扩展前端调色板接入 7 个后端分析节点」增量改动：
 *  - NodeType 枚举新增 7 个 key，值须与后端 pipeline_engine._get_node_runner 的 key 完全一致
 *  - NodeTypeMeta 新增 7 条中文元信息（phase:'analysis'、badge-info、track:0）
 *  - createNodeData(NodeType.X, {x:0,y:0}) 对 7 个类型逐一调用不抛错，
 *    且返回对象 type=后端 key、typeLabel=对应中文（缺一条 meta 会抛 Unknown node type）
 *
 * 后端零改动，仅前端增量；本测试不得修改被测业务源码。
 */
import { describe, it, expect } from 'vitest'
import { NodeType, NodeTypeMeta, createNodeData } from '@/constants/pipelineTypes'

// 7 个扩展节点的「枚举键名 / 后端 key(枚举值) / 中文 label」对应表
const EXTENSION = [
  { key: 'FILE_ANALYSIS', value: 'file_analysis', label: '文件分析' },
  { key: 'PROCESS_ANALYSIS', value: 'process_analysis', label: '进程分析' },
  { key: 'NETWORK_ANALYSIS', value: 'network_analysis', label: '网络分析' },
  { key: 'REGISTRY_ANALYSIS', value: 'registry_analysis', label: '注册表分析' },
  { key: 'TIMELINE', value: 'timeline', label: '时间线重建' },
  { key: 'ROOT_CAUSE', value: 'root_cause', label: '根因定位' },
  { key: 'THREAT_INTEL', value: 'threat_intel', label: '威胁情报' },
]

describe('NodeType — 7 个扩展分析节点枚举值', () => {
  it('新增 7 个枚举 key 全部存在', () => {
    for (const { key } of EXTENSION) {
      expect(NodeType[key]).toBeDefined()
    }
  })

  it.each(EXTENSION)('$key === "$value" （与后端 runner key 一致）', ({ key, value }) => {
    expect(NodeType[key]).toBe(value)
  })
})

describe('NodeTypeMeta — 7 个扩展分析节点元信息', () => {
  it.each(EXTENSION)(
    '$key meta: label/phase/badgeColor/track 正确',
    ({ key, value, label }) => {
      // NodeTypeMeta 以枚举值（后端 key）作为键
      const meta = NodeTypeMeta[value]
      expect(meta).toBeDefined()
      expect(NodeTypeMeta[NodeType[key]]).toBe(meta)

      expect(meta.label).toBe(label)
      expect(meta.phase).toBe('analysis')
      expect(meta.badgeColor).toBe('badge-info')
      expect(meta.track).toBe(0)
    },
  )

  it('7 个扩展节点在 NodeTypeMeta 中无一遗漏', () => {
    const present = EXTENSION.every(({ value }) => NodeTypeMeta[value] != null)
    expect(present).toBe(true)
  })
})

describe('createNodeData — 7 个扩展分析节点可正常创建', () => {
  it.each(EXTENSION)(
    '$key createNodeData 不抛错且 type/typeLabel 正确',
    ({ key, value, label }) => {
      let data
      expect(() => {
        data = createNodeData(NodeType[key], { x: 0, y: 0 })
      }).not.toThrow()
      expect(data).toBeDefined()
      expect(data.type).toBe(value)
      expect(data.typeLabel).toBe(label)
    },
  )

  it('7 个扩展节点全部可创建且元信息完整（无 Unknown node type）', () => {
    for (const { key } of EXTENSION) {
      expect(() => createNodeData(NodeType[key], { x: 0, y: 0 })).not.toThrow()
    }
  })
})
