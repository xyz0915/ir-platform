/** 时间工具 — 本地时间格式化（P1-1 时间统一）。
 *
 * 库内时间契约：'YYYY-MM-DD HH:MM:SS'（服务器本地时间）。
 * 前端统一用本地时间字符串（非 UTC、无时区后缀），与后端 time_utils 对齐。
 */

/**
 * 将 Date 格式化为本地时间字符串 YYYY-MM-DD HH:mm:ss（非 UTC）。
 * @param {Date|string|number} date 日期对象 / 可解析字符串 / 时间戳
 * @returns {string} 'YYYY-MM-DD HH:mm:ss'，非法输入返回 ''
 */
export function formatLocalTime(date) {
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/**
 * 快捷时间范围起止（本地时间字符串）。
 * @param {string} key '' | '5m' | '1h' | '24h' | '7d'
 * @returns {{start: string, end: string}}
 */
export function quickRangeValue(key) {
  const end = new Date()
  const start = new Date()
  switch (key) {
    case '5m': start.setMinutes(start.getMinutes() - 5); break
    case '1h': start.setHours(start.getHours() - 1); break
    case '7d': start.setDate(start.getDate() - 7); break
    case '24h':
    default: start.setDate(start.getDate() - 1); break
  }
  return { start: formatLocalTime(start), end: formatLocalTime(end) }
}

/** 今日 0 点（用于快捷筛选「今日新增」）。@returns {string} */
export function todayStart() {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return formatLocalTime(d)
}
