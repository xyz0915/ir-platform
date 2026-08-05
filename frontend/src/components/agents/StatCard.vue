<template>
  <div class="stat-card" :style="{ borderTopColor: color }">
    <div class="sc-icon" :style="{ background: color + '1A', color }" v-if="icon">
      <el-icon :size="20"><component :is="icon" /></el-icon>
    </div>
    <div class="sc-body">
      <div class="sc-value" :style="{ color }">{{ value }}</div>
      <div class="sc-title">{{ title }}</div>
      <div class="sc-trend" v-if="trend !== null && trend !== undefined">
        <el-icon :size="12"><component :is="trendUp ? Top : Bottom" /></el-icon>
        {{ trendLabel }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Top, Bottom } from '@element-plus/icons-vue'

const props = defineProps({
  title: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  icon: { type: [Object, Function, String], default: null },
  color: { type: String, default: '#111827' },
  /** 趋势值（如 +3 / -1），数值型按正负着色 */
  trend: { type: [Number, String], default: null },
})

const trendUp = computed(() => {
  const n = typeof props.trend === 'number' ? props.trend : Number(String(props.trend).replace(/[+%]/g, ''))
  return n >= 0
})

const trendLabel = computed(() => {
  if (props.trend === null || props.trend === undefined || props.trend === '') return ''
  return typeof props.trend === 'number' ? `${props.trend > 0 ? '+' : ''}${props.trend}` : String(props.trend)
})
</script>

<style scoped>
.stat-card {
  position: relative;
  flex: 1;
  min-width: 160px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-top: 3px solid #111827;
  border-radius: 10px;
}
.sc-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.sc-body { min-width: 0; }
.sc-value { font-size: 24px; font-weight: 700; line-height: 1.2; color: var(--color-fg-default); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: -0.3px; }
.sc-title { font-size: 12px; color: var(--color-fg-muted); margin-top: 2px; }
.sc-trend { font-size: 11px; color: var(--color-fg-subtle); display: inline-flex; align-items: center; gap: 2px; margin-top: 2px; }
</style>
