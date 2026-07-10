import { defineStore } from 'pinia'

/**
 * 主题状态：light | dark
 * - 持久化到 localStorage('ir-theme')
 * - 与 <html class="dark"> 同步，供 Element Plus 暗色变量与 theme.css 生效
 */
export const useThemeStore = defineStore('theme', {
  state: () => ({
    theme: localStorage.getItem('ir-theme') || 'light'
  }),
  actions: {
    /** 应用启动时调用：从 localStorage 恢复主题，确保与 DOM 一致 */
    initTheme() {
      const saved = localStorage.getItem('ir-theme') || 'light'
      this.theme = saved
      document.documentElement.classList.toggle('dark', saved === 'dark')
    },
    /** 切换亮/暗并持久化 + 同步 DOM */
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark'
      localStorage.setItem('ir-theme', this.theme)
      document.documentElement.classList.toggle('dark', this.theme === 'dark')
    }
  }
})
