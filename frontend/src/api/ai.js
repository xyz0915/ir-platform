// AI 分析 API 封装 — 完整重写

import request from './index'

// ============================================================
// AI 配置 Profile 管理
// ============================================================

// 获取所有AI配置Profile列表
export function getAiProfiles() {
  return request.get('/ai/profiles')
}

// 创建AI配置Profile
export function createAiProfile(data) {
  return request.post('/ai/profiles', data)
}

// 更新AI配置Profile
export function updateAiProfile(profileId, data) {
  return request.put(`/ai/profiles/${profileId}`, data)
}

// 删除AI配置Profile
export function deleteAiProfile(profileId) {
  return request.delete(`/ai/profiles/${profileId}`)
}

// 激活AI配置Profile
export function activateAiProfile(profileId) {
  return request.post(`/ai/profiles/${profileId}/activate`)
}

// 测试AI连接
export function testAiConnection(profileId) {
  return request.post('/ai/test-connection', { profile_id: profileId })
}

// ============================================================
// AI 分析任务
// ============================================================

// 提交AI分析任务（异步模式，返回 task_id）
export function aiAnalyze(hostId, options = {}) {
  const { profileId, maskedMode, mode, focusArea, baseReportId } = options
  const params = new URLSearchParams()
  if (maskedMode !== undefined) params.set('masked_mode', maskedMode)
  if (mode) params.set('mode', mode)
  if (focusArea) params.set('focus_area', focusArea)
  if (baseReportId) params.set('base_report_id', baseReportId)
  const query = params.toString()
  return request.post(`/ai/analyze/${hostId}${query ? `?${query}` : ''}`, {
    profile_id: profileId ?? null,
    masked_mode: maskedMode ?? 1,
    mode: mode ?? 'standard',
    focus_area: focusArea ?? null,
    base_report_id: baseReportId ?? null,
  })
}

// 获取AI分析任务状态
export function getAiTaskStatus(taskId) {
  return request.get(`/ai/tasks/${taskId}`)
}

// SSE 流式获取AI分析进度
export function streamAiAnalysis(taskId, onProgress, onComplete, onError) {
  const token = localStorage.getItem('ir_token')
  const baseURL = request.defaults.baseURL || '/api'

  const eventSource = new EventSource(
    `${baseURL}/ai/tasks/${taskId}/stream?token=${encodeURIComponent(token || '')}`
  )

  eventSource.addEventListener('progress', (event) => {
    try {
      const data = JSON.parse(event.data)
      onProgress && onProgress(data)
    } catch (e) {
      // ignore parse errors
    }
  })

  eventSource.addEventListener('complete', (event) => {
    try {
      const data = JSON.parse(event.data)
      onComplete && onComplete(data)
    } catch (e) {
      onComplete && onComplete({})
    }
    eventSource.close()
  })

  eventSource.addEventListener('error', (event) => {
    try {
      if (event.data) {
        const data = JSON.parse(event.data)
        onError && onError(data)
      }
    } catch (e) {
      onError && onError({ message: 'SSE连接异常' })
    }
    eventSource.close()
  })

  eventSource.onerror = () => {
    onError && onError({ message: 'SSE连接中断' })
    eventSource.close()
  }

  return eventSource
}

// 取消AI分析任务
export function cancelAiTask(taskId) {
  return request.post(`/ai/tasks/${taskId}/cancel`)
}

// ============================================================
// AI 分析报告
// ============================================================

// 获取主机最新的AI分析报告
export function getAiReport(hostId) {
  return request.get(`/ai/report/${hostId}`)
}

// 获取主机AI分析报告版本列表
export function getAiReportVersions(hostId) {
  return request.get(`/ai/report/${hostId}/versions`)
}

// 获取主机特定版本的AI分析报告
export function getAiReportByVersion(hostId, version) {
  return request.get(`/ai/report/${hostId}/versions/${version}`)
}

// 导出AI分析报告PDF
export function exportAiReportPdf(hostId) {
  return request.get(`/ai/report/${hostId}/pdf`, {
    responseType: 'blob',
  })
}

// 删除AI分析报告
export function deleteAiReport(hostId) {
  return request.delete(`/ai/report/${hostId}`)
}

// ============================================================
// AI 审计日志
// ============================================================

// 获取审计日志列表
export function getAiAuditLogs(params = {}) {
  return request.get('/ai/audit-logs', { params })
}

