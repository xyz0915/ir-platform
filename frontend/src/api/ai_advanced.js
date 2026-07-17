import request from './index'

// 1. 语义告警降噪与事件归并
export function correlateIncidents(params = {}) {
  return request.post('/ai/correlate-incidents', null, { params })
}

// 2. 自然语言指挥台
export function aiQuery(params = {}) {
  // params 可以是字符串（向后兼容）或对象（含 query, start_time, end_time, host_id 等）
  if (typeof params === 'string') {
    return request.post('/ai/query', null, { params: { query: params } })
  }
  return request.post('/ai/query', null, { params })
}

// 3. 攻击故事讲述
export function narrateIncident(params = {}) {
  return request.post('/ai/narrate-incident', null, { params })
}

// 4. 误报自学习
export function markFalsePositive(alertId, reason = '') {
  return request.post('/ai/false-positive', null, { params: { alert_id: alertId, reason } })
}
export function getFalsePositives(page = 1) {
  return request.get('/ai/false-positives', { params: { page } })
}
export function deleteFalsePositive(id) {
  return request.delete(`/ai/false-positives/${id}`)
}

// 5. 预测性沦陷预警
export function getRiskRanking() {
  return request.get('/ai/risk-ranking')
}

// ============================================================
// 6. SSE 流式自然语言查询 — 通过 fetch + ReadableStream 消费 SSE 流
// ============================================================
/**
 * SSE 流式自然语言查询 — 通过 fetch + ReadableStream 消费 SSE 流
 * @param {string} query - 用户输入
 * @param {string} sessionId - 会话 ID
 * @param {object} options - 可选参数 { host_id, start_time, end_time }
 * @param {function} onTextChunk - 文本块回调 (text)
 * @param {function} onCard - 富卡片回调 (cardType, data)
 * @param {function} onActionConfirm - 操作确认回调 (action, target, confirmId)
 * @param {function} onActionResult - 操作结果回调 (action, status, result)
 * @param {function} onProgress - 剧本进度回调 (step, total, name, status)
 * @param {function} onEnd - 流结束回调 (usage, confidence)
 * @param {function} onError - 错误回调 (error)
 * @returns {function} abort - 调用可中断 SSE 流
 */
export function aiQueryStream(query, sessionId, options = {}, callbacks = {}) {
  const {
    onTextChunk = () => {},
    onCard = () => {},
    onActionConfirm = () => {},
    onActionResult = () => {},
    onProgress = () => {},
    onEnd = () => {},
    onError = () => {},
  } = callbacks

  const params = new URLSearchParams({ query, session_id: sessionId })
  if (options.host_id) params.set('host_id', options.host_id)
  if (options.start_time) params.set('start_time', options.start_time)
  if (options.end_time) params.set('end_time', options.end_time)

  const url = `/api/ai/query-stream?${params.toString()}`
  const controller = new AbortController()
  const token = localStorage.getItem('ir_token') || ''

  fetch(url, {
    signal: controller.signal,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      function processChunk() {
        reader.read().then(({ done, value }) => {
          if (done) return
          buffer += decoder.decode(value, { stream: true })
          // 按 \n\n 分割 SSE 事件
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const part of parts) {
            const lines = part.split('\n')
            let eventType = ''
            let eventData = ''
            for (const line of lines) {
              if (line.startsWith('event: ')) eventType = line.slice(7)
              if (line.startsWith('data: ')) eventData = line.slice(6)
            }
            if (!eventData) continue
            try {
              const data = JSON.parse(eventData)
              if (eventType === 'text_chunk') {
                onTextChunk(data.content || '')
              } else if (eventType === 'card') {
                onCard(data.card_type, data.data)
              } else if (eventType === 'action_confirm') {
                onActionConfirm(data.action, data.target, data.confirm_id)
              } else if (eventType === 'action_result') {
                onActionResult(data.action, data.status, data.result)
              } else if (eventType === 'playbook_progress') {
                onProgress(data.step, data.total, data.current_step_name, data.status)
              } else if (eventType === 'query_end') {
                onEnd(data.usage || {}, data.confidence || '', { exec_time_ms: data.exec_time_ms || 0, results_count: data.results_count || 0 })
              }
            } catch (e) { /* skip malformed JSON */ }
          }
          processChunk()
        }).catch(err => {
          if (err.name !== 'AbortError') onError(err.message)
        })
      }
      processChunk()
    })
    .catch(err => {
      if (err.name !== 'AbortError') onError(err.message)
    })

  return () => controller.abort()  // 返回 abort 函数
}

// 7. 执行操作（T-003 完善）
export function executeAction(action, target, confirmId = '') {
  return request.post('/ai/execute-action', null, {
    params: { action, target: JSON.stringify(target), confirm_id: confirmId }
  })
}

// ============================================================
// 8. 调查剧本 API（T-004）
// ============================================================
export function startPlaybook(playbookId, sessionId) {
  return request.post('/ai/playbook/start', null, { params: { playbook_id: playbookId, session_id: sessionId } })
}

export function getPlaybookStatus() {
  return request.get('/ai/playbook/status')
}

export function getPlaybookStep() {
  return request.get('/ai/playbook/step')
}

export function controlPlaybook(action) {
  return request.post('/ai/playbook/control', null, { params: { action } })
}

export function getSessionSummary(sessionId) {
  return request.post('/ai/session-summary', null, { params: { session_id: sessionId } })
}

// ============================================================
// 9. 文件解析（T-005）
// ============================================================
export function parseFile(filename, contentBase64) {
  return request.post('/ai/parse-file', {
    name: filename,
    content_base64: contentBase64,
  })
}

// ============================================================
// 10. 安全态势报告生成
// ============================================================
export function generateReport(query = '') {
  return request.get('/ai/generate-report', { params: { query } })
}

// ============================================================
// 11. v3.1 新功能
// ============================================================
export function submitFeedback(sessionId, query, reply, rating, comment = '') {
  return request.post('/ai/feedback', null, { params: { session_id: sessionId, query, reply, rating, comment } })
}

export function getFeedbackStats() {
  return request.get('/ai/feedback/stats')
}

export function nlUnderstand(query) {
  return request.post('/ai/nl-understand', null, { params: { query } })
}

export function getPresets() {
  return request.get('/ai/presets')
}

export function getAuditLog(days = 7) {
  return request.get('/ai/audit-log', { params: { days } })
}
