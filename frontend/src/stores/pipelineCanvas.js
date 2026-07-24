/**
 * 流水线 DAG 画布 Store（M3）。
 *
 * 职责（port demo usePipelineStore）：
 *   - 维护 DAG 节点/边（nodes / edges）
 *   - 图级校验：Kahn 环检测 + 必须含 guardrail/hitl 节点（UX 前置）
 *   - 经 agentApi.pipeline 调用真实接口层（validate/run/getSample），后端就绪零改动
 *
 * 设计依据：01-api-spec.md §3 / Q3 / T11。
 * 说明：当前真实 pipeline 接口层为 PipelineEngine 空壳（R1），run 仅返回 run_id；
 *       运行态进度待 M1 后端收敛到 Orchestrator 后由 SSE 驱动。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'
import { NODE_TYPE_LABELS, NODE_TYPE_COLOR } from '@/constants/agentLabels'

let nodeSeq = 0
function nextNodeId() {
  nodeSeq += 1
  return `n-custom-${Date.now().toString(36)}-${nodeSeq}`
}

export const usePipelineCanvasStore = defineStore('pipelineCanvas', () => {
  // ===== 状态 =====
  const nodes = ref([]) // PipelineNode[]
  const edges = ref([]) // PipelineEdge[]（{source, target}）
  const validation = ref({ valid: true, warnings: [], errors: [] })
  const submitting = ref(false)
  const running = ref(false)
  const currentRunId = ref(null)

  // ===== 派生 =====
  const nodeCount = computed(() => nodes.value.length)
  const edgeCount = computed(() => edges.value.length)
  const hasGuardrail = computed(() => nodes.value.some((n) => n.type === 'guardrail'))
  const hasHitl = computed(() => nodes.value.some((n) => n.type === 'hitl'))

  /** 转为 GraphPanel 兼容节点（带 x/y/type 映射） */
  const graphNodes = computed(() =>
    nodes.value.map((n) => ({
      id: n.node_id,
      type: n.type,
      label: n.label || NODE_TYPE_LABELS[n.type] || n.node_id,
      x: (n.position && n.position.x) || 0,
      y: (n.position && n.position.y) || 0,
      properties: n.config || {},
      _nodeType: n.type,
    }))
  )
  /** 转为 GraphPanel 兼容边（补 id） */
  const graphEdges = computed(() =>
    edges.value.map((e) => ({
      id: `e-${e.source}--${e.target}`,
      source: e.source,
      target: e.target,
    }))
  )

  // ===== 图级校验 =====
  /**
   * Kahn 拓扑排序环检测 + 必须含 guardrail/hitl 节点。
   * @returns {{valid:boolean, warnings:string[], errors:string[]}}
   */
  function validateGraph() {
    const errors = []
    const warnings = []
    const nodeIds = nodes.value.map((n) => n.node_id)

    // 1. 环检测（Kahn）
    const indeg = new Map(nodeIds.map((id) => [id, 0]))
    edges.value.forEach((e) => {
      if (indeg.has(e.target)) indeg.set(e.target, indeg.get(e.target) + 1)
    })
    const queue = nodeIds.filter((id) => (indeg.get(id) || 0) === 0)
    let visited = 0
    const adj = new Map(nodeIds.map((id) => [id, []]))
    edges.value.forEach((e) => {
      if (adj.has(e.source)) adj.get(e.source).push(e.target)
    })
    while (queue.length) {
      const cur = queue.shift()
      visited += 1
      ;(adj.get(cur) || []).forEach((nb) => {
        indeg.set(nb, indeg.get(nb) - 1)
        if (indeg.get(nb) === 0) queue.push(nb)
      })
    }
    if (visited < nodeIds.length) {
      errors.push('检测到环路（DAG 不允许循环依赖），请移除形成环的边。')
    }

    // 2. 必须含 guardrail / hitl 节点（安全前置，作为告警）
    if (!hasGuardrail.value) {
      warnings.push('建议包含「护栏」节点以在执行高危动作前做安全校验。')
    }
    if (!hasHitl.value) {
      warnings.push('建议包含「人工审核」节点以在处置动作前挂起等待审批。')
    }

    const result = { valid: errors.length === 0, warnings, errors }
    validation.value = result
    return result
  }

  // ===== 动作 =====
  /** 加载示例 DAG（种子来自 pipelineMock.getSample） */
  async function seedFromSample() {
    submitting.value = true
    try {
      const res = await agentApi.pipeline.getSample()
      const def = res.data || {}
      nodes.value = (def.nodes || []).map((n) => ({ ...n }))
      edges.value = (def.edges || []).map((e) => ({ ...e }))
      validateGraph()
      return def
    } finally {
      submitting.value = false
    }
  }

  /** 新增节点 */
  function addNode(type, position = { x: 200, y: 200 }, label) {
    const node = {
      node_id: nextNodeId(),
      type,
      label: label || NODE_TYPE_LABELS[type] || type,
      position: { x: Math.round(position.x), y: Math.round(position.y) },
      config: {},
    }
    nodes.value.push(node)
    return node
  }

  /** 移动节点 */
  function moveNode(nodeId, position) {
    const n = nodes.value.find((x) => x.node_id === nodeId)
    if (n) n.position = { x: Math.round(position.x), y: Math.round(position.y) }
  }

  /** 连接两节点（去重） */
  function connect(source, target) {
    if (source === target) return false
    const exists = edges.value.some((e) => e.source === source && e.target === target)
    if (exists) return false
    edges.value.push({ source, target })
    return true
  }

  /** 删除节点（及其相关边） */
  function removeNode(nodeId) {
    nodes.value = nodes.value.filter((n) => n.node_id !== nodeId)
    edges.value = edges.value.filter((e) => e.source !== nodeId && e.target !== nodeId)
  }

  /** 删除边 */
  function removeEdge(edgeId) {
    edges.value = edges.value.filter((e) => `e-${e.source}--${e.target}` !== edgeId)
  }

  /** 清空画布 */
  function clear() {
    nodes.value = []
    edges.value = []
    validation.value = { valid: true, warnings: [], errors: [] }
    running.value = false
    currentRunId.value = null
  }

  /**
   * 校验并启动编排（经 agentApi.pipeline.run 真实接口层）。
   * @param {string} eventId
   * @returns {Promise<{run_id:string}|null>}
   */
  async function run(eventId) {
    const v = validateGraph()
    if (!v.valid) return null
    submitting.value = true
    running.value = true
    try {
      // 节点类型即候选 agent 名（U4 假设：节点粒度 = agent 级）
      const agentNames = nodes.value.map((n) => n.type)
      const res = await agentApi.pipeline.run(eventId || 'SE-DEMO', agentNames, true)
      currentRunId.value = res.data && res.data.run_id ? res.data.run_id : null
      return res.data
    } finally {
      submitting.value = false
    }
  }

  return {
    // state
    nodes,
    edges,
    validation,
    submitting,
    running,
    currentRunId,
    // getters
    nodeCount,
    edgeCount,
    hasGuardrail,
    hasHitl,
    graphNodes,
    graphEdges,
    // actions
    validateGraph,
    seedFromSample,
    addNode,
    moveNode,
    connect,
    removeNode,
    removeEdge,
    clear,
    run,
  }
})
