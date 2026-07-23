/**
 * useSSE — SSE 事件订阅 composable
 *
 * 封装浏览器原生 EventSource，提供响应式状态和自动重连。
 * 支持证据图谱构建（兼容 flat list 和 nested { data_sources, evidence } 格式）。
 */
import { ref, computed, onUnmounted } from 'vue'

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]

/**
 * 将 flat list 中的证据项转换为图谱节点格式
 * @param {Object} item - flat list 中的单个元素（如 { type: "process_events", ref: "...", process_name: "..." }）
 * @returns {Object|null} 图谱节点对象或 null
 */
function convertToNode(item) {
  if (!item || typeof item !== 'object') return null
  if (item.id && item.type) return item  // 已经是节点格式

  const rawType = item.type || 'action'
  let id = item.ref || item.id
  let label = id

  // 把后端 evidence type 归一化到我们识别的 5 种类型
  // normalized_logs → log
  // security_events / process_events / file_events → security/process/file
  // responder_action → action
  const type = (
    rawType === 'normalized_logs' ? 'log' :
    rawType === 'security_events' ? 'security' :
    rawType === 'process_events' ? 'process' :
    rawType === 'file_events' ? 'file' :
    rawType === 'responder_action' ? 'action' :
    rawType === 'network_connection' ? 'host' :  // 网络连接归到 host 类型
    rawType
  )

  if (type === 'process') {
    label = item.process_name || id
  } else if (type === 'log') {
    label = `Log#${(id.split('id=')[1]) || id}`
  } else if (type === 'security') {
    label = (id.split('id=')[1]) || id
  } else if (type === 'action') {
    label = item.ref || item.action || 'action'
  } else if (type === 'file') {
    label = item.file_name || id
  } else if (type === 'host') {
    label = `${item.local_addr || ''}:${item.local_port || ''}→${item.remote_addr || ''}` || id
  } else {
    label = id
  }

  return {
    id: id,
    type,
    label,
    properties: { ...item },
  }
}

/**
 * 解析 evidence 数据并构建图谱节点和边
 * 兼容两种格式：
 *   格式 1: { data_sources: [...], evidence: [...] }
 *   格式 2: [...] (flat list)
 *
 * @param {Object|Array} evidence - 证据数据
 * @param {Object} graphNodes - 图谱节点响应式数组
 * @param {Object} graphEdges - 图谱边响应式数组
 */
// 推断证据之间的关系并生成边
function inferEdges(nodes, graphEdges) {
  if (!nodes || nodes.length === 0) return
  const nodeMap = new Map(nodes.map(n => [n.id, n]))

  const addEdge = (source, target, relation, description) => {
    if (!source || !target || source === target) return
    if (!nodeMap.has(source) || !nodeMap.has(target)) return
    const edgeId = `${source}--${target}`
    if (!graphEdges.value.find(e => e.id === edgeId)) {
      graphEdges.value.push({
        id: edgeId,
        source,
        target,
        relation,
        description,
        directed: true,
      })
    }
  }

  // 1. process 之间的父进程关系（parent_name → process_name）
  const processNodes = nodes.filter(n => n.type === 'process')
  processNodes.forEach(child => {
    const parentName = child.properties?.parent_name
    if (parentName) {
      const parent = processNodes.find(p => p !== child && p.properties?.process_name === parentName)
      if (parent) addEdge(parent.id, child.id, '启动', '父进程')
    }
  })

  // 2. 同名进程横向关联（同一进程多个实例/PID）
  const byName = new Map()
  processNodes.forEach(n => {
    const name = n.properties?.process_name
    if (name) {
      if (!byName.has(name)) byName.set(name, [])
      byName.get(name).push(n)
    }
  })
  byName.forEach((list, name) => {
    if (list.length >= 2) {
      // 同一进程名连接成链
      for (let i = 0; i < list.length - 1; i++) {
        addEdge(list[i].id, list[i + 1].id, '关联', `同进程名 ${name}`)
      }
    }
  })

  // 3. responder_action → 第一个 security_event（响应处置）
  const actionNodes = nodes.filter(n => n.type === 'action')
  const eventNodes = nodes.filter(n => n.type === 'security' || n.type === 'host')
  if (actionNodes.length > 0 && eventNodes.length > 0) {
    const firstEvent = eventNodes[0]
    actionNodes.forEach(a => addEdge(a.id, firstEvent.id, '响应', '处置动作针对'))
  }

  // 4. 同一 event_type 的日志相连（同类事件）
  const logNodes = nodes.filter(n => n.type === 'log')
  const logsByType = new Map()
  logNodes.forEach(n => {
    const t = n.properties?.event_type
    if (t) {
      if (!logsByType.has(t)) logsByType.set(t, [])
      logsByType.get(t).push(n)
    }
  })
  logsByType.forEach((list, type) => {
    // 限制每类最多 5 条连线，避免图谱变蜘蛛网
    if (list.length >= 2 && list.length <= 8) {
      for (let i = 0; i < list.length - 1; i++) {
        addEdge(list[i].id, list[i + 1].id, '关联', `同类事件 ${type}`)
      }
    }
  })

  // 5. security_event/host → process/log（事件触发了相关进程和日志）
  //    关键的"下钻"边：没有它，process 全部平级、图谱只有 1 层
  eventNodes.forEach(evt => {
    // event → 前 5 个 process（"触发"）
    processNodes.slice(0, 5).forEach(p => addEdge(evt.id, p.id, '触发', '事件相关进程'))
    // event → 前 3 个 log（"伴随"）
    logNodes.slice(0, 3).forEach(l => addEdge(evt.id, l.id, '伴随', '事件相关日志'))
  })

  // 不再使用兜底中枢连线 — 径向布局本身已提供视觉层次
  // 大量节点连到中心反而形成蜘蛛网、难以阅读
}

