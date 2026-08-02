/**
 * 智能体管理 Phase 2 — Pinia Store
 *
 * 职责：管理 Agent 定义、管道构建、运行状态与预置模板。
 * 采用 setup function 风格（与 stores/agents.js 一致），集中缓存所有后端数据，
 * 对外暴露同步的 state / getters / actions。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'

export const useAgentManagementStore = defineStore('agentManagement', () => {
  // ==========================================================================
  // State
  // ==========================================================================

  /** 所有 Agent 定义列表。 */
  const agents = ref([])
  /** 是否正在加载 Agent 列表。 */
  const loading = ref(false)

  /** 管道构建中的 Agent 列表（有序）。 */
  const pipeline = ref([])
  /** 管道校验消息。 */
  const validationMessages = ref([])
  /** 管道校验是否通过。 */
  const isPipelineValid = ref(false)

  /** 当前运行信息。 */
  const currentRun = ref(null)
  /** 是否正在执行管道。 */
  const runLoading = ref(false)

  /** 预置模板列表。 */
  const presets = ref([])
  /** 是否正在加载预置模板。 */
  const presetsLoading = ref(false)

  /**
   * 当前在画布上选中的节点（与 pipelineEditor store 桥接）。
   * 保存节点 ID 或节点名，用于跨 store 同步。
   */
  const selectedNode = ref(null)

  // ==========================================================================
  // Getters
  // ==========================================================================

  /** 仅返回已启用的 Agent。 */
  const availableAgents = computed(() => agents.value.filter(a => a.enabled))

  /** 管道摘要文字（用于状态栏展示）。 */
  const pipelineSummary = computed(() => {
    if (pipeline.value.length === 0) return ''
    return `${pipeline.value.length} 个 Agent · ${isPipelineValid.value ? '✓ 有效' : '✗ 待校验'}`
  })

  // ==========================================================================
  // Actions — Agent CRUD
  // ==========================================================================

  /**
   * 从后端拉取所有 Agent 列表。
   * 加载期间 loading 为 true，完成后重置。
   */
  async function fetchAgents() {
    loading.value = true
    try {
      // Library 需要显示所有 Agent（包括禁用的），所以传 false
      const res = await agentApi.listAgents(false)
      agents.value = res.data || []
    } catch (e) {
      console.error('[agentManagement] fetchAgents failed:', e)
      agents.value = []
    } finally {
      loading.value = false
    }
  }

  /**
   * 注册新 Agent，注册成功后自动刷新列表。
   * @param {object} data — Agent 定义数据
   * @returns {Promise<object>} 完整响应信封（含 data + 可选顶层 warning，P2）
   */
  async function registerAgent(data) {
    try {
      const res = await agentApi.createAgent(data)
      await fetchAgents()
      return res
    } catch (e) {
      console.error('[agentManagement] registerAgent failed:', e)
      throw e
    }
  }

  /**
   * 更新 Agent 配置，成功后自动刷新列表。
   * @param {string} name — Agent 名称
   * @param {object} data — 需要更新的字段
   * @returns {Promise<object>} 完整响应信封（含 data + 可选顶层 warning，P2）
   */
  async function updateAgentAction(name, data) {
    try {
      const res = await agentApi.updateAgent(name, data)
      await fetchAgents()
      return res
    } catch (e) {
      console.error('[agentManagement] updateAgent failed:', e)
      throw e
    }
  }

  /**
   * 注销 Agent，成功后自动刷新列表。
   * @param {string} name — Agent 名称
   */
  async function deleteAgentAction(name) {
    try {
      await agentApi.deleteAgent(name)
      await fetchAgents()
    } catch (e) {
      console.error('[agentManagement] deleteAgent failed:', e)
      throw e
    }
  }

  /**
   * 切换 Agent 启用/禁用状态。
   * @param {object} agent — Agent 对象
   */
  async function toggleEnabled(agent) {
    await updateAgentAction(agent.name, { enabled: !agent.enabled })
  }

  // ==========================================================================
  // Actions — Pipeline 构建
  // ==========================================================================

  /**
   * 将 Agent 加入管道末尾（去重）。
   * @param {object} agent — Agent 对象（含 name, display_name 等字段）
   */
  function addToPipeline(agent) {
    if (pipeline.value.find(a => a.name === agent.name)) return
    pipeline.value.push({ ...agent })
    validatePipelineAction()
  }

  /**
   * 从管道中移除指定 Agent。
   * @param {string} agentName — 要移除的 Agent 名称
   */
  function removeFromPipeline(agentName) {
    pipeline.value = pipeline.value.filter(a => a.name !== agentName)
    validatePipelineAction()
  }

  /**
   * 重排管道中的 Agent 顺序。
   * @param {number} fromIdx — 原位置
   * @param {number} toIdx — 目标位置
   */
  function reorderPipeline(fromIdx, toIdx) {
    if (fromIdx < 0 || fromIdx >= pipeline.value.length) return
    if (toIdx < 0 || toIdx >= pipeline.value.length) return
    const item = pipeline.value.splice(fromIdx, 1)[0]
    pipeline.value.splice(toIdx, 0, item)
    validatePipelineAction()
  }

  /**
   * 向后端发起管道校验。
   * 若管道为空，直接重置校验状态，不发起请求。
   */
  async function validatePipelineAction() {
    const names = pipeline.value.map(a => a.name)
    if (names.length === 0) {
      validationMessages.value = []
      isPipelineValid.value = false
      return
    }
    try {
      const res = await agentApi.pipeline.validate(names)
      const data = res.data || {}
      validationMessages.value = data.warnings || []
      isPipelineValid.value = data.valid !== false
    } catch (e) {
      console.error('[agentManagement] validatePipeline failed:', e)
      validationMessages.value = ['校验服务不可用']
      isPipelineValid.value = false
    }
  }

  // ==========================================================================
  // Actions — 执行
  // ==========================================================================

  /**
   * 启动管道执行。
   * @param {string} eventId — 事件 ID
   * @param {boolean} useCache — 是否使用缓存（默认 true）
   * @returns {Promise<object|null>} 运行信息 {run_id, status}
   */
  async function startPipeline(eventId, useCache = true) {
    const names = pipeline.value.map(a => a.name)
    if (names.length === 0) throw new Error('管道为空')
    runLoading.value = true
    try {
      const res = await agentApi.pipeline.run(eventId, names, useCache)
      currentRun.value = res.data || null
      return currentRun.value
    } catch (e) {
      console.error('[agentManagement] startPipeline failed:', e)
      throw e
    } finally {
      runLoading.value = false
    }
  }

  /**
   * 查询指定 run 的运行状态，并更新 currentRun。
   * @param {string} runId — 运行 ID
   * @returns {Promise<object|null>}
   */
  async function fetchRunStatus(runId) {
    try {
      const res = await agentApi.pipeline.getRunStatus(runId)
      currentRun.value = res.data || null
      return currentRun.value
    } catch (e) {
      console.error('[agentManagement] fetchRunStatus failed:', e)
      return null
    }
  }

  /**
   * 取消指定 run。
   * @param {string} runId — 运行 ID
   */
  async function cancelRunAction(runId) {
    try {
      await agentApi.pipeline.cancel(runId)
      if (currentRun.value) currentRun.value.status = 'cancelled'
    } catch (e) {
      console.error('[agentManagement] cancelRun failed:', e)
      throw e
    }
  }

  // ==========================================================================
  // Actions — 预置模板
  // ==========================================================================

  /** 从后端拉取所有预置模板列表。 */
  async function fetchPresets() {
    presetsLoading.value = true
    try {
      const res = await agentApi.pipeline.getPresets()
      presets.value = res.data || []
    } catch (e) {
      console.error('[agentManagement] fetchPresets failed:', e)
      presets.value = []
    } finally {
      presetsLoading.value = false
    }
  }

  /**
   * 将当前管道保存为预置模板。
   * @param {string} name — 模板名称
   * @param {string} description — 模板描述
   * @returns {Promise<object>}
   */
  async function savePreset(name, description) {
    const names = pipeline.value.map(a => a.name)
    if (!name || names.length === 0) throw new Error('名称和 Agent 列表不能为空')
    try {
      const res = await agentApi.pipeline.createPreset(name, description, names)
      await fetchPresets()
      return res.data || null
    } catch (e) {
      console.error('[agentManagement] savePreset failed:', e)
      throw e
    }
  }

  /**
   * 删除指定预置模板。
   * @param {number|string} presetId — 模板 ID
   */
  async function deletePresetAction(presetId) {
    try {
      await agentApi.pipeline.deletePreset(presetId)
      await fetchPresets()
    } catch (e) {
      console.error('[agentManagement] deletePreset failed:', e)
      throw e
    }
  }

  // ==========================================================================
  // Actions — 工具
  // ==========================================================================

  /** 清空管道并重置校验状态。 */
  function clearPipeline() {
    pipeline.value = []
    validationMessages.value = []
    isPipelineValid.value = false
  }

  /**
   * 将预置模板加载到当前管道。
   * 从已加载的 agents 列表中查找匹配的 Agent 对象。
   * @param {object} preset — 预置模板对象（含 agents: string[]）
   */
  function loadPresetToPipeline(preset) {
    const names = preset.agents || []
    pipeline.value = names
      .map(name => agents.value.find(a => a.name === name))
      .filter(Boolean)
    validatePipelineAction()
  }

  // ==========================================================================
  // Actions — Store 桥接
  // ==========================================================================

  /**
   * 更新画布上指定节点的配置信息。
   * 桥接到 pipelineEditor store 的 updateNodeConfig。
   * @param {string} nodeName — 节点名称
   * @param {object} config — 配置补丁
   */
  function updateNodeConfig(nodeName, config) {
    // 更新 pipeline 中指定 agent 的运行时配置
    const agent = pipeline.value.find(a => a.name === nodeName)
    if (agent) Object.assign(agent, config)
  }

  /**
   * 选中画布上的某个节点用于配置编辑。
   * 同步到 pipelineEditor store 的 selectNode。
   * @param {object} node — 节点对象
   */
  function selectNodeForConfig(node) {
    selectedNode.value = node ? { id: node.id, name: node.name, type: node.type } : null
  }

  // ==========================================================================
  // Expose
  // ==========================================================================

  return {
    // state
    agents,
    loading,
    pipeline,
    validationMessages,
    isPipelineValid,
    currentRun,
    runLoading,
    presets,
    presetsLoading,
    selectedNode,
    // getters
    availableAgents,
    pipelineSummary,
    // actions
    fetchAgents,
    registerAgent,
    updateAgentAction,
    updateAgent: updateAgentAction,
    deleteAgentAction,
    deleteAgent: deleteAgentAction,
    toggleEnabled,
    addToPipeline,
    removeFromPipeline,
    reorderPipeline,
    validatePipelineAction,
    startPipeline,
    fetchRunStatus,
    cancelRunAction,
    fetchPresets,
    savePreset,
    deletePresetAction,
    clearPipeline,
    loadPresetToPipeline,
    updateNodeConfig,
    selectNodeForConfig,
  }
})
