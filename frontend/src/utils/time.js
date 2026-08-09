/** 时间工具 — 时间格式化。
 *
 * 后端持久化时间字段（created_at / updated_at / analyzed_at 等）由 datetime('now') 生成，
 * 存的是 UTC 纯字符串 'YYYY-MM-DD HH:MM:SS'（无时区标记）。
 * 展示后端时间一律用 formatServerTime：按 UTC 解析后转本地，否则会偏差 8 小时。
 * formatLocalTime / quickRangeValue / todayStart 仅用于前端本地时间场景。
 */

import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)

/** 带时区标记（Z 或 ±HH:MM）的 ISO 字符串判定 */
const TZ_SUFFIX_RE = /[zZ]$|[+-]\d{2}:?\d{2}$/

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
 * 将后端返回的 UTC 时间字符串格式化为本地时间显示。
 * 后端时间字段（created_at 等）存的是 datetime('now') 的 UTC 纯字符串（无时区标记）。
 * 必须按 UTC 解析再转本地，否则会偏差 8 小时。
 * @param {string|Date|number} t 时间值；已带时区标记(Z/+HH:MM)的 ISO 字符串也会正确转本地
 * @param {string} [fmt='YYYY-MM-DD HH:mm:ss'] 输出格式
 * @returns {string} 本地时间字符串；非法输入返回 ''
 */
export function formatServerTime(t, fmt = 'YYYY-MM-DD HH:mm:ss') {
  const d = parseServerTime(t)
  return d ? dayjs(d).format(fmt) : ''
}

/**
 * 将后端时间值解析为 Date（绝对时间点），用于相对时间 / 时间差计算。
 * 与 formatServerTime 同一套规则。
 * @param {string|Date|number} t 时间值
 * @returns {Date|null} 非法输入返回 null
 */
export function parseServerTime(t) {
  if (t === null || t === undefined || t === '') return null
  // Date / 时间戳本身已是绝对时间点，直接采用
  if (t instanceof Date) return Number.isNaN(t.getTime()) ? null : t
  if (typeof t === 'number') {
    const d = new Date(t)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const s = String(t).trim()
  // 已带时区标记（ISO8601，带 Z 或 ±HH:MM）→ 当作该时区的时间点解析
  // 后端纯字符串（如 '2026-08-07 12:08:44'，无时区）→ 当作 UTC 解析
  const d = TZ_SUFFIX_RE.test(s) ? dayjs(s) : dayjs.utc(s)
  return d.isValid() ? d.toDate() : null
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
