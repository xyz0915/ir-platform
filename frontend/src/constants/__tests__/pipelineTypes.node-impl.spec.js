/**
 * pipelineTypes — 11 节点真实化（T05-5）常量回归测试。
 *
 * 验证：
 *  - NodeType 枚举 11 个节点-impl 值存在，且值与后端 runner 键完全一致
 *    （guard/hitl/condition/parallel/data-process/intel-query/action/output/mcp-tool/intel-source/llm）
 *  - NodeTypeMeta 11 条元信息（label/icon/phase/badgeColor/track）
 *  - NODE_DEFAULT_INPUT_PARAMS 11 类默认 input_params 骨架
 *  - createNodeData 注入 config.input_params
 *  - ACTION_OPTIONS 7 种处置动作
 *
 * 后端零改动，仅前端增量；本测试不得修改被测业务源码。
 */
import { describe, it, expect } from 'vitest'
import {
  NodeType,
  NodeTypeMeta,
  NODE_DEFAULT_INPUT_PARAMS,
  ACTION_OPTIONS,
  createNodeData,
} from '@/constants/pipelineTypes'

// 11 个节点-impl 类型：枚举键名 / 后端 runner 键（枚举值）/ NodeTypeMeta label
const NODE_IMPL = [
  { key: 'GUARD', value: 'guard', label: '护栏' },
  { key: 'HITL', value: 'hitl', label: '人工审核' },
  { key: 'CONDITION', value: 'condition', label: '条件分支' },
  { key: 'PARALLEL', value: 'parallel', label: '并行分支' },
  { key: 'DATA_PROCESS', value: 'data-process', label: '数据处理' },
  { key: 'INTEL_QUERY', value: 'intel-query', label: '外部情报查询' },
  { key: 'ACTION', value: 'action', label: '处置执行' },
  { key: 'OUTPUT', value: 'output', label: '报告输出' },
  { key: 'MCP_TOOL', value: 'mcp-tool', label: 'MCP 工具' },
  { key: 'INTEL_SOURCE', value: 'intel-source', label: '情报源接入' },
  { key: 'LLM', value: 'llm', label: '大模型调用' },
]

describe('NodeType — 11 节点-impl 枚举值（与后端 runner 键一致）', () => {
  it.each(NODE_IMPL)('$key === "$value"', ({ key, value }) => {
    expect(NodeType[key]).toBe(value)
  })
})

describe('NodeTypeMeta — 11 节点-impl 元信息', () => {
  it.each(NODE_IMPL)('$key meta: label/icon/phase/badgeColor/track 完整', ({ key, value, label }) => {
    const meta = NodeTypeMeta[value]
    expect(meta).toBeDefined()
    expect(NodeTypeMeta[NodeType[key]]).toBe(meta)
    expect(meta.label).toBe(label)
    expect(meta.icon).toBeTruthy()
    expect(meta.phase).toBeTruthy()
    expect(meta.badgeColor).toBeTruthy()
    expect(typeof meta.track).toBe('number')
  })

  it('11 个类型在 NodeTypeMeta 中无一遗漏', () => {
    expect(NODE_IMPL.every(({ value }) => NodeTypeMeta[value] != null)).toBe(true)
  })
})

describe('NODE_DEFAULT_INPUT_PARAMS — 11 类默认骨架', () => {
  it.each(NODE_IMPL)('$key 有默认 input_params 骨架', ({ key, value }) => {
    expect(NODE_DEFAULT_INPUT_PARAMS[NodeType[key]]).toBeDefined()
    expect(typeof NODE_DEFAULT_INPUT_PARAMS[NodeType[key]]).toBe('object')
    expect(NODE_DEFAULT_INPUT_PARAMS[value]).toBe(NODE_DEFAULT_INPUT_PARAMS[NodeType[key]])
  })

  it('关键默认值正确（block/allow_default_llm 默认关 = 零意外）', () => {
    expect(NODE_DEFAULT_INPUT_PARAMS[NodeType.GUARD].block).toBe(false)
    expect(NODE_DEFAULT_INPUT_PARAMS[NodeType.LLM].allow_default_llm).toBe(false)
    expect(NODE_DEFAULT_INPUT_PARAMS[NodeType.HITL].action).toBe('export_report')
    expect(NODE_DEFAULT_INPUT_PARAMS[NodeType.INTEL_QUERY].ioc_type).toBe('ip')
    expect(NODE_DEFAULT_INPUT_PARAMS[NodeType.OUTPUT].limit).toBe(5)
    expect(Array.isArray(NODE_DEFAULT_INPUT_PARAMS[NodeType.CONDITION].conditions)).toBe(true)
    expect(Array.isArray(NODE_DEFAULT_INPUT_PARAMS[NodeType.PARALLEL].branches)).toBe(true)
  })
})

describe('createNodeData — 注入 config.input_params', () => {
  it.each(NODE_IMPL)('$key createNodeData 注入 config.input_params', ({ key, value }) => {
    let data
    expect(() => {
      data = createNodeData(NodeType[key], { x: 0, y: 0 })
    }).not.toThrow()
    expect(data.type).toBe(value)
    expect(data.config.input_params).toEqual(NODE_DEFAULT_INPUT_PARAMS[value])
  })
})

describe('ACTION_OPTIONS — 7 种处置动作', () => {
  it('包含 7 种标准动作', () => {
    expect(ACTION_OPTIONS).toEqual([
      'block_ip',
      'isolate_host',
      'export_report',
      'mark_false_positive',
      'add_whitelist',
      'create_case',
      'add_note',
    ])
  })
})
