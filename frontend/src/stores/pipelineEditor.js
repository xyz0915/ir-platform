/**
 * pipelineEditor — 工作流编排画布状态管理
 *
 * 职责：管理画布上的节点列表、连线列表、选中状态、缩放等级、
 * 连线模式、校验状态等全部画布运行时状态。
 *
 * 采用 Pinia setup function 风格，与 project 现有 stores 一致。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { createNodeData, syncTo8px, flattenVariables, NodeType } from '@/constants/pipelineTypes'

export const usePipelineEditorStore = defineStore('pipelineEditor', () => {
  // ==========================================================================
  // State
  // ==========================================================================

  /** 画布上所有节点。 */
  const pipelineNodes = ref([])

  /** 连线列表，每项 { sourceId, targetId, isCrossTrack }。 */
  const connections = ref([])

  /** 当前选中节点的 ID（TODO: 多选支持 future — 改为 selectedNodeIds Set<string>）。 */
  const selectedNodeId = ref(null)

  /** 配置是否被更改但未保存。 */
  const configDirty = ref(false)

  /** 缩放百分比（50–200）。 */
  const zoomLevel = ref(100)

  /** 是否处于连线模式（等待点击目标节点）。 */
  const connectMode = ref(false)

  /** 连线模式的源节点 ID。 */
  const connectSource = ref(null)

  /** 校验结果消息列表。 */
  const validationMessages = ref([])

  /** 校验是否通过。 */
  const isValid = ref(true)

  /** 运行加载状态。 */
  const runLoading = ref(false)

  /** 最近一次运行的 run_id。 */
  const lastRunId = ref(null)

  /** 当前选中连线的索引。 */
  const selectedConnectionId = ref(null)

  /** 管道名称（用于动态标题/面包屑）。 */
  const pipelineName = ref('')

  // ==========================================================================
  // Phase 3 · 调试面板状态
  // ==========================================================================

  /** 调试面板开关。 */
  const debugMode = ref(false)

  /** 节点运行态：{ [nodeId]: 'idle'|'running'|'success'|'failed' }。 */
  const nodeRunStatus = ref({})

  /** 调试草稿：{ [nodeId]: { input_params, context_vars, mode } }（不污染画布 config）。 */
  const debugDraft = ref({})

  /** 分支选择：{ [nodeId]: chosenBranchLabel }。 */
  const branchSelection = ref({})

  /** 分支路径结果：{ activeNodes:Set|null, prunedEdges:[{sourceId,targetId}] }。 */
  const branchPath = ref({ activeNodes: null, prunedEdges: [] })

  /** 当前选中节点最近一次执行结果（回显）。 */
  const activeNodeRun = ref(null)

  /** 当前节点历史列表（来自 getNodeRuns）。 */
  const nodeRunHistory = ref([])

  // ==========================================================================
  // Getters
  // ==========================================================================

  /** 当前选中的节点对象。 */
  const selectedNode = computed(() =>
    pipelineNodes.value.find(n => n.id === selectedNodeId.value) || null,
  )

  /** 节点数量。 */
  const nodeCount = computed(() => pipelineNodes.value.length)

  /** 连线数量。 */
  const connectionCount = computed(() => connections.value.length)

  // ==========================================================================
  // Actions — 节点操作
  // ==========================================================================

  /**
   * 在画布上添加一个新节点。
   * @param {string} type — NodeType 值
   * @param {{x: number, y: number}} position — 画布坐标
   * @param {string} [name] — 可选的自定义名称
   * @returns {object} 新建的节点数据
   */
  function addNode(type, position, name) {
    const node = createNodeData(type, position, name)
    node.stepIndex = pipelineNodes.value.length + 1
    pipelineNodes.value.push(node)
    return node
  }

  /**
   * 从画布移除指定节点及其所有关联连线。
   * @param {string} nodeId — 要移除的节点 ID
   */
  function removeNode(nodeId) {
    pipelineNodes.value = pipelineNodes.value.filter(n => n.id !== nodeId)
    connections.value = connections.value.filter(
      c => c.sourceId !== nodeId && c.targetId !== nodeId,
    )
    if (selectedNodeId.value === nodeId) {
      selectedNodeId.value = null
    }
  }

  /**
   * 移动节点到新位置（y 自动 8px 对齐）。
   * @param {string} nodeId
   * @param {{x: number, y: number}} position
   */
  function moveNode(nodeId, position) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (node) {
      node.position.x = position.x
      node.position.y = syncTo8px(position.y)
    }
  }

  /**
   * 选中/取消选中某个节点。
   * @param {string|null} nodeId — 节点 ID（null 表示取消选中）
   */
  function selectNode(nodeId) {
    pipelineNodes.value.forEach(n => { n.selected = false })
    selectedNodeId.value = nodeId
    if (nodeId) {
      const node = pipelineNodes.value.find(n => n.id === nodeId)
      if (node) node.selected = true
    }
  }

  // ==========================================================================
  // Actions — 连接操作
  // ==========================================================================

  /**
   * 进入连线模式，标记连线起点。
   * @param {string} sourceId — 源节点 ID
   */
  function startConnect(sourceId) {
    connectMode.value = true
    connectSource.value = sourceId
  }

  /**
   * 完成连线。
   * @param {string} targetId — 目标节点 ID
   */
  function completeConnect(targetId) {
    if (!connectSource.value) {
      cancelConnect()
      return
    }
    if (connectSource.value === targetId) {
      cancelConnect()
      return
    }
    // 检查重复连线
    const exists = connections.value.some(
      c => c.sourceId === connectSource.value && c.targetId === targetId,
    )
    if (!exists) {
      const sourceNode = pipelineNodes.value.find(n => n.id === connectSource.value)
      const targetNode = pipelineNodes.value.find(n => n.id === targetId)
      const isCrossTrack = sourceNode && targetNode && sourceNode.track !== targetNode.track
      connections.value.push({
        sourceId: connectSource.value,
        targetId,
        isCrossTrack: !!isCrossTrack,
      })
    }
    cancelConnect()
  }

  /**
   * 取消连线模式。
   */
  function cancelConnect() {
    connectMode.value = false
    connectSource.value = null
  }

  /**
   * 移除指定连线。
   * @param {string} sourceId
   * @param {string} targetId
   */
  function removeConnection(sourceId, targetId) {
    connections.value = connections.value.filter(
      c => !(c.sourceId === sourceId && c.targetId === targetId),
    )
  }

  /**
   * 选中一条连线（按索引）。
   * @param {number} index — 连线在 connections 数组中的索引
   */
  function selectConnection(index) {
    selectedConnectionId.value = index
    // 同时取消所有节点选中
    pipelineNodes.value.forEach(n => { n.selected = false })
    selectedNodeId.value = null
  }

  /**
   * 按索引移除连线。
   * @param {number} index — 连线在 connections 数组中的索引
   */
  function removeConnectionByIndex(index) {
    connections.value.splice(index, 1)
    selectedConnectionId.value = null
    configDirty.value = true
  }

  /**
   * 获取当前画布的快照数据（用于保存/发布）。
   * @returns {object} { nodes, connections }
   */
  function getPipelineSnapshot() {
    return {
      nodes: JSON.parse(JSON.stringify(pipelineNodes.value)),
      connections: JSON.parse(JSON.stringify(connections.value)),
    }
  }

  /**
   * 更新当前选中节点的单个配置字段。
   * @param {string} field — 配置字段名
   * @param {any} value — 新值
   */
  function updateSelectedNodeConfig(field, value) {
    if (selectedNodeId.value) {
      updateNodeConfig(selectedNodeId.value, { [field]: value })
    }
  }

  // ==========================================================================
  // Actions — 配置操作
  // ==========================================================================

  /**
   * 更新指定节点的配置（局部补丁）。
   * @param {string} nodeId
   * @param {object} configPatch — 要合并到 config 的字段
   */
  function updateNodeConfig(nodeId, configPatch) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (node) {
      Object.assign(node.config, configPatch)
      configDirty.value = true
    }
  }

  /**
   * 更新指定节点的系统提示词。
   * @param {string} nodeId
   * @param {string} prompt
   */
  function updateNodePrompt(nodeId, prompt) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (node) {
      node.prompt = prompt
      configDirty.value = true
    }
  }

  // ==========================================================================
  // Actions — 工具管理 (C3)
  // ==========================================================================

  /**
   * 为指定节点添加一个工具。
   * @param {string} nodeId
   * @param {object} tool — { name, endpoint, schema }
   */
  function addNodeTool(nodeId, tool) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (node) {
      if (!node.tools) node.tools = []
      node.tools.push(tool)
      configDirty.value = true
    }
  }

  /**
   * 移除指定节点的指定工具。
   * @param {string} nodeId
   * @param {number} index — 工具在 tools 数组中的索引
   */
  function removeNodeTool(nodeId, index) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (node && node.tools) {
      node.tools.splice(index, 1)
      configDirty.value = true
    }
  }

  // ==========================================================================
  // Actions — 变量管理 (C4)
  // ==========================================================================

  /**
   * 为指定节点添加一个变量。
   * @param {string} nodeId
   * @param {object} variable — { key, value }
   */
  function addNodeVariable(nodeId, variable) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (node) {
      if (!node.variables) node.variables = []
      node.variables.push(variable)
      configDirty.value = true
    }
  }

  /**
   * 移除指定节点的指定变量。
   * @param {string} nodeId
   * @param {number} index — 变量在 variables 数组中的索引
   */
  function removeNodeVariable(nodeId, index) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (node && node.variables) {
      node.variables.splice(index, 1)
      configDirty.value = true
    }
  }

  // ==========================================================================
  // Actions — 校验 & 运行
  // ==========================================================================

  /**
   * 校验管道的合法性。
   * 使用 Kahn 拓扑排序检测环，同时检查基本规则。
   */
  function validatePipeline() {
    const messages = []
    let valid = true

    if (pipelineNodes.value.length === 0) {
      messages.push('管道为空，请添加至少一个节点')
      valid = false
      validationMessages.value = messages
      isValid.value = valid
      return
    }

    // 检查是否有 TRIGGER 节点
    const hasTrigger = pipelineNodes.value.some(n => n.type === 'trigger')
    if (!hasTrigger) {
      messages.push('管道缺少触发器节点（trigger）')
      valid = false
    }

    // 检查是否有 OUTPUT 节点
    const hasOutput = pipelineNodes.value.some(n => n.type === 'output')
    if (!hasOutput) {
      messages.push('管道缺少输出节点（output）')
      valid = false
    }

    // Kahn 拓扑排序检测环
    const nodeIds = pipelineNodes.value.map(n => n.id)
    const adjList = new Map()
    const inDegree = new Map()

    nodeIds.forEach(id => {
      adjList.set(id, [])
      inDegree.set(id, 0)
    })

    connections.value.forEach(c => {
      if (adjList.has(c.sourceId) && adjList.has(c.targetId)) {
        adjList.get(c.sourceId).push(c.targetId)
        inDegree.set(c.targetId, (inDegree.get(c.targetId) || 0) + 1)
      }
    })

    const queue = []
    inDegree.forEach((degree, id) => {
      if (degree === 0) queue.push(id)
    })

    let visitedCount = 0
    const visitedNodes = new Set()
    while (queue.length > 0) {
      const current = queue.shift()
      visitedNodes.add(current)
      visitedCount++
      const neighbors = adjList.get(current) || []
      neighbors.forEach(neighbor => {
        const newDegree = (inDegree.get(neighbor) || 0) - 1
        inDegree.set(neighbor, newDegree)
        if (newDegree === 0) queue.push(neighbor)
      })
    }

    if (visitedCount !== nodeIds.length) {
      messages.push('检测到循环依赖，请检查连线')
      valid = false
      // 标记环中未访问的节点
      pipelineNodes.value.forEach(n => {
        n.validationError = !visitedNodes.has(n.id)
      })
    } else {
      pipelineNodes.value.forEach(n => { n.validationError = false })
    }

    if (valid && messages.length === 0) {
      messages.push('管道校验通过')
    }

    validationMessages.value = messages
    isValid.value = valid
  }

  /**
   * 运行当前管道。
   * @param {string} eventId — 事件 ID
   * @returns {Promise<object>} 运行结果
   */
  async function runPipeline(eventId) {
    // 先校验
    validatePipeline()
    if (!isValid.value) {
      throw new Error('管道校验未通过，请先修正问题')
    }
    runLoading.value = true
    try {
      const { default: agentApi } = await import('@/api/agent')
      const names = pipelineNodes.value.map(n => n.name)
      const res = await agentApi.pipeline.run(eventId, names, true)
      lastRunId.value = res.data?.run_id || null
      return res.data
    } finally {
      runLoading.value = false
    }
  }

  /**
   * 清空画布所有节点和连线。
   */
  function clearCanvas() {
    pipelineNodes.value = []
    connections.value = []
    selectedNodeId.value = null
    connectMode.value = false
    connectSource.value = null
    validationMessages.value = []
    isValid.value = true
    configDirty.value = false
  }

  /**
   * 加载示例数据到画布。
   */
  function loadSample() {
    clearCanvas()
    const nodes = [
      addNode('trigger', { x: 100, y: 280 }, '触发器'),
      addNode('llm', { x: 360, y: 280 }, '初步调查'),
      addNode('llm', { x: 700, y: 280 }, '根因定位'),
      addNode('guard', { x: 680, y: 400 }, '护栏校验'),
      addNode('hitl', { x: 920, y: 400 }, '人工审批'),
      addNode('action', { x: 1120, y: 280 }, '处置执行'),
      addNode('output', { x: 1380, y: 280 }, '报告输出'),
    ]
    nodes[0].badgeText = '事件驱动'
    nodes[0].statText = '告警入站 · 1 条规则'
    nodes[1].badgeText = 'triage_agent'
    nodes[1].statText = '3 数据源 · 2 工具'
    nodes[2].badgeText = 'root_cause'
    nodes[2].statText = '综合分析 4 路 Agent 输出'
    nodes[3].badgeText = '高危'
    nodes[3].statText = '5 条策略命中 · 需 HITL'
    nodes[4].badgeText = '待审批'
    nodes[4].statText = '超时 24h · 必填意见'
    nodes[5].badgeText = '隔离主机'
    nodes[5].statText = '回滚方案: ACL 自动恢复'
    nodes[6].badgeText = 'Markdown'
    nodes[6].statText = '存储至案件库'

    // 连线
    const conns = [
      { source: nodes[0].id, target: nodes[1].id },
      { source: nodes[1].id, target: nodes[2].id },
      { source: nodes[2].id, target: nodes[3].id, cross: true },
      { source: nodes[3].id, target: nodes[4].id },
      { source: nodes[4].id, target: nodes[5].id, cross: true },
      { source: nodes[5].id, target: nodes[6].id },
    ]
    conns.forEach(c => {
      connections.value.push({
        sourceId: c.source,
        targetId: c.target,
        isCrossTrack: !!c.cross,
      })
    })
  }

  // ==========================================================================
  // Actions — 预设加载 (H2)
  // ==========================================================================

  /**
   * 加载预设到画布。
   * 兼容两种后端格式：
   * - { nodes: [...] } — 完整节点对象（前端标准）
   * - { agents: [...] } — 后端当前存储的字符串数组（Agent/Runner 名称）
   *
   * 对于 agents 格式，会自动按顺序排列节点并串联连线。
   *
   * @param {object} preset — 预设数据
   */
  function loadPreset(preset) {
    clearCanvas()
    if (preset.nodes && Array.isArray(preset.nodes)) {
      preset.nodes.forEach(nodeData => {
        const node = addNode(nodeData.type, nodeData.position, nodeData.name)
        // 复制额外属性
        Object.assign(node, nodeData, { id: node.id, stepIndex: node.stepIndex })
      })
    } else if (preset.agents && Array.isArray(preset.agents)) {
      // 兼容后端以 agents 字符串数组存储的预设
      const validTypes = Object.values(NodeType)
      const aliasMap = {
        triage: NodeType.TRIGGER,
        process: NodeType.PROCESS_ANALYSIS,
        reporter: NodeType.OUTPUT,
        responder: NodeType.ACTION,
        investigator: NodeType.LLM,
      }
      const nodes = []
      preset.agents.forEach((agent, idx) => {
        let type = agent
        if (!validTypes.includes(type)) {
          type = aliasMap[agent] || NodeType.LLM
        }
        const x = 100 + idx * 260
        const y = idx % 2 === 0 ? 280 : 360
        const node = addNode(type, { x, y }, agent)
        nodes.push(node)
      })
      // 自动串联成流水线
      nodes.forEach((node, idx) => {
        if (idx > 0) {
          const prev = nodes[idx - 1]
          connections.value.push({
            sourceId: prev.id,
            targetId: node.id,
            isCrossTrack: prev.track !== node.track,
          })
        }
      })
    }
    if (preset.pipelineName || preset.name) {
      pipelineName.value = preset.pipelineName || preset.name
    }
    configDirty.value = false
  }

  // ==========================================================================
  // Actions — 节点复制 (M4)
  // ==========================================================================

  /**
   * 复制指定节点（深拷贝 + 位置偏移）。
   * @param {string} nodeId — 要复制的节点 ID
   * @returns {object|null} 复制的节点
   */
  function duplicateNode(nodeId) {
    const source = pipelineNodes.value.find(n => n.id === nodeId)
    if (!source) return null
    const pos = {
      x: source.position.x + 30,
      y: source.position.y + 30,
    }
    const newNode = addNode(source.type, pos, source.name + ' (副本)')
    // 复制额外属性
    Object.assign(newNode, {
      badgeText: source.badgeText,
      statText: source.statText,
      config: JSON.parse(JSON.stringify(source.config)),
      prompt: source.prompt || '',
      tools: source.tools ? JSON.parse(JSON.stringify(source.tools)) : [],
      variables: source.variables ? JSON.parse(JSON.stringify(source.variables)) : [],
    })
    return newNode
  }

  // ==========================================================================
  // Actions — Phase 3 调试面板
  // ==========================================================================

  /** 切换调试面板开关。 */
  function toggleDebug() {
    debugMode.value = !debugMode.value
    if (!debugMode.value) {
      // 关闭时复位分支路径高亮，避免残留
      branchPath.value = { activeNodes: null, prunedEdges: [] }
    }
  }

  /** 打开调试面板（可选指定节点）。 */
  function openDebug(nodeId) {
    debugMode.value = true
    if (nodeId) selectNode(nodeId)
  }

  /** 关闭调试面板。 */
  function closeDebug() {
    debugMode.value = false
    branchPath.value = { activeNodes: null, prunedEdges: [] }
  }

  /** 确保某节点有调试草稿（无则以其 variables 生成 context_vars）。 */
  function ensureDebugDraft(nodeId) {
    if (debugDraft.value[nodeId]) return debugDraft.value[nodeId]
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    const draft = {
      input_params: {},
      context_vars: node ? flattenVariables(node.variables) : {},
      mode: 'real',
    }
    debugDraft.value = { ...debugDraft.value, [nodeId]: draft }
    return draft
  }

  /** 设置节点运行态。 */
  function setNodeRunStatus(nodeId, status) {
    nodeRunStatus.value = { ...nodeRunStatus.value, [nodeId]: status }
  }

  /** 清除节点运行态。 */
  function clearNodeRunStatus(nodeId) {
    const next = { ...nodeRunStatus.value }
    delete next[nodeId]
    nodeRunStatus.value = next
  }

  /** 保存调试草稿（不触 configDirty）。 */
  function saveDebugDraft(nodeId, draft) {
    if (!nodeId) return
    debugDraft.value = { ...debugDraft.value, [nodeId]: { ...draft } }
  }

  /**
   * 执行单节点调试。
   * 组装 payload（节点 variables 展平为 context_vars）→ 调 facade → 置 nodeRunStatus → 存 activeNodeRun → 刷新历史。
   * @param {string} nodeId
   */
  async function runNodeDebug(nodeId) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (!node) return null
    const draft = ensureDebugDraft(nodeId)
    setNodeRunStatus(nodeId, 'running')
    try {
      const { default: agentApi } = await import('@/api/agent')
      const payload = {
        node_type: node.type,
        node_name: node.name,
        input_params: draft.input_params || {},
        context_vars: draft.context_vars || flattenVariables(node.variables),
        mode: draft.mode || 'real',
      }
      const res = await agentApi.pipeline.runNode(payload)
      const data = res?.data ?? res ?? {}
      const status = data.status === 'success' ? 'success' : 'failed'
      setNodeRunStatus(nodeId, status)
      activeNodeRun.value = data
      await loadNodeRuns(nodeId)
      return data
    } catch (e) {
      setNodeRunStatus(nodeId, 'failed')
      activeNodeRun.value = {
        status: 'failed',
        error: e?.message || String(e),
        node_type: node.type,
        node_name: node.name,
      }
      return null
    }
  }

  /**
   * 分支模拟：组装 connections + chosen_branch → 调 simulateBranch → 存 branchSelection + branchPath。
   * @param {string} nodeId
   */
  async function runBranchSim(nodeId) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (!node || node.type !== NodeType.BRANCH) return null
    const chosen = branchSelection.value[nodeId]
      || (node.config?.branches?.[0]?.label)
    try {
      const { default: agentApi } = await import('@/api/agent')
      const payload = {
        node_name: node.name,
        branches: node.config?.branches || [],
        chosen_branch: chosen,
        connections: connections.value,
      }
      const res = await agentApi.pipeline.simulateBranch(payload)
      const data = res?.data ?? res ?? {}
      branchSelection.value = { ...branchSelection.value, [nodeId]: chosen }
      branchPath.value = {
        activeNodes: new Set(data.active_nodes || []),
        prunedEdges: data.pruned_edges || [],
      }
      return data
    } catch (e) {
      return null
    }
  }

  /**
   * 加载节点调试历史。
   * @param {string} nodeId
   */
  async function loadNodeRuns(nodeId) {
    const node = pipelineNodes.value.find(n => n.id === nodeId)
    if (!node) { nodeRunHistory.value = []; return [] }
    try {
      const { default: agentApi } = await import('@/api/agent')
      const res = await agentApi.pipeline.getNodeRuns({ node_name: node.name })
      const items = (res?.data?.items) || res?.items || []
      nodeRunHistory.value = items
      return items
    } catch (e) {
      nodeRunHistory.value = []
      return []
    }
  }

  /**
   * 应用分支选择（更新选择并触发 runBranchSim）。
   * @param {string} nodeId
   * @param {string} label — 所选分支 label
   */
  function applyBranchSelection(nodeId, label) {
    branchSelection.value = { ...branchSelection.value, [nodeId]: label }
    runBranchSim(nodeId)
  }

  // ==========================================================================
  // Expose
  // ==========================================================================

  return {
    // state
    pipelineNodes,
    connections,
    selectedNodeId,
    configDirty,
    zoomLevel,
    connectMode,
    connectSource,
    validationMessages,
    isValid,
    // new states
    runLoading,
    lastRunId,
    selectedConnectionId,
    pipelineName,
    // Phase 3 states
    debugMode,
    nodeRunStatus,
    debugDraft,
    branchSelection,
    branchPath,
    activeNodeRun,
    nodeRunHistory,
    // getters
    selectedNode,
    nodeCount,
    connectionCount,
    // actions
    addNode,
    removeNode,
    moveNode,
    selectNode,
    startConnect,
    completeConnect,
    cancelConnect,
    removeConnection,
    selectConnection,
    removeConnectionByIndex,
    getPipelineSnapshot,
    updateSelectedNodeConfig,
    updateNodeConfig,
    updateNodePrompt,
    addNodeTool,
    removeNodeTool,
    addNodeVariable,
    removeNodeVariable,
    validatePipeline,
    runPipeline,
    clearCanvas,
    loadSample,
    loadPreset,
    duplicateNode,
    // Phase 3 actions
    toggleDebug,
    openDebug,
    closeDebug,
    ensureDebugDraft,
    setNodeRunStatus,
    clearNodeRunStatus,
    saveDebugDraft,
    runNodeDebug,
    runBranchSim,
    loadNodeRuns,
    applyBranchSelection,
  }
})
