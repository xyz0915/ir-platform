<template>
  <div class="sla-overlay">
    <div class="sla-summary">
      <div class="sla-stat">
        <span class="sla-count">{{ overdueCount }}</span>
        <span class="sla-label">超时事件</span>
      </div>
      <div class="sla-stat">
        <span class="sla-count warning">{{ warningCount }}</span>
        <span class="sla-label">即将超时</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { SLA } from '@/constants/design-tokens.js'

const props = defineProps({
  events: { type: Array, default: () => [] },
  showOnChart: { type: Boolean, default: false },
})

const now = Date.now()

const overdueCount = computed(() => {
  return props.events.filter(e => {
    if (!e.timestamp) return false
    const elapsed = now - new Date(e.timestamp).getTime()
    return elapsed > SLA.TIMEOUT_HOURS * 3600 * 1000
  }).length
})

const warningCount = computed(() => {
  return props.events.filter(e => {
    if (!e.timestamp) return false
    const elapsed = now - new Date(e.timestamp).getTime()
    return elapsed > SLA.WARNING_HOURS * 3600 * 1000 && elapsed <= SLA.TIMEOUT_HOURS * 3600 * 1000
  }).length
})
</script>

<style scoped>
.sla-overlay {
  padding: 8px 12px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 12px;
}
.sla-summary {
  display: flex;
  gap: 24px;
}
.sla-stat {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sla-count {
  font-size: 18px;
  font-weight: 700;
  color: #F56C6C;
}
.sla-count.warning {
  color: #E6A23C;
}
.sla-label {
  font-size: 12px;
  color: #909399;
}
</style>
