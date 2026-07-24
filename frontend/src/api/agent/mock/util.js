/**
 * Mock 适配层公共工具 —— 镜像 demo mocks/util.ts
 *
 * 所有 mock 函数返回与后端同构的响应信封 { code, data, message }，
 * 因此业务 store 无需区分数据来自 Mock 还是真实后端。
 */

/** 模拟网络延迟（100–400ms 随机），贴近真实 API 体感。 */
export const delay = (min = 100, max = 400) =>
  new Promise((resolve) => setTimeout(resolve, Math.floor(min + Math.random() * (max - min))))

/** 深拷贝，避免组件修改污染原始 mock 常量。 */
export const clone = (value) => JSON.parse(JSON.stringify(value))

/** 统一响应包装（模拟 API 返回结构）。 */
export const ok = (data, message = 'ok') => ({ code: 0, data, message })

/** 可选错误模拟（默认关闭，Vitest 异常路径测试可开启）。 */
export const THROW_ON = { rate: 0, map: {} }

/** 当前时间的 ISO 8601 字符串。 */
export const nowISO = () => new Date().toISOString()

/** 相对当前时间偏移若干分钟，返回 ISO 字符串。 */
export const isoMinutesAgo = (minutes) =>
  new Date(Date.now() - minutes * 60 * 1000).toISOString()

/** 转义正则特殊字符（用于 action_pattern 通配匹配）。 */
export const escapeRegExp = (s) => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')
