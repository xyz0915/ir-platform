<template>
  <el-tag
    v-if="label"
    :type="tagType"
    :effect="effect"
    size="small"
    :style="color ? { color: color, borderColor: color, backgroundColor: 'transparent' } : undefined"
    class="status-badge"
  >
    <span v-if="dotColor" class="sb-dot" :style="{ background: dotColor }" />
    {{ label }}
  </el-tag>
  <span v-else>—</span>
</template>

<script setup>
import { computed } from 'vue'
import {
  RUN_STATUS_LABELS, RUN_STATUS_TAG,
  SEVERITY_LABELS, SEVERITY_COLOR,
  ROLE_LABELS, HITL_DECISION_LABELS, HITL_DECISION_COLOR,
  TOOL_STATUS_LABELS, TOOL_STATUS_COLOR,
  MCP_STATUS_LABELS, MCP_STATUS_COLOR,
} from '@/constants/agentLabels'

const props = defineProps({
  /** 语义类型：run | severity | role | hitl | tool | mcp */
  type: { type: String, default: 'run' },
  /** 状态值 */
  value: { type: [String, Number], default: '' },
  /** 标签效果：light/plain/dark */
  effect: { type: String, default: 'light' },
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

const tagType = computed(() => {
  if (props.type === 'run') return RUN_STATUS_TAG[props.value] || 'info'
  if (props.type === 'hitl') return 'plain'
  return 'info'
})

const color = computed(() => {
  switch (props.type) {
    case 'severity': return SEVERITY_COLOR[props.value]
    case 'hitl': return HITL_DECISION_COLOR[props.value]
    case 'tool': return TOOL_STATUS_COLOR[props.value]
    case 'mcp': return MCP_STATUS_COLOR[props.value]
    default: return ''
  }
})

const dotColor = computed(() => color.value || '')
</script>

<style scoped>
.status-badge { display: inline-flex; align-items: center; gap: 4px; font-weight: 500; }
.sb-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
</style>
