<template>
  <div class="related-alerts" v-if="alerts && alerts.length">
    <div class="ra-title">关联告警</div>
    <div class="ra-list">
      <div v-for="(alert, i) in alerts" :key="alert.id || i" class="ra-item">
        <span class="ra-name">{{ alert.name || alert.rule_name || ('告警#' + (i + 1)) }}</span>
        <span class="ra-time">{{ formatTime(alert.timestamp) }}</span>
        <span class="ra-sev" :class="'ra-sev-' + (alert.severity || 'info')">{{ alert.severity }}</span>
      </div>
    </div>
  </div>
  <!-- 数据不可用时降级隐藏 -->
</template>

<script setup>
const props = defineProps({
  alerts: { type: Array, default: () => [] },
})

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.related-alerts {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 10px;
}
.ra-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 8px;
}
.ra-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ra-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background: var(--color-canvas-inset);
  border-radius: 4px;
  font-size: 11px;
}
.ra-name {
  flex: 1;
  color: var(--color-fg-default);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ra-time {
  font-size: 10px;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
}
.ra-sev {
  font-size: 9px;
  padding: 0 4px;
  border-radius: 2px;
}
.ra-sev-critical, .ra-sev-high { background: rgba(220,38,38,0.1); color: #dc2626; }
.ra-sev-medium { background: rgba(217,119,6,0.1); color: #d97706; }
.ra-sev-low { background: rgba(37,99,235,0.1); color: #2563eb; }
</style>
