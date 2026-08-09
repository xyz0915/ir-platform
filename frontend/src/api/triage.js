import request from './index'

/**
 * 动态取证任务 API（应急动态取证方案 Phase 2 / 方案 A 轮询通道）.
 *
 * 取证范围枚举（与后端 ALLOWED_SCOPE 对齐）：
 *   - file_hashes      文件哈希快照（追加写，不覆盖存量）
 *   - network          实时网络连接
 *   - process_subtree  进程子树（定向采集）
 * 默认三项全勾（见 docs/应急动态取证方案.md 阶段二）。
 */
export const TRIAGE_SCOPE_OPTIONS = [
  { value: 'file_hashes', label: '文件哈希', desc: '对当前运行进程加载的模块做哈希快照' },
  { value: 'network', label: '实时网络连接', desc: '采集 daemon 轮询时刻的主机网络连接' },
  { value: 'process_subtree', label: '进程子树', desc: '定向采集进程启动链/子树' },
]

export const DEFAULT_TRIAGE_SCOPE = ['file_hashes', 'network', 'process_subtree']

export default {
  /** 平台侧：下发动态取证任务 */
  create(hostId, scope) {
    return request.post(`/hosts/${hostId}/triage-tasks`, { scope })
  },
  /** 平台侧：查询主机的取证任务列表 */
  list(hostId) {
    return request.get(`/hosts/${hostId}/triage-tasks`)
  }
}
