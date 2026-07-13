// AI 分析 Pinia Store — 管理 Profile、分析任务、流式输出状态

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  getAiProfiles,
  createAiProfile,
  updateAiProfile,
  deleteAiProfile,
  activateAiProfile,
  testAiConnection,
  aiAnalyze,
  cancelAiTask,
  getAiReport,
  getAiReportVersions,
  getAiTaskStatus,
} from '@/api/ai'

export const useAiStore = defineStore('ai', () => {
  // ============================================================
  // State
  // ============================================================

  /** 所有 Profile 列表 */
  const profiles = ref([])

  /** 当前活跃 Profile ID */
  const activeProfileId = ref(null)

  /** 当前分析任务信息 */
  const currentTask = ref(null)

  /** 流式输出的累积文本 */
  const streamContent = ref('')

  /** 任务进度 0-100 */
  const taskProgress = ref(0)

  /** 任务状态：idle | analyzing | completed | error | cancelled */
  const taskStatus = ref('idle')

  /** 任务阶段描述 */
  const taskStage = ref('')

  /** 阶段时间线: [{stage, name, elapsed_ms, active}] */
  const stageTimeline = ref([])

  /** 流式请求的 AbortController */
  let streamAbortController = null
  /** 取消守卫标志：取消后忽略所有非 error 事件，防止晚到的 complete/done/content 覆盖状态 */
  let _cancelled = false
  /** 上一阶段已用总耗时（毫秒），用于计算单阶段增量 */
  let stageStartElapsed = 0
  /** 最近一次 progress 事件的累计耗时 */
  let _lastElapsedMs = 0

  /** Token 消耗统计 */
  const tokenUsage = ref({ prompt: 0, completion: 0, total: 0 })

  /** 最终报告数据 */
  const reportData = ref(null)

  // ============================================================
  // Getters
  // ============================================================

  /** 当前活跃的 Profile 对象 */
  const activeProfile = computed(() => {
    return profiles.value.find((p) => p.id === activeProfileId.value) || null
  })

  /** 是否有 Profile */
  const hasProfiles = computed(() => profiles.value.length > 0)

  /** 是否正在分析中 */
  const isAnalyzing = computed(() => taskStatus.value === 'analyzing')

  /** AI 功能是否已启用（存在活跃 Profile 且配置完整） */
  const isAiEnabled = computed(() => {
    const p = activeProfile.value
    return !!(p && p.api_base_url && p.api_key_masked)
  })

  // ============================================================
  // Actions
  // ============================================================

  /**
   * 加载所有 Profile 列表
   */
  async function fetchProfiles() {
    try {
      const res = await getAiProfiles()
      const data = res.data || {}
      profiles.value = data.items || []
      // 设置活跃 Profile
      if (data.active_id) {
        activeProfileId.value = data.active_id
      } else if (!activeProfileId.value && profiles.value.length > 0) {
        const active = profiles.value.find((p) => p.is_active === 1)
        if (active) {
          activeProfileId.value = active.id
        }
      }
    } catch {
      profiles.value = []
    }
  }

  /**
   * 设置活跃 Profile
   * @param {number} id - Profile ID
   */
  async function setActiveProfile(id) {
    try {
      await activateAiProfile(id)
      activeProfileId.value = id
      // 刷新列表以更新 is_active 状态
      await fetchProfiles()
    } catch (error) {
      throw error
    }
  }

  /**
   * 创建新 Profile
   * @param {object} data - Profile 数据
   * @returns {Promise<object>} 创建的 Profile
   */
  async function createProfile(data) {
    const res = await createAiProfile(data)
    const newProfile = res.data
    profiles.value.push(newProfile)
    // 如果是第一个 Profile，自动设为活跃
    if (profiles.value.length === 1) {
      activeProfileId.value = newProfile.id
    }
    return newProfile
  }

  /**
   * 更新 Profile
   * @param {number} id - Profile ID
   * @param {object} data - 要更新的字段
   */
  async function updateProfile(id, data) {
    const res = await updateAiProfile(id, data)
    const updated = res.data
    const idx = profiles.value.findIndex((p) => p.id === id)
    if (idx !== -1) {
      profiles.value[idx] = { ...profiles.value[idx], ...updated }
    }
  }

  /**
   * 删除 Profile
   * @param {number} id - Profile ID
   */
  async function deleteProfileById(id) {
    await deleteAiProfile(id)
    profiles.value = profiles.value.filter((p) => p.id !== id)
    if (activeProfileId.value === id) {
      activeProfileId.value = profiles.value.length > 0 ? profiles.value[0].id : null
    }
  }

  /**
   * 提交 AI 分析任务（异步模式）
   * @param {number|string} hostId - 主机 ID
   * @param {number} maskedMode - 脱敏模式 1=开启 0=关闭
   * @returns {Promise<string>} taskId
   */
  async function startAnalysis(hostId, maskedMode, options = {}) {
    const { mode, focusArea, audience } = options
    const res = await aiAnalyze(hostId, {
      maskedMode,
      profileId: activeProfileId.value,
      mode: mode || 'standard',
      focusArea: focusArea || null,
      audience: audience || null,
    })
    const taskId = res.data?.task_id
    if (!taskId) {
      throw new Error('未获取到任务 ID')
    }
    currentTask.value = { taskId, hostId }
    return taskId
  }

  /**
   * 连接 SSE 流式端点，逐步累积 streamContent
   * 使用 fetch + ReadableStream 实现
   * @param {string} taskId - 任务 ID
   */
  async function connectStream(taskId) {
    resetStream()
    _cancelled = false
    taskStatus.value = 'analyzing'

    // ── 轮询兜底：每隔 2 秒检查任务状态（SSE 失败时的 fallback）──
    let pollCount = 0
    const pollInterval = setInterval(async () => {
      if (taskStatus.value !== 'analyzing' || _cancelled) {
        clearInterval(pollInterval)
        return
      }
      pollCount++
      try {
        const task = await getAiTaskStatus(taskId)
        const status = task?.data?.status || task?.status
        const progress = task?.data?.progress || task?.progress
        const stage = task?.data?.stage || task?.stage
        const errorMsg = task?.data?.error_message || task?.error_message
        const reportId = task?.data?.report_id || task?.report_id

        if (progress !== undefined) taskProgress.value = progress
        if (stage) taskStage.value = stage

        if (status === 'completed') {
          taskStatus.value = 'completed'
          taskProgress.value = 100
          clearInterval(pollInterval)
          return
        }
        if (status === 'failed' || status === 'error') {
          taskStatus.value = 'error'
          taskStage.value = errorMsg || '分析失败'
          clearInterval(pollInterval)
          return
        }
        if (status === 'cancelled') {
          taskStatus.value = 'cancelled'
          clearInterval(pollInterval)
          return
        }
      } catch (e) {
        console.warn('[AiStore] status poll failed:', e)
      }
    }, 2000)

    const controller = new AbortController()
    streamAbortController = controller

    try {
      const token = localStorage.getItem('ir_token')
      const baseUrl = '/api'
      const url = `${baseUrl}/ai/tasks/${taskId}/stream?token=${encodeURIComponent(token || '')}`

      const response = await fetch(url, {
        headers: {
          Accept: 'text/event-stream',
          Authorization: `Bearer ${token || ''}`,
        },
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`SSE 连接失败 (HTTP ${response.status})`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        // 最后一个可能是不完整的行，保留在 buffer 中
        buffer = lines.pop() || ''

        let currentEvent = 'message'

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            // 空行表示一个事件的结束
            currentEvent = 'message'
            continue
          }

          if (trimmed.startsWith('event:')) {
            currentEvent = trimmed.slice(6).trim()
            continue
          }

          if (trimmed.startsWith('data:')) {
            const dataStr = trimmed.slice(5).trim()
            if (!dataStr) continue

            try {
              const data = JSON.parse(dataStr)
              processStreamEvent(currentEvent, data)
            } catch {
              // 非 JSON 数据：chunk 类型直接作为文本追加
              if (currentEvent === 'chunk') {
                streamContent.value += dataStr
              }
            }
          }
        }
      }

      // 流正常结束
      if (taskStatus.value === 'analyzing') {
        // 完成最后一个活跃阶段，但不把流结束误判为分析成功
        const activeStage = stageTimeline.value.find((s) => s.active)
        if (activeStage) {
          activeStage.elapsed_ms = _lastElapsedMs - stageStartElapsed
          activeStage.active = false
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        taskStatus.value = 'cancelled'
        taskStage.value = '已取消'
      } else {
        // SSE 失败 → 依赖 polling fallback 兜底
        console.warn('[AiStore] SSE connection failed, relying on polling:', err.message)
        taskStage.value = 'SSE 连接异常，改用轮询模式...'
      }
    } finally {
      clearInterval(pollInterval)
      streamAbortController = null
    }
  }

  /**
   * 处理 SSE 事件
   */
  function processStreamEvent(eventType, data) {
    // 取消守卫：取消后忽略所有非 error 事件，防止晚到的 complete/done/content 二次写回 UI
    if (_cancelled && eventType !== 'error') return
    switch (eventType) {
      case 'chunk':
      case 'content':
        // 追加文本内容
        if (data.content) {
          streamContent.value += data.content
        } else if (typeof data === 'string') {
          streamContent.value += data
        }
        break

      case 'progress':
        // 更新进度和阶段
        if (data.progress !== undefined) {
          taskProgress.value = data.progress
        }
        if (data.stage) {
          updateStageTimeline(data.stage, data.elapsed_ms || 0)
          taskStage.value = data.stage
        }
        if (data.elapsed_ms !== undefined) {
          _lastElapsedMs = data.elapsed_ms
        }
        if (data.tokens) {
          tokenUsage.value = {
            prompt: data.tokens.prompt || 0,
            completion: data.tokens.completion || 0,
            total: data.tokens.total || 0,
          }
        }
        break

      case 'complete':
        taskStatus.value = 'completed'
        taskProgress.value = 100
        if (data.report) {
          reportData.value = data.report
        }
        break

      case 'done':
        if (data.report) {
          reportData.value = data.report
        }
        if (taskStatus.value === 'analyzing') {
          taskStage.value = data.message || '分析流已结束，等待最终结果'
        }
        break

      case 'error':
        taskStatus.value = 'error'
        taskStage.value = data.message || '分析过程出错'
        break

      default:
        // 未识别的事件类型，尝试作为 chunk 处理
        if (data.content) {
          streamContent.value += data.content
        }
        break
    }
  }

  /**
   * 取消当前分析任务
   */
  async function cancelAnalysis() {
    // 在 abort 之前设置取消守卫，防止 abort 后仍有已排队的 SSE 事件被处理
    _cancelled = true
    if (streamAbortController) {
      streamAbortController.abort()
      streamAbortController = null
    }
    if (currentTask.value?.taskId) {
      try {
        await cancelAiTask(currentTask.value.taskId)
      } catch {
        // 即使取消 API 调用失败，本地已中止流
      }
    }
    taskStatus.value = 'cancelled'
    taskStage.value = '已取消'
  }

  /**
   * 重置流式输出状态
   */
  function resetStream() {
    streamContent.value = ''
    taskProgress.value = 0
    taskStage.value = ''
    taskStatus.value = 'idle'
    reportData.value = null
    tokenUsage.value = { prompt: 0, completion: 0, total: 0 }
    stageTimeline.value = []
    stageStartElapsed = 0
    _lastElapsedMs = 0
    _cancelled = false
    if (streamAbortController) {
      streamAbortController.abort()
      streamAbortController = null
    }
  }

  /**
   * 更新阶段时间线（P2-10：分阶段进度展示）
   * @param {string} stageCode - 阶段代码 (assembling|building|calling|parsing|saving)
   * @param {number} currentElapsed - SSE 返回的累计耗时 (ms)
   */
  const STAGE_NAME_MAP = {
    assembling: '数据组装',
    building: 'Prompt构建',
    calling: 'LLM调用中',
    parsing: '结果解析',
    saving: '保存报告',
  }

  function updateStageTimeline(stageCode, currentElapsed) {
    // 完成上一个活跃阶段
    const activeIdx = stageTimeline.value.findIndex((s) => s.active)
    if (activeIdx >= 0) {
      stageTimeline.value[activeIdx].elapsed_ms = currentElapsed - stageStartElapsed
      stageTimeline.value[activeIdx].active = false
    }

    // 如果该阶段已经存在（重复推送），仅更新耗时
    const existingIdx = stageTimeline.value.findIndex((s) => s.stage === stageCode)
    if (existingIdx >= 0) {
      stageTimeline.value[existingIdx].active = true
      stageTimeline.value[existingIdx].elapsed_ms = null
      stageStartElapsed = currentElapsed
      return
    }

    // 添加新阶段
    stageStartElapsed = currentElapsed
    stageTimeline.value.push({
      stage: stageCode,
      name: STAGE_NAME_MAP[stageCode] || stageCode,
      elapsed_ms: null,
      active: true,
    })
  }

  /**
   * 加载分析报告
   * @param {number|string} hostId
   */
  async function fetchReport(hostId) {
    try {
      const res = await getAiReport(hostId)
      reportData.value = res.data
      return reportData.value
    } catch {
      reportData.value = null
      return null
    }
  }

  /**
   * 加载报告版本列表
   * @param {number|string} hostId
   */
  async function fetchReportVersions(hostId) {
    try {
      const res = await getAiReportVersions(hostId)
      return res.data || []
    } catch {
      return []
    }
  }

  return {
    // state
    profiles,
    activeProfileId,
    currentTask,
    streamContent,
    taskProgress,
    taskStatus,
    taskStage,
    tokenUsage,
    reportData,
    stageTimeline,

    // getters
    activeProfile,
    hasProfiles,
    isAnalyzing,
    isAiEnabled,

    // actions
    fetchProfiles,
    setActiveProfile,
    createProfile,
    updateProfile,
    deleteProfileById,
    startAnalysis,
    connectStream,
    cancelAnalysis,
    resetStream,
    fetchReport,
    fetchReportVersions,
  }
})