// 获取审计日志详情
export function getAiAuditLogDetail(logId) {
  return request.get(`/ai/audit-logs/${logId}`)
}

// ============================================================
// Token 统计
// ============================================================

// 获取Token使用统计
export function getAiTokenStats(params = {}) {
  return request.get('/ai/stats/tokens', { params })
}

// 获取Token汇总（按天/按模型/按Profile）
export function getAiTokenSummary(groupBy = 'daily') {
  return request.get('/ai/stats/summary', { params: { group_by: groupBy } })
}

// 向后兼容：获取当前活跃 AI 配置（HostDetailView 用）
export function getAiConfig() {
  return request.get('/ai/config')
}

// ============================================================
// P2: 多轮对话
// ============================================================

// 向 AI 发送追问消息
export function chatWithAi(hostId, data) {
  // 后端 chat_with_ai 使用 httpx timeout=120s，前端必须至少等这么久，
  // 否则会在 30s（全局超时）时提前抛出 timeout 错误。仅本接口覆盖超时，
  // 不影响全局 axios 30s 超时配置。
  return request.post(`/ai/analyze/${hostId}/chat`, data, { timeout: 120000 })
}

// 获取对话历史
export function getConversation(conversationId) {
  return request.get(`/ai/conversations/${conversationId}`)
}

// ============================================================
// P2: 提示词优化
// ============================================================

// 优化系统提示词
export function optimizePrompt(profileId, data) {
  return request.post('/ai/prompt/optimize', { ...data, profile_id: profileId })
}

// 获取提示词历史版本
export function getPromptVersions(profileId) {
  return request.get(`/ai/prompt/versions/${profileId}`)
}

// ============================================================
// P2: 批量对比分析
// ============================================================

// 提交批量对比分析任务
export function compareHosts(hostIds, dimensions) {
  return request.post('/ai/analyze/compare', { host_ids: hostIds, dimensions })
}

// SSE 流式获取对比分析结果
export function streamCompare(taskId, onProgress, onComplete, onError) {
  const token = localStorage.getItem('ir_token')
  const baseURL = request.defaults.baseURL || '/api'
  const url = `${baseURL}/ai/analyze/compare/${taskId}/stream?token=${encodeURIComponent(token || '')}`

  const controller = new AbortController()
  let completed = false
  let lastActivity = Date.now()
  let hasResult = false

  // 安全网：8秒无活动且有结果 → 自动完成
  const idleCheck = setInterval(() => {
    if (!completed && hasResult && Date.now() - lastActivity > 8000) {
      completed = true
      if (onComplete) onComplete({ progress: 100, message: '分析完成' })
      controller.abort()
    }
  }, 2000)

  fetch(url, {
    headers: { Accept: 'text/event-stream', Authorization: `Bearer ${token || ''}` },
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) throw new Error(`SSE 连接失败 (HTTP ${response.status})`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = 'message'

      while (true) {
        const { done, value } = await reader.read()
        if (done) { clearInterval(idleCheck); break }
        lastActivity = Date.now()

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const t = line.trim()
          if (!t) { currentEvent = 'message'; continue }
          if (t.startsWith('event:')) { currentEvent = t.slice(6).trim(); continue }
          if (!t.startsWith('data:')) continue
          const dataStr = t.slice(5).trim()
          if (!dataStr) continue
          try {
            const payload = JSON.parse(dataStr)
            if (currentEvent === 'progress' && onProgress) { onProgress(payload) }
            else if (currentEvent === 'content' && onProgress) { onProgress(payload); hasResult = true }
            else if (currentEvent === 'complete' && onComplete) { completed = true; onComplete(payload) }
            else if (currentEvent === 'error' && onError) { onError(payload) }
          } catch { /* ignore */ }
        }
      }
    })
    .catch((err) => {
      clearInterval(idleCheck)
      if (err.name !== 'AbortError') {
        if (!completed && onComplete) { completed = true; onComplete({ progress: 100, message: '连接已关闭' }) }
        if (onError) onError({ message: err.message || 'SSE 连接异常' })
      }
    })

  return controller
}

// ============================================================
// P2: Provider 选项
// ============================================================

// 获取可用的 AI Provider 列表
export function getProviderOptions() {
  return request.get('/ai/provider-options')
}
