import { defineStore } from 'pinia'
import { THEME_PRESETS, CUSTOM_THEME_DEFAULTS } from '@/config/themes'
import { ref, computed } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  // 状态
  const themeName = ref(localStorage.getItem('ir-theme-name') || 'classic')
  const customColors = ref(JSON.parse(localStorage.getItem('ir-theme-custom') || '{}'))

  // 兼容旧有 theme 属性（AppLayout.vue 模板引用 themeStore.theme）
  const theme = computed(() => themeName.value === 'dark' ? 'dark' : 'light')

  // 计算当前主题色板（如果是 custom 则合并自定义颜色）
  const effectiveColors = computed(() => {
    if (themeName.value === 'custom') {
      return { ...CUSTOM_THEME_DEFAULTS, ...customColors.value }
    }
    const preset = THEME_PRESETS[themeName.value]
    return preset ? preset.colors : THEME_PRESETS.classic.colors
  })

  // 当前预设配置
  const currentPreset = computed(() => THEME_PRESETS[themeName.value] || THEME_PRESETS.classic)

  // 应用主题：把所有 CSS 变量 setProperty 到 document.documentElement
  function applyTheme() {
    const colors = effectiveColors.value
    const root = document.documentElement
    for (const [key, value] of Object.entries(colors)) {
      root.style.setProperty(key, value)
    }
    // 同步暗色 class（经典/暗夜兼容现有 dark 切换）
    root.classList.toggle('dark', themeName.value === 'dark')
    localStorage.setItem('ir-theme-name', themeName.value)
  }

  // 切换主题
  function setTheme(name) {
    themeName.value = name
    applyTheme()
  }

  // 更新自定义颜色
  function updateCustomColor(key, value) {
    customColors.value = { ...customColors.value, [key]: value }
    localStorage.setItem('ir-theme-custom', JSON.stringify(customColors.value))
    applyTheme()
  }

  // 重置自定义颜色
  function resetCustomColors() {
    customColors.value = {}
    localStorage.removeItem('ir-theme-custom')
    applyTheme()
  }

  // 初始化
  function initTheme() {
    applyTheme()
  }

  // 兼容旧有 toggleTheme（dark ↔ classic 切换）
  function toggleTheme() {
    const next = themeName.value === 'dark' ? 'classic' : 'dark'
    setTheme(next)
  }

  return {
    themeName, customColors, effectiveColors, currentPreset, theme,
    setTheme, updateCustomColor, resetCustomColors, initTheme, toggleTheme,
  }
})
