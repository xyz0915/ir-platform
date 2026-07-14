<template>
  <div class="vf">
    <span
      v-for="v in views"
      :key="v.key"
      class="vf-chip"
      :class="{ active: active === v.key }"
      @click="$emit('switch', v.key)"
    >
      <!-- 全部 -->
      <svg v-if="v.key === 'all'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
      </svg>
      <!-- 已匹配 -->
      <svg v-else-if="v.key === 'matched'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="12 2 16 8 22 9 18 14 19 20 12 17 5 20 6 14 2 9 8 8 12 2"/>
      </svg>
      <!-- 未匹配 -->
      <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><path d="M16 8l-8 8M8 8l8 8"/>
      </svg>
      {{ v.label }} <span class="vf-cnt">{{ v.count }}</span>
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  active: { type: String, default: 'matched' },
  counts: { type: Object, default: () => ({ all: 0, matched: 0, unmatched: 0 }) },
})

defineEmits(['switch'])

const views = computed(() => [
  { key: 'all', label: '全部事件', count: props.counts.all || 0 },
  { key: 'matched', label: '已匹配规则', count: props.counts.matched || 0 },
  { key: 'unmatched', label: '未匹配规则', count: props.counts.unmatched || 0 },
])
</script>

<style scoped>
.vf {
  display: flex;
  gap: 8px;
}
.vf-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1;
}
.vf-chip:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
}
.vf-chip.active {
  background: var(--color-accent-subtle, #eff6ff);
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
  font-weight: 500;
}
.vf-chip svg {
  flex-shrink: 0;
}
.vf-cnt {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
  margin-left: 2px;
}
.vf-chip.active .vf-cnt {
  color: var(--color-accent-fg, #2563eb);
}
</style>