function parseEvidenceForGraph(evidence, graphNodes, graphEdges) {
  if (!evidence) return

  let dataSources = []
  let evidenceList = []

  if (Array.isArray(evidence)) {
    // flat list 格式 — 转换为节点
    dataSources = evidence.map(item => convertToNode(item)).filter(Boolean)
  } else if (evidence.data_sources) {
    // 嵌套格式
    dataSources = evidence.data_sources
    evidenceList = evidence.evidence || []
  }

  // 添加节点
  dataSources.forEach(src => {
    if (src && src.id && !graphNodes.value.find(n => n.id === src.id)) {
      graphNodes.value.push({
        id: src.id,
        type: src.type || 'action',
        label: src.label || src.id,
        properties: src.properties || {},
        x: Math.random() * 600 + 50,
        y: Math.random() * 400 + 50,
      })
    }
  })

  // 添加边
  evidenceList.forEach(e => {
    if (e && e.source_id && e.target_id) {
      const edgeId = `${e.source_id}--${e.target_id}`
      if (!graphEdges.value.find(ed => ed.id === edgeId)) {
        graphEdges.value.push({
          id: edgeId,
          source: e.source_id,
          target: e.target_id,
          relation: e.relation || '关联',
          description: e.description || '',
          directed: true,
        })
      }
    }
  })

  // flat list 模式：从节点信息推断边（data 本身没有显式 relation）
  if (Array.isArray(evidence)) {
    inferEdges(graphNodes.value, graphEdges)
  }
}

