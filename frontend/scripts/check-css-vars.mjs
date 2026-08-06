/**
 * CSS 自定义属性「引用 ⨯ 定义」差集校验。
 *
 * 相比按名匹配已知失效令牌黑名单（易出现「换一个新幽灵令牌」的漏网），
 * 本脚本做的是全集差集：
 *   未定义令牌 = (目标文件中所有 var(--x) 引用) - (全仓所有 --x: 定义)
 *
 * 定义来源包含：
 *   1. 项目 CSS/SCSS 中的 `--x: value` 声明
 *   2. JS/TS 中以字符串形式声明的令牌键（如 config/themes.js 的预设色板、
 *      stores/theme.js 里 setProperty 的键），这些在运行时注入到 :root
 *   3. Element Plus 自带的 `--el-*` 命名空间（第三方库定义，视为已定义）
 *
 * 退出码 0 表示零未定义令牌。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, extname } from 'node:path'

/** 需要校验引用的目标文件（本次去 AI 感改造范围内的 10 个文件） */
const TARGET_FILES = [
  'src/views/AiView.vue',
  'src/views/settings/SettingsLayout.vue',
  'src/views/settings/UserManagement.vue',
  'src/views/settings/AuditLogView.vue',
  'src/views/settings/AgentManagement.vue',
  'src/views/settings/DataStorageView.vue',
  'src/views/settings/SystemParamsView.vue',
  'src/views/settings/ThemeCustomizeView.vue',
  'src/components/settings/SettingsStatCard.vue',
  'src/utils/themeColor.js',
]

/** 扫描定义来源的根目录 */
const SCAN_ROOTS = ['src']

/** 参与扫描的文件扩展名 */
const SCAN_EXTS = new Set(['.css', '.scss', '.vue', '.js', '.ts'])

/** 视为「由第三方库定义」的令牌前缀，跳过校验 */
const EXTERNAL_PREFIXES = ['--el-']

/**
 * 递归收集目录下所有待扫描文件的绝对路径。
 * @param {string} dir 起始目录
 * @param {string[]} acc 累加器
 * @returns {string[]} 文件路径列表
 */
function walk(dir, acc = []) {
  let entries = []
  try {
    entries = readdirSync(dir)
  } catch (e) {
    return acc
  }
  for (const name of entries) {
    if (name === 'node_modules' || name === 'dist' || name.startsWith('.')) continue
    const full = join(dir, name)
    let st = null
    try {
      st = statSync(full)
    } catch (e) {
      continue
    }
    if (st.isDirectory()) {
      walk(full, acc)
    } else if (SCAN_EXTS.has(extname(name))) {
      acc.push(full)
    }
  }
  return acc
}

/**
 * 从全仓收集所有「已定义」的 CSS 自定义属性名。
 * @returns {Set<string>} 已定义令牌集合
 */
function collectDefined() {
  const defined = new Set()
  const files = SCAN_ROOTS.flatMap((r) => walk(r))
  for (const file of files) {
    let text = ''
    try {
      text = readFileSync(file, 'utf8')
    } catch (e) {
      continue
    }
    // 形态 1：CSS 声明 `--x: value`
    for (const m of text.matchAll(/(--[A-Za-z0-9_-]+)\s*:/g)) {
      defined.add(m[1])
    }
    // 形态 2：JS 字符串键 '--x' / "--x"（预设色板、setProperty 调用）
    for (const m of text.matchAll(/['"](--[A-Za-z0-9_-]+)['"]/g)) {
      defined.add(m[1])
    }
  }
  return defined
}

/**
 * 将注释内容替换为等长空白，避免 JSDoc/CSS 注释里书写的示例令牌
 * （如 `var(--color-*)`）被误报为真实引用，同时保持行号不变。
 * @param {string} text 源文本
 * @returns {string} 注释已置空的文本
 */
function stripComments(text) {
  // 块注释 /* ... */ 与 JSDoc，逐字符保留换行以维持行号
  let out = text.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
  // 行注释 //（跳过 http:// 这类协议前缀）
  out = out.replace(/(^|[^:])\/\/[^\n]*/g, (m, p1) => p1 + ' '.repeat(m.length - p1.length))
  // HTML/Vue 模板注释
  out = out.replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ' '))
  return out
}

/**
 * 从目标文件中收集所有 var() 引用及其出现位置（已排除注释内的示例）。
 * @returns {Array<{token: string, file: string, line: number}>} 引用列表
 */
function collectReferences() {
  const refs = []
  for (const file of TARGET_FILES) {
    let text = ''
    try {
      text = readFileSync(file, 'utf8')
    } catch (e) {
      console.error(`[warn] 无法读取目标文件: ${file}`)
      continue
    }
    const lines = stripComments(text).split(/\r?\n/)
    lines.forEach((line, idx) => {
      for (const m of line.matchAll(/var\(\s*(--[A-Za-z0-9_-]+)/g)) {
        refs.push({ token: m[1], file, line: idx + 1 })
      }
    })
  }
  return refs
}

const defined = collectDefined()
const refs = collectReferences()

const missing = refs.filter(
  (r) => !defined.has(r.token) && !EXTERNAL_PREFIXES.some((p) => r.token.startsWith(p))
)

const uniqueRefs = new Set(refs.map((r) => r.token))
console.log(`已定义令牌总数: ${defined.size}`)
console.log(`目标文件 var() 引用: ${refs.length} 处 / ${uniqueRefs.size} 个唯一令牌`)

if (missing.length === 0) {
  console.log('\n✓ PASS — 目标文件内零未定义令牌')
  process.exit(0)
}

console.log(`\n✗ FAIL — 发现 ${missing.length} 处未定义令牌引用:`)
for (const m of missing) {
  console.log(`  ${m.file}:${m.line}  ${m.token}`)
}
process.exit(1)
