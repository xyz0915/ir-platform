<template>
  <span :class="['confidence-badge', level]">
    <span class="dot" />
    {{ level === 'high' ? '高可信度' : level === 'medium' ? '中可信度' : '低可信度' }}
    <span v-if="level === 'low'" class="verify-hint">建议核实</span>
  </span>
</template>

<script setup>
defineProps({ level: { type: String, default: 'medium' } })
</script>

<style scoped>
.confidence-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 500; padding: 2px 8px; border-radius: 10px; }
.confidence-badge.high { background: var(--color-background-success, #f0fdf4); color: var(--color-text-success, #16a34a); }
.confidence-badge.medium { background: var(--color-background-warning, #fffbeb); color: var(--color-text-warning, #d97706); }
.confidence-badge.low { background: var(--color-background-danger, #fef2f2); color: var(--color-text-danger, #dc2626); }
.dot { width: 6px; height: 6px; border-radius: 50%; }
.confidence-badge.high .dot { background: var(--color-text-success, #16a34a); }
.confidence-badge.medium .dot { background: var(--color-text-warning, #d97706); }
.confidence-badge.low .dot { background: var(--color-text-danger, #dc2626); }
.verify-hint { font-size: 10px; opacity: 0.8; }
</style>
