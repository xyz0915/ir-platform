<template>
  <span
    class="risk-badge"
    :class="`risk-badge--${level}`"
    :style="{ fontSize: size === 'small' ? '12px' : '14px' }"
  >
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  level: { type: String, default: 'info' },
  size: { type: String, default: 'default' }
})

const label = computed(() => {
  const map = {
    critical: '严重',
    high: '高危',
    medium: '中危',
    low: '低危',
    info: '信息'
  }
  return map[props.level] || props.level
})
</script>

<style scoped>
.risk-badge {
  display: inline-block;
  padding: 1px 10px;
  border-radius: 2em;
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
}

/* 严重 / 高危 → danger 语义 */
.risk-badge--critical,
.risk-badge--high {
  color: #fff;
  background: var(--color-danger-emphasis);
}

/* 中危 → warning 语义 */
.risk-badge--medium {
  color: #fff;
  background: var(--color-warning-emphasis);
}

/* 低危 → accent 语义 */
.risk-badge--low {
  color: #fff;
  background: var(--color-accent-emphasis);
}

/* 信息 → 中性 */
.risk-badge--info {
  color: var(--color-fg-default);
  background: var(--color-canvas-subtle);
  border: 1px solid var(--color-border-default);
}
</style>
