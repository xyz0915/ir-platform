/**
 * 主题令牌读取工具
 *
 * ECharts 的 option 是纯 JS 对象，无法解析 CSS 的 `var(--color-*)`，
 * 这正是图表配色历史上被硬编码为 `#409eff` / `#67c23a` 的根因。
 * 本模块在「构建 option 时」把设计令牌解析为具体色值，
 * 从而让图表跟随 `stores/theme.js` 的主题切换自动变色。
 *
 * 使用约束（ir-ui-design-system）：
 * - 只返回中性灰阶 + 单一强调色，**不返回任何渐变**；
 * - 调用方不得再出现硬编码色值。
 */

/**
 * 读取挂在 `document.documentElement` 上的 CSS 自定义属性。
 *
 * @param {string} name     CSS 变量名，必须以 `--` 开头，例如 `--color-accent-fg`
 * @param {string} fallback 变量未定义（或非浏览器环境）时的兜底色值
 * @returns {string} 解析后的色值字符串；解析失败时返回 fallback
 */
export function cssVar(name, fallback = '') {
  if (typeof name !== 'string' || name.length === 0) return fallback
  try {
    if (typeof window === 'undefined' || typeof document === 'undefined') return fallback
    const value = getComputedStyle(document.documentElement).getPropertyValue(name)
    return (value || '').trim() || fallback
  } catch (e) {
    return fallback
  }
}

/**
 * @typedef {Object} ChartPalette
 * @property {string} primary   主序列颜色（强调色，每图至多一条主线）
 * @property {string} secondary 副序列颜色（中性灰）
 * @property {string} text      轴标签 / 图例文字色
 * @property {string} split     网格线 / 轴线颜色
 */

/**
 * 返回图表调色板（中性灰阶 + 单一强调色，无渐变）。
 *
 * fallback 值与 `assets/styles/theme.css` 的 `:root` 亮色令牌保持一致，
 * 保证 SSR / 单测等无 DOM 环境下仍能拿到合法配色。
 *
 * @returns {ChartPalette}
 */
export function chartPalette() {
  return {
    primary: cssVar('--color-accent-fg', '#2563eb'),
    secondary: cssVar('--color-fg-subtle', '#888888'),
    text: cssVar('--color-fg-muted', '#555555'),
    split: cssVar('--color-border-default', '#e5e5e5'),
  }
}

export default { cssVar, chartPalette }
