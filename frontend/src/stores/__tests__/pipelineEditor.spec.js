/**
 * pipelineEditor Store 单元测试 — 工作流编排画布状态管理。
 *
 * 覆盖范围：
 * - State 初始化
 * - 节点操作：add/remove/move/select
 * - 连线操作：startConnect/completeConnect/cancelConnect/removeConnection
 * - 跨轨道连线检测
 * - 重复连线检测
 * - 自连接检测
 * - 配置操作：updateNodeConfig/updateNodePrompt
 * - 校验操作：validatePipeline（空、缺触发、缺输出、环检测）
 * - 清空/加载示例
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

function createStore() {
  setActivePinia(createPinia())
  return usePipelineEditorStore()
}

describe('pipelineEditor — 状态初始化', () => {
  it('初始状态各项应有正确默认值', () => {
    const store = createStore()
    expect(store.pipelineNodes).toEqual([])
    expect(store.connections).toEqual([])
    expect(store.selectedNodeId).toBeNull()
    expect(store.configDirty).toBe(false)
    expect(store.zoomLevel).toBe(100)
    expect(store.connectMode).toBe(false)
    expect(store.connectSource).toBeNull()
    expect(store.validationMessages).toEqual([])
    expect(store.isValid).toBe(true)
  })

  it('getters 初始值正确', () => {
    const store = createStore()
    expect(store.nodeCount).toBe(0)
    expect(store.connectionCount).toBe(0)
    expect(store.selectedNode).toBeNull()
  })
})

describe('pipelineEditor — 节点操作', () => {
  let store

  beforeEach(() => {
    store = createStore()
  })

  it('addNode 应添加新节点并自动编号 stepIndex', () => {
    const node = store.addNode('trigger', { x: 100, y: 280 })
    expect(node.type).toBe('trigger')
    expect(node.stepIndex).toBe(1)
    expect(store.nodeCount).toBe(1)
    expect(node.position.x).toBe(100)
    expect(node.position.y % 8).toBe(0) // 8px 对齐
  })

  it('addNode 应累加 stepIndex', () => {
    store.addNode('trigger', { x: 0, y: 0 })
    store.addNode('llm', { x: 0, y: 0 })
    store.addNode('guard', { x: 0, y: 0 })
    expect(store.nodeCount).toBe(3)
    expect(store.pipelineNodes[0].stepIndex).toBe(1)
    expect(store.pipelineNodes[1].stepIndex).toBe(2)
    expect(store.pipelineNodes[2].stepIndex).toBe(3)
  })

  it('removeNode 应移除节点及关联连线', () => {
    const n1 = store.addNode('trigger', { x: 0, y: 0 })
    const n2 = store.addNode('llm', { x: 100, y: 0 })
    store.startConnect(n1.id)
    store.completeConnect(n2.id)
    expect(store.connectionCount).toBe(1)
    store.removeNode(n1.id)
    expect(store.nodeCount).toBe(1)
    expect(store.connectionCount).toBe(0) // 关联连线也被清理
  })

  it('removeNode 应清空选中状态', () => {
    const n = store.addNode('trigger', { x: 0, y: 0 })
    store.selectNode(n.id)
    expect(store.selectedNodeId).toBe(n.id)
    store.removeNode(n.id)
    expect(store.selectedNodeId).toBeNull()
  })

  it('moveNode 应移动节点 y 坐标自动 8px 对齐', () => {
    const n = store.addNode('trigger', { x: 0, y: 0 })
    store.moveNode(n.id, { x: 50, y: 55 })
    const moved = store.pipelineNodes[0]
    expect(moved.position.x).toBe(50)
    expect(moved.position.y).toBe(56) // 55 → syncTo8px = 56
    expect(moved.position.y % 8).toBe(0)
  })

  it('selectNode 应正确选中/取消选中', () => {
    const n1 = store.addNode('trigger', { x: 0, y: 0 })
    const n2 = store.addNode('llm', { x: 100, y: 0 })
    store.selectNode(n1.id)
    expect(store.selectedNodeId).toBe(n1.id)
    expect(store.pipelineNodes[0].selected).toBe(true)
    expect(store.pipelineNodes[1].selected).toBe(false)
    store.selectNode(n2.id)
    expect(store.selectedNodeId).toBe(n2.id)
    expect(store.pipelineNodes[0].selected).toBe(false)
    expect(store.pipelineNodes[1].selected).toBe(true)
    store.selectNode(null)
    expect(store.selectedNodeId).toBeNull()
  })

  it('selectedNode getter 应返回当前选中节点', () => {
    expect(store.selectedNode).toBeNull()
    const n = store.addNode('trigger', { x: 0, y: 0 })
    store.selectNode(n.id)
    expect(store.selectedNode).not.toBeNull()
    expect(store.selectedNode.id).toBe(n.id)
    expect(store.selectedNode.type).toBe('trigger')
  })
})

describe('pipelineEditor — 连线操作', () => {
  let store, n1, n2, n3

  beforeEach(() => {
    store = createStore()
    n1 = store.addNode('trigger', { x: 0, y: 0 })
    n2 = store.addNode('llm', { x: 100, y: 0 })
    n3 = store.addNode('guard', { x: 200, y: 120 }) // 不同轨道
  })

  it('正常完成连线应创建一条连线', () => {
    store.startConnect(n1.id)
    expect(store.connectMode).toBe(true)
    expect(store.connectSource).toBe(n1.id)
    store.completeConnect(n2.id)
    expect(store.connectMode).toBe(false)
    expect(store.connectionCount).toBe(1)
    expect(store.connections[0].sourceId).toBe(n1.id)
    expect(store.connections[0].targetId).toBe(n2.id)
  })

  it('跨轨道连线应标记 isCrossTrack=true', () => {
    store.startConnect(n1.id)
    store.completeConnect(n3.id)
    expect(store.connectionCount).toBe(1)
    expect(store.connections[0].isCrossTrack).toBe(true)
  })

  it('同轨道连线应标记 isCrossTrack=false', () => {
    store.startConnect(n1.id)
    store.completeConnect(n2.id) // 同为 track=0
    expect(store.connections[0].isCrossTrack).toBe(false)
  })

  it('自连接应被忽略', () => {
    store.startConnect(n1.id)
    store.completeConnect(n1.id)
    expect(store.connectionCount).toBe(0)
  })

  it('重复连线应被忽略', () => {
    store.startConnect(n1.id)
    store.completeConnect(n2.id)
    store.startConnect(n1.id)
    store.completeConnect(n2.id)
    expect(store.connectionCount).toBe(1) // 仍只有 1 条
  })

  it('空源完成连线应自动取消', () => {
    store.completeConnect(n2.id) // 没有 startConnect
    expect(store.connectMode).toBe(false)
    expect(store.connectionCount).toBe(0)
  })

  it('cancelConnect 应退出连线模式', () => {
    store.startConnect(n1.id)
    store.cancelConnect()
    expect(store.connectMode).toBe(false)
    expect(store.connectSource).toBeNull()
  })

  it('removeConnection 应移除指定连线', () => {
    store.startConnect(n1.id)
    store.completeConnect(n2.id)
    expect(store.connectionCount).toBe(1)
    store.removeConnection(n1.id, n2.id)
    expect(store.connectionCount).toBe(0)
  })
})

describe('pipelineEditor — 配置操作', () => {
  let store

  beforeEach(() => {
    store = createStore()
  })

  it('updateNodeConfig 应合并补丁并标记 dirty', () => {
    const n = store.addNode('hitl', { x: 0, y: 0 })
    expect(store.configDirty).toBe(false)
    store.updateNodeConfig(n.id, { timeout: '24h', role: 'analyst' })
    expect(store.pipelineNodes[0].config.timeout).toBe('24h')
    expect(store.pipelineNodes[0].config.role).toBe('analyst')
    expect(store.configDirty).toBe(true)

    store.updateNodeConfig(n.id, { timeout: '48h' })
    expect(store.pipelineNodes[0].config.timeout).toBe('48h')
    expect(store.pipelineNodes[0].config.role).toBe('analyst') // 未覆盖的保留
  })

  it('updateNodePrompt 应更新提示词并标记 dirty', () => {
    const n = store.addNode('llm', { x: 0, y: 0 })
    store.updateNodePrompt(n.id, '系统提示词')
    expect(store.pipelineNodes[0].prompt).toBe('系统提示词')
    expect(store.configDirty).toBe(true)
  })
})

describe('pipelineEditor — 校验操作', () => {
  let store

  beforeEach(() => {
    store = createStore()
  })

  it('空管道应校验失败', () => {
    store.validatePipeline()
    expect(store.isValid).toBe(false)
    expect(store.validationMessages[0]).toContain('为空')
  })

  it('缺触发器应校验失败', () => {
    store.addNode('llm', { x: 0, y: 0 })
    store.addNode('output', { x: 100, y: 0 })
    store.validatePipeline()
    expect(store.isValid).toBe(false)
    expect(store.validationMessages.some(m => m.includes('触发器'))).toBe(true)
  })

  it('缺输出应校验失败', () => {
    store.addNode('trigger', { x: 0, y: 0 })
    store.addNode('llm', { x: 100, y: 0 })
    store.validatePipeline()
    expect(store.isValid).toBe(false)
    expect(store.validationMessages.some(m => m.includes('输出'))).toBe(true)
  })

  it('完整管道应校验通过', () => {
    const nodes = [
      store.addNode('trigger', { x: 0, y: 0 }),
      store.addNode('llm', { x: 100, y: 0 }),
      store.addNode('output', { x: 200, y: 0 }),
    ]
    store.startConnect(nodes[0].id)
    store.completeConnect(nodes[1].id)
    store.startConnect(nodes[1].id)
    store.completeConnect(nodes[2].id)
    store.validatePipeline()
    expect(store.isValid).toBe(true)
    expect(store.validationMessages.some(m => m.includes('通过'))).toBe(true)
  })

  it('循环依赖应校验失败', () => {
    const nodes = [
      store.addNode('trigger', { x: 0, y: 0 }),
      store.addNode('llm', { x: 100, y: 0 }),
      store.addNode('output', { x: 200, y: 0 }),
    ]
    // A→B→C→A 成环
    store.startConnect(nodes[0].id)
    store.completeConnect(nodes[1].id)
    store.startConnect(nodes[1].id)
    store.completeConnect(nodes[2].id)
    store.startConnect(nodes[2].id)
    store.completeConnect(nodes[0].id)
    store.validatePipeline()
    expect(store.isValid).toBe(false)
    expect(store.validationMessages.some(m => m.includes('循环') || m.includes('环'))).toBe(true)
  })
})

describe('pipelineEditor — 清空与加载', () => {
  let store

  beforeEach(() => {
    store = createStore()
  })

  it('clearCanvas 应清空所有状态', () => {
    store.addNode('trigger', { x: 0, y: 0 })
    store.addNode('llm', { x: 100, y: 0 })
    store.configDirty = true
    store.isValid = false
    store.clearCanvas()
    expect(store.nodeCount).toBe(0)
    expect(store.connectionCount).toBe(0)
    expect(store.selectedNodeId).toBeNull()
    expect(store.configDirty).toBe(false)
    expect(store.isValid).toBe(true)
    expect(store.validationMessages).toEqual([])
    expect(store.connectMode).toBe(false)
  })

  it('loadSample 应加载 7 个节点 + 6 条连线', () => {
    store.loadSample()
    expect(store.nodeCount).toBe(7)
    expect(store.connectionCount).toBe(6)
    // 验证节点类型
    const types = store.pipelineNodes.map(n => n.type)
    expect(types).toContain('trigger')
    expect(types).toContain('llm')
    expect(types).toContain('guard')
    expect(types).toContain('hitl')
    expect(types).toContain('action')
    expect(types).toContain('output')
    // 验证 badgeText
    expect(store.pipelineNodes[0].badgeText).toBe('事件驱动')
    expect(store.pipelineNodes[3].badgeText).toBe('高危')
    // 验证跨轨道连线
    const crossConns = store.connections.filter(c => c.isCrossTrack)
    expect(crossConns.length).toBeGreaterThanOrEqual(2)
  })
})
