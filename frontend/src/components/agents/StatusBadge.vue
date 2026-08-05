<template>
  <span v-if="label" class="status-badge">
    <span class="sb-dot" :style="dotStyle" />
    <span class="sb-text">{{ label }}</span>
  </span>
  <span v-else class="status-badge status-badge-empty">—</span>
</template>

<script setup>
import { computed } from 'vue'
import {
  RUN_STATUS_LABELS,
  SEVERITY_LABELS,
  ROLE_LABELS, HITL_DECISION_LABELS,
  TOOL_STATUS_LABELS,
  MCP_STATUS_LABELS,
} from '@/constants/agentLabels'

const props = defineProps({
  /** 语义类型：run | severity | role | hitl | tool | mcp */
  type: { type: String, default: 'run' },
  /** 状态值 */
  value: { type: [String, Number], default: '' },
  /** 标签效果：light/plain/dark（保留兼容，渲染已统一为单色点+文字） */
  effect: { type: String, default: 'light' },
  /** 自定义圆点颜色（可选，覆盖默认单色语义） */
  color: { type: String, default: '' },
})

const label = computed(() => {
  const v = props.value
  switch (props.type) {
    case 'run': return RUN_STATUS_LABELS[v] || v
    case 'severity': return SEVERITY_LABELS[v] || v
    case 'role': return ROLE_LABELS[v] || v
    case 'hitl': return HITL_DECISION_LABELS[v] || v
    case 'tool': return TOOL_STATUS_LABELS[v] || v
    case 'mcp': return MCP_STATUS_LABELS[v] || v
    default: return v
  }
})

/** 单色圆点：仅保留必要语义色（绿 #16a34a / 红 #dc2626 克制），其余灰 #9ca3af */
const dotColor = computed(() => {
  if (props.color) return props.color
  const v = props.value
  if (['approved', 'success', 'online', 'available'].includes(v)) return '#16a34a'
  if (['failed', 'rejected'].includes(v)) return '#dc2626'
  return '#9ca3af'
})

const dotStyle = computed(() => ({ background: dotColor.value }))
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
  white-space: nowrap;
}
.status-badge-empty { color: #9ca3af; font-weight: 400; }
.sb-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
</style>
