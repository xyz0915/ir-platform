<template>
  <div class="top-navigation">
    <button class="tn-back" @click="$emit('back')">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9 3L5 7L9 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      返回分析中心
    </button>
    <template v-if="caseInfo">
      <span class="tn-sep">|</span>
      <span class="tn-case" @click="onViewCase" v-if="caseInfo.case_name || caseInfo.case_number">
        <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><rect x="2" y="3" width="10" height="8" rx="1.5" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M5 3V2a1.5 1.5 0 0 1 3 0v1" stroke="currentColor" stroke-width="1.2" fill="none"/></svg>
        {{ caseInfo.case_name || caseInfo.case_number }}
      </span>
    </template>
    <span class="tn-sep">|</span>
    <span class="tn-event-meta">
      <span class="tn-event-id">{{ eventIdShort }}</span>
      <span class="tn-event-time">{{ formatTime(event.timestamp) }}</span>
      <span class="tn-event-host">{{ event.hostname || (event.host_id ? '主机#' + event.host_id : '') }}</span>
      <span class="tn-event-ip">{{ event.ip_address || '' }}</span>
      <span class="tn-event-collector">{{ event.source_collector || '' }}</span>
    </span>
    <slot name="actions" />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  event: { type: Object, default: () => ({}) },
  caseInfo: { type: Object, default: null },
})

const emit = defineEmits(['back', 'view-case'])

const eventIdShort = computed(() => {
  if (!props.event.id) return ''
  return props.event.id.substring(0, 16) + '…'
})

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function onViewCase() {
  if (props.caseInfo?.case_id) {
    emit('view-case', props.caseInfo.case_id)
  }
}
</script>

<style scoped>
.top-navigation {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
  font-size: 12px;
}
.tn-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  cursor: pointer;
  white-space: nowrap;
}
.tn-back:hover {
  background: var(--color-canvas-inset);
}
.tn-sep {
  color: var(--color-border-default);
  font-size: 14px;
}
.tn-case {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-accent-fg);
  cursor: pointer;
  font-weight: 500;
  white-space: nowrap;
}
.tn-case:hover {
  text-decoration: underline;
}
.tn-event-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.tn-event-id {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.tn-event-time {
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.tn-event-host {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default);
}
.tn-event-ip {
  font-size: 11px;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
}
.tn-event-collector {
  font-size: 11px;
  color: var(--color-fg-light);
  background: var(--color-canvas-inset);
  padding: 1px 6px;
  border-radius: 3px;
}
</style>
