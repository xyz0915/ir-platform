<template>
  <div class="theme-customize">
    <div class="section-title">选择主题风格</div>
    <div class="theme-grid">
      <div
        v-for="(preset, key) in THEME_PRESETS"
        :key="key"
        :class="['theme-card', { active: themeStore.themeName === key }]"
        @click="themeStore.setTheme(key)"
      >
        <div class="preview-strip" :style="{ background: preset.colors['--color-canvas-default'] }">
          <div class="preview-nav" :style="{ background: preset.colors['--color-sidebar-bg'], borderBottom: `0.5px solid ${preset.colors['--color-border-default']}` }">
            <div class="preview-logo" :style="{ background: preset.accent, width: 16, height: 16, borderRadius: 3 }"></div>
            <div class="preview-dot" :style="{ background: preset.colors['--color-accent-fg'], width: 20, height: 3, borderRadius: 2 }"></div>
          </div>
          <div class="preview-body">
            <div class="preview-card" :style="{ background: preset.colors['--color-canvas-subtle'], border: `0.5px solid ${preset.colors['--color-border-default']}` }"></div>
          </div>
        </div>
        <div class="theme-info">
          <div class="theme-name">{{ preset.name }}</div>
          <div class="theme-name-en">{{ preset.nameEn }}</div>
          <div class="theme-desc">{{ preset.description }}</div>
        </div>
        <div v-if="themeStore.themeName === key" class="theme-checked">
          <svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="8" :fill="preset.accent"/><path d="M5 8l2 2 4-4" stroke="#fff" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </div>
      </div>
    </div>

    <!-- 自定义主题 -->
    <div class="section-title" style="margin-top: 28px;">自定义主题</div>
    <div :class="['custom-section', { expanded: themeStore.themeName === 'custom' }]">
      <div class="custom-trigger" @click="themeStore.setTheme('custom')">
        <div class="custom-preview">
          <div v-for="c in CUSTOMIZABLE_COLORS" :key="c.key"
               class="custom-dot"
               :style="{ background: themeStore.customColors[c.key] || c.default }"></div>
        </div>
        <div class="custom-info">
          <div class="theme-name">自定义主题</div>
          <div class="theme-desc">自由调整品牌色、背景、文字、边框等核心颜色</div>
        </div>
        <div v-if="themeStore.themeName === 'custom'" class="theme-checked">
          <svg width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="8" fill="#d4a54a"/><path d="M5 8l2 2 4-4" stroke="#fff" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </div>
      </div>

      <div v-if="themeStore.themeName === 'custom'" class="custom-colors">
        <div v-for="c in CUSTOMIZABLE_COLORS" :key="c.key" class="color-row">
          <label class="color-label">{{ c.label }}</label>
          <div class="color-controls">
            <input type="color" :value="themeStore.customColors[c.key] || c.default"
                   @input="themeStore.updateCustomColor(c.key, $event.target.value)"
                   class="color-picker" />
            <input type="text" :value="themeStore.customColors[c.key] || c.default"
                   @input="themeStore.updateCustomColor(c.key, $event.target.value)"
                   class="color-input" />
          </div>
        </div>
        <el-button size="small" @click="themeStore.resetCustomColors()" style="margin-top: 12px;">恢复默认</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useThemeStore } from '@/stores/theme'
import { THEME_PRESETS, CUSTOMIZABLE_COLORS } from '@/config/themes'
const themeStore = useThemeStore()
</script>

<style scoped>
.theme-customize { max-width: 720px; }
.section-title { font-size: 14px; font-weight: 500; color: var(--color-text-primary, #111); margin-bottom: 14px; }
.theme-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.theme-card {
  position: relative; border-radius: 10px; border: 1.5px solid var(--color-border-secondary, #e0e0e0);
  overflow: hidden; cursor: pointer; transition: border-color 0.15s;
  background: var(--color-background-primary, #fff);
}
.theme-card:hover { border-color: var(--color-text-info, #409eff); }
.theme-card.active { border-color: var(--color-accent-fg, #2563eb); }
.preview-strip { height: 64px; padding: 8px; display: flex; flex-direction: column; gap: 4px; }
.preview-nav { height: 16px; border-radius: 4px; display: flex; align-items: center; gap: 6px; padding: 0 6px; }
.preview-body { flex: 1; display: flex; align-items: center; justify-content: center; }
.preview-card { width: 60%; height: 20px; border-radius: 4px; }
.theme-info { padding: 10px 10px 12px; }
.theme-name { font-size: 13px; font-weight: 500; color: var(--color-text-primary, #111); }
.theme-name-en { font-size: 11px; color: var(--color-text-tertiary, #888); margin-bottom: 4px; }
.theme-desc { font-size: 11px; color: var(--color-text-tertiary, #888); line-height: 1.4; }
.theme-checked { position: absolute; top: 8px; right: 8px; }
.custom-section { border-radius: 10px; border: 1.5px solid var(--color-border-secondary, #e0e0e0); overflow: hidden; }
.custom-section.expanded { border-color: var(--color-accent-fg, #d4a54a); }
.custom-trigger { display: flex; align-items: center; gap: 14px; padding: 16px; cursor: pointer; background: var(--color-background-primary, #fff); }
.custom-preview { display: flex; gap: 4px; }
.custom-dot { width: 18px; height: 18px; border-radius: 50%; border: 0.5px solid rgba(0,0,0,0.1); }
.custom-info { flex: 1; }
.custom-colors { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 10px; }
.color-row { display: flex; align-items: center; gap: 12px; }
.color-label { width: 60px; font-size: 12px; color: var(--color-text-secondary, #666); flex-shrink: 0; }
.color-controls { display: flex; align-items: center; gap: 8px; }
.color-picker { width: 32px; height: 32px; border: none; padding: 0; cursor: pointer; border-radius: 4px; }
.color-input { width: 100px; height: 28px; border: 0.5px solid var(--color-border-default, #ddd); border-radius: 4px; padding: 0 8px; font-size: 12px; font-family: 'JetBrains Mono', monospace; }
</style>
