/**
 * useAgentTheme —— SecOps 暗色主题控制器。
 *
 * - 默认暗色（SecOps 惯例），可切亮色并持久化（键名 aop:app-prefs 与 demo 一致，便于数据迁移）。
 * - 复用现有 Element Plus 主题机制：暗色映射到平台内置 'dark' 预设，亮色映射到 'classic' 预设，
 *   通过 themeStore.setTheme 应用 --color-* 变量，不写死色值，与 GraphPanel 等组件一致。
 *
 * 设计依据：01-arch-design.md §6.5 / T2。
 */
import { ref, watch } from 'vue'
import { useThemeStore } from '@/stores/theme'

const STORAGE_KEY = 'aop:app-prefs'

function loadPersist() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function savePersist(data) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    /* 忽略持久化失败（预览态） */
  }
}

const persisted = loadPersist()
const mode = ref(persisted.mode || 'dark')
const role = ref(persisted.role || 'analyst')

const themeStore = useThemeStore()

/** 将 SecOps 模式映射到平台内置主题预设并应用 */
function applyMode(next) {
  themeStore.setTheme(next === 'dark' ? 'dark' : 'classic')
  savePersist({ mode: next, role: role.value })
}

function setMode(next) {
  mode.value = next
  applyMode(next)
}

function setRole(next) {
  role.value = next
  savePersist({ mode: mode.value, role: next })
}

function toggleMode() {
  setMode(mode.value === 'dark' ? 'light' : 'dark')
}

// 监听外部（如全局顶栏主题切换）变化时同步 SecOps 偏好
watch(
  () => themeStore.themeName,
  (name) => {
    const next = name === 'dark' ? 'dark' : 'light'
    if (next !== mode.value) {
      mode.value = next
      savePersist({ mode: next, role: role.value })
    }
  }
)

export function useAgentTheme() {
  return { mode, role, setMode, setRole, toggleMode }
}