export function useSSE() {
  const connected = ref(false)
  const lastError = ref(null)
  const steps = ref([])
  const graphNodes = ref([])
  const graphEdges = ref([])
  const runCompleted = ref(false)

  let es = null
  let reconnectTimer = null
  let reconnectAttempt = 0
  let currentRunId = null

  // SSE 事件处理
  function handleStepUpdate(data) {
    const idx = steps.value.findIndex(s => s.step_id === data.step_id)
    const now = Date.now()
    // 兼容 SSE 事件 'evidence' 字段和历史 API 'evidence_json' 字段
    const evidence = data.evidence || data.evidence_json || { data_sources: [], evidence: [] }
    if (idx >= 0) {
      steps.value[idx] = { ...steps.value[idx], ...data, evidence_json: evidence, _updated_at: now }
    } else {
      steps.value.push({
        step_id: data.step_id,
        agent: data.agent,
        stage: data.stage,
        status: data.status || 'running',
        output: data.output || '',
        evidence_json: evidence,
        elapsed_seconds: data.elapsed_seconds || 0,
        started_at: data.started_at,
        timestamp: new Date().toISOString(),
        _updated_at: now,
      })
    }
    // 实时更新也构建图谱
    if (evidence) {
      parseEvidenceForGraph(evidence, graphNodes, graphEdges)
    }
  }

  function handleStepCompleted(data) {
    const idx = steps.value.findIndex(s => s.step_id === data.step_id)
    const now = Date.now()
    if (idx >= 0) {
      steps.value[idx] = {
        ...steps.value[idx],
        status: 'completed',
        output: data.output || steps.value[idx].output,
        elapsed_seconds: data.elapsed_seconds || steps.value[idx].elapsed_seconds,
        _updated_at: now,
      }
    } else {
      steps.value.push({
        step_id: data.step_id,
        agent: data.agent,
        stage: data.stage,
        status: 'completed',
        output: data.output || '',
        evidence_json: {},
        elapsed_seconds: data.elapsed_seconds || 0,
        timestamp: new Date().toISOString(),
      })
    }
    // 解析证据数据（兼容 flat list 和嵌套格式）
    const evidence = data.evidence || data.evidence_json || null
    if (evidence) {
      parseEvidenceForGraph(evidence, graphNodes, graphEdges)
    }
    // 兜底：若 evidence 为空，从 output 文本中提取简单实体
    if ((!evidence || (Array.isArray(evidence) && evidence.length === 0) || (!Array.isArray(evidence) && (!evidence.data_sources || evidence.data_sources.length === 0))) && data.output) {
      const entities = extractEntitiesFromText(data.output)
      if (entities.length > 0) {
        entities.forEach(src => {
          if (!graphNodes.value.find(n => n.id === src.id)) {
            graphNodes.value.push({
              id: src.id,
              type: src.type,
              label: src.label,
              properties: src.properties || {},
              x: Math.random() * 600,
              y: Math.random() * 400,
            })
          }
        })
      }
    }
  }

  function handleRunCompleted(data) {
    runCompleted.value = true
    // 更新最后一步状态为 completed
    if (steps.value.length > 0) {
      const last = steps.value[steps.value.length - 1]
      last.status = 'completed'
    }
  }

  function handleError(data) {
    lastError.value = data.message || 'SSE 连接错误'
  }

  /**
   * 加载历史步骤数据（用于 onMounted 时回填）
   * 同时构建 step 卡片和证据图谱。
   *
   * @param {Object} step - 历史步骤对象
   *   @param {string|number} step.id - 步骤 ID
   *   @param {string} [step.step_id] - 步骤 ID（优先）
   *   @param {string} [step.agent] - Agent 名称
   *   @param {string} [step.stage] - 阶段
   *   @param {string} [step.status] - 状态
   *   @param {string} [step.output] - 输出文本
   *   @param {Object|Array} [step.evidence] - 证据数据
   *   @param {Object|Array} [step.evidence_json] - 证据数据（后备）
   *   @param {string} [step.started_at] - 开始时间
   *   @param {string} [step.timestamp] - 时间戳
   */
  function loadHistoricalStep(step) {
    if (!step) return

    // 1. 添加到 steps
    const stepId = step.step_id || String(step.id || '')
    if (stepId && !steps.value.find(s => s.step_id === stepId)) {
      steps.value.push({
        step_id: stepId,
        agent: step.agent || '',
        stage: step.stage || '',
        status: step.status === 'success' ? 'completed' : (step.status || 'completed'),
        output: step.output || '',
        evidence_json: step.evidence || step.evidence_json || { data_sources: [], evidence: [] },
        elapsed_seconds: 0,
        started_at: step.started_at,
        timestamp: step.timestamp || new Date().toISOString(),
        _updated_at: Date.now(),
      })
    }

    // 2. 解析 evidence 字段，构建 graphNodes 和 graphEdges
    const evidence = step.evidence || step.evidence_json
    if (evidence) {
      parseEvidenceForGraph(evidence, graphNodes, graphEdges)
    }
  }

  function connect(runId) {
    if (currentRunId === runId && es) return
    disconnect()
    currentRunId = runId
    const url = `/api/agents/runs/${runId}/stream`
    es = new EventSource(url)

    es.addEventListener('step_update', (e) => {
      try { handleStepUpdate(JSON.parse(e.data)) } catch (err) { /* ignore parse errors */ }
    })
    es.addEventListener('step_completed', (e) => {
      try { handleStepCompleted(JSON.parse(e.data)) } catch (err) { /* ignore */ }
    })
    es.addEventListener('run_completed', (e) => {
      try { handleRunCompleted(JSON.parse(e.data)) } catch (err) { /* ignore */ }
    })
    es.addEventListener('error', (e) => {
      handleError({ message: 'SSE 连接异常' })
    })

    es.onopen = () => {
      connected.value = true
      lastError.value = null
      reconnectAttempt = 0
    }

    es.onerror = () => {
      connected.value = false
      es.close()
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    // 终态运行不重连（避免无限循环重连已结束的 run）
    if (runCompleted.value) {
      return
    }
    const delay = RECONNECT_DELAYS[Math.min(reconnectAttempt, RECONNECT_DELAYS.length - 1)]
    reconnectAttempt++
    if (currentRunId) {
      reconnectTimer = setTimeout(() => connect(currentRunId), delay)
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (es) {
      es.close()
      es = null
    }
    connected.value = false
    currentRunId = null
    reconnectAttempt = 0
  }

  // 简单的实体提取（启发式）
  function extractEntitiesFromText(text) {
    if (!text) return []
    const entities = []
    // IP 地址
    const ipRegex = /\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/g
    let m
    while ((m = ipRegex.exec(text)) !== null) {
      entities.push({ id: `ip:${m[1]}`, type: 'host', label: m[1], properties: { ip: m[1] } })
    }
    // 文件路径
    const pathRegex = /([A-Za-z]:\\[\w\\\.\-]+|\/[\w\/\.\-]+\.[a-z]{2,4})/g
    while ((m = pathRegex.exec(text)) !== null) {
      if (m[1].length < 200) {
        entities.push({ id: `path:${m[1]}`, type: 'file', label: m[1].split('\\').pop() || m[1], properties: { path: m[1] } })
      }
    }
    // 去重
    const seen = new Set()
    return entities.filter(e => {
      if (seen.has(e.id)) return false
      seen.add(e.id)
      return true
    })
  }

  // cleanup on unmount
  onUnmounted(() => disconnect())

  // ========== 图谱节点聚合（关键优化） ==========
  // 原始 nodes 经常含 30+ 节点（ir_agent.exe 多个 PID、normalized_logs 20 条...）
  // 聚合后大幅减少视觉噪音：
  //   - 同名 process 节点 → 1 个"组节点"+ count 数字
  //   - 多个 normalized_logs → 折叠为 1 个"日志(N)"节点
  //   - 保留 security_event/host/action 单个显示
  const aggregatedNodes = computed(() => {
    const list = graphNodes.value
    if (!list || list.length === 0) return []

    const groups = new Map()
    const singles = []

    for (const node of list) {
      const t = node.type
      if (t === 'process') {
        // 同名 process 合并（如 ir_agent.exe 有 3 个 PID → 1 个节点）
        const key = (node.label || node.id).toLowerCase()
        if (groups.has(key)) {
          groups.get(key).count++
          groups.get(key).originalIds.push(node.id)
        } else {
          groups.set(key, { ...node, count: 1, originalIds: [node.id] })
        }
      } else if (t === 'log') {
        // 多个 log 节点合并成 1 个"日志(N)"
        const key = 'logs-bucket'
        if (groups.has(key)) {
          groups.get(key).count++
          groups.get(key).originalIds.push(node.id)
        } else {
          groups.set(key, { ...node, count: 1, originalIds: [node.id], label: '系统日志' })
        }
      } else {
        // security/host/action/file/url 单个保留
        singles.push(node)
      }
    }

    return [...singles, ...groups.values()]
  })

  return {
    connected,
    lastError,
    steps,
    graphNodes,
    graphEdges,
    aggregatedNodes,
    graphEdges,
    runCompleted,
    connect,
    disconnect,
    loadHistoricalStep,
  }
}
