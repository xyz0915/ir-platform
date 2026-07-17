/**
 * 四套内置主题定义
 * 每套主题覆盖全部的 --color-* CSS 变量
 * 自定义主题通过 themeStore 动态覆写
 */
export const THEME_PRESETS = {
  classic: {
    name: '古典型',
    nameEn: 'Classic',
    description: '中性专业，高对比，适配标准办公环境',
    accent: '#2563eb',  // 品牌色预览用
    colors: {
      '--color-canvas-default': '#ffffff',
      '--color-canvas-subtle': '#fafafa',
      '--color-canvas-inset': '#f5f5f5',
      '--color-fg-default': '#111111',
      '--color-fg-muted': '#555555',
      '--color-fg-subtle': '#888888',
      '--color-fg-light': '#a3a3a3',
      '--color-border-default': '#e5e5e5',
      '--color-accent-fg': '#2563eb',
      '--color-accent-emphasis': '#2563eb',
      '--color-accent-subtle': '#eff6ff',
      '--color-danger-fg': '#dc2626',
      '--color-success-fg': '#16a34a',
      '--color-warning-fg': '#d97706',
      '--color-sidebar-bg': '#ffffff',
      '--color-sidebar-fg': '#111111',
      '--color-sidebar-fg-muted': '#555555',
      '--color-sidebar-border': '#e5e5e5',
      '--color-sidebar-hover-bg': '#f5f5f5',
      '--color-sidebar-active-bg': '#eff6ff',
    }
  },
  dark: {
    name: '暗夜型',
    nameEn: 'Dark',
    description: '暖灰基底 + 靛蓝点缀，护眼舒适，适合长时间操作',
    accent: '#818cf8',
    colors: {
      '--color-canvas-default': '#161618',
      '--color-canvas-subtle': '#1e1e20',
      '--color-canvas-inset': '#121214',
      '--color-fg-default': '#d4d4d8',
      '--color-fg-muted': '#a1a1aa',
      '--color-fg-subtle': '#71717a',
      '--color-fg-light': '#52525b',
      '--color-border-default': '#27272a',
      '--color-accent-fg': '#818cf8',
      '--color-accent-emphasis': '#6366f1',
      '--color-accent-subtle': '#1e1a3a',
      '--color-danger-fg': '#fb7185',
      '--color-success-fg': '#34d399',
      '--color-warning-fg': '#f59e0b',
      '--color-sidebar-bg': '#161618',
      '--color-sidebar-fg': '#d4d4d8',
      '--color-sidebar-fg-muted': '#a1a1aa',
      '--color-sidebar-border': '#27272a',
      '--color-sidebar-hover-bg': '#1e1e20',
      '--color-sidebar-active-bg': '#1e1a3a',
    }
  },
  ocean: {
    name: '深海型',
    nameEn: 'Ocean',
    description: '深海海军蓝基底 + 冰蓝点缀，沉稳专业的 SOC 大屏感',
    accent: '#5ba4e8',
    colors: {
      '--color-canvas-default': '#0c1220',
      '--color-canvas-subtle': '#131d2e',
      '--color-canvas-inset': '#080e1a',
      '--color-fg-default': '#c8d8f0',
      '--color-fg-muted': '#8aa0c0',
      '--color-fg-subtle': '#6a88aa',
      '--color-fg-light': '#3a5a7a',
      '--color-border-default': '#1e3050',
      '--color-accent-fg': '#5ba4e8',
      '--color-accent-emphasis': '#4a93d8',
      '--color-accent-subtle': 'rgba(91,164,232,0.08)',
      '--color-danger-fg': '#e07070',
      '--color-success-fg': '#4ac0c0',
      '--color-warning-fg': '#d4a040',
      '--color-sidebar-bg': '#0c1220',
      '--color-sidebar-fg': '#c8d8f0',
      '--color-sidebar-fg-muted': '#6a88aa',
      '--color-sidebar-border': '#1e3050',
      '--color-sidebar-hover-bg': '#131d2e',
      '--color-sidebar-active-bg': 'rgba(91,164,232,0.08)',
    }
  },
  titanium: {
    name: '钛金型',
    nameEn: 'Titanium',
    description: '暖灰基底 + 哑光金色点缀，克制轻奢的高级质感',
    accent: '#bfa055',
    colors: {
      '--color-canvas-default': '#141416',
      '--color-canvas-subtle': '#1c1c20',
      '--color-canvas-inset': '#0a0a0c',
      '--color-fg-default': '#d4d4d8',
      '--color-fg-muted': '#a1a1aa',
      '--color-fg-subtle': '#71717a',
      '--color-fg-light': '#52525b',
      '--color-border-default': '#2e2e32',
      '--color-accent-fg': '#bfa055',
      '--color-accent-emphasis': '#a88840',
      '--color-accent-subtle': 'rgba(191,160,85,0.08)',
      '--color-danger-fg': '#d06060',
      '--color-success-fg': '#50a080',
      '--color-warning-fg': '#c89030',
      '--color-sidebar-bg': '#141416',
      '--color-sidebar-fg': '#d4d4d8',
      '--color-sidebar-fg-muted': '#71717a',
      '--color-sidebar-border': '#2e2e32',
      '--color-sidebar-hover-bg': '#1c1c20',
      '--color-sidebar-active-bg': 'rgba(191,160,85,0.08)',
    }
  }
}

/** 自定义主题默认颜色 */
export const CUSTOM_THEME_DEFAULTS = {
  '--color-canvas-default': '#ffffff',
  '--color-canvas-subtle': '#fafafa',
  '--color-fg-default': '#111111',
  '--color-border-default': '#e5e5e5',
  '--color-accent-fg': '#2563eb',
}

/** 可自定义的颜色键列表（供颜色选择器使用） */
export const CUSTOMIZABLE_COLORS = [
  { key: '--color-accent-fg', label: '品牌色', default: '#2563eb' },
  { key: '--color-canvas-default', label: '背景色', default: '#ffffff' },
  { key: '--color-fg-default', label: '文字色', default: '#111111' },
  { key: '--color-border-default', label: '边框色', default: '#e5e5e5' },
  { key: '--color-canvas-subtle', label: '浅底色', default: '#fafafa' },
]
