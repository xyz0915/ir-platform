// R2-3 只读派发 API 封装（v1.3.0 作战化）
// 对应后端 /api/ai 下的 dispatch-readonly / dispatch 路由
// 红线：仅接收 auto_runnable=true 的只读采集动作；绝不自动处置

import request from './index'

// 派发只读采集（返回 { task_id, status } 供轮询）
export function dispatchReadonly(hostId, payload) {
  // payload: { action_type, target, command_or_api, auto_runnable }
  return request.post(`/ai/analyze/${hostId}/dispatch-readonly`, payload)
}

// 轮询派发任务状态（含采集证据）
export function getDispatchStatus(taskId) {
  return request.get(`/ai/dispatch/${taskId}`)
}

// 取消正在执行的派发（仅中断采集，绝不 kill/隔离主机）
export function cancelDispatch(taskId) {
  return request.post(`/ai/dispatch/${taskId}/cancel`)
}
