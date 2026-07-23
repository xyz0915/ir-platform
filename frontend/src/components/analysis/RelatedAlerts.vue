<template>
  <div class="related-alerts" v-if="displayAlerts.length">
    <div class="ra-title">关联告警 ({{ displayAlerts.length }})</div>
    <div class="ra-list">
      <div
        v-for="(alert, i) in displayAlerts"
        :key="alert.id || i"
        class="ra-item"
        :class="alert.severity === 'high' || alert.severity === 'critical' ? 'ra-danger' : 'ra-warning'"
      >
        <div class="ra-icon">!</div>
        <div class="ra-body">
          <div class="ra-name">{{ alert.name || alert.rule_name || ('告警#' + (i + 1)) }}</div>
          <div class="ra-desc">{{ alert.description || alert.detail || (alert.rule_name ? alert.rule_name + ' · ' + (alert.severity || 'info') : '') }}</div>
          <div class="ra-meta">PID {{ alert.pid || '?' }} · {{ formatTime(alert.timestamp) }} · {{ alert.alert_id ? 'alert #' + alert.alert_id : '' }}</div>
        </div>
      </div>
    </div>
  </div>
  <!-- 数据不可用时降级隐藏（由父组件控制 v-if） -->
</template>

<script setup>
const props = defineProps({
  alerts: { type: Array, default: () => [] },
})

const displayAlerts = props.alerts // use as-is from parent

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.related-alerts {
  margin-bottom: 12px;
}
.ra-title {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 8px;
}
.ra-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ra-item {
  display: flex;
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
}
.ra-danger {
  background: #FCEBEB;
}
.ra-warning {
  background: #FAEEDA;
}
.ra-icon {
  font-size: 16px;
  line-height: 1;
  font-weight: bold;
  flex-shrink: 0;
}
.ra-danger .ra-icon {
  color: #A32D2D;
}
.ra-warning .ra-icon {
  color: #854F0B;
}
.ra-body {
  flex: 1;
}
.ra-name {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
}
.ra-desc {
  font-size: 11px;
  color: #888780;
  margin-top: 2px;
}
.ra-meta {
  font-size: 11px;
  color: #b4b2a9;
  margin-top: 4px;
}
</style>
