<template>
  <div v-if="rules.length" class="rnf">
    <div
      class="rnf-header"
      role="button"
      :aria-expanded="!collapsed"
      tabindex="0"
      @click="collapsed = !collapsed"
      @keydown.enter.prevent="collapsed = !collapsed"
      @keydown.space.prevent="collapsed = !collapsed"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
      </svg>
      <span class="rnf-title">规则筛选</span>
      <span class="rnf-summary">命中 {{ rules.length }} 条规则</span>
      <span v-if="selectedRule" class="rnf-active-tag">当前：{{ selectedRule }}</span>
      <span class="rnf-hint">{{ collapsed ? '点击展开' : '点击收起' }}</span>
      <span class="rnf-chevron-wrap">
        <svg
          class="rnf-chevron"
          :class="{ rotated: !collapsed }"
          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        >
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </span>
    </div>
    <div v-show="!collapsed" class="rnf-body">
      <span class="rnf-lbl">规则筛选：</span>
      <span
        class="rnf-chip"
        :class="{ active: selected === null }"
        @click="$emit('select', null)"
      >全部</span>
      <span
        v-for="r in rules"
        :key="r.id"
        class="rnf-chip"
        :class="{ active: selected === r.id }"
        @click="$emit('select', r.id)"
      >
        {{ r.name || r.rule_name }}
        <span class="rnf-cnt">{{ r.hit_count }}</span>
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  rules: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
})
defineEmits(['select'])

// 默认折叠状态
const collapsed = ref(true)

// 当前选中的规则名称（用于 header 标签展示）
const selectedRule = computed(() => {
  if (props.selected == null) return null
  const r = props.rules.find(x => x.id === props.selected)
  return r ? (r.name || r.rule_name) : null
})
</script>

<style scoped>
.rnf {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  overflow: hidden;
}
.rnf-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.rnf-header:hover {
  background: var(--color-canvas-subtle, #f5f5f5);
}
.rnf-header:focus-visible {
  outline: 2px solid var(--color-accent-fg, #2563eb);
  outline-offset: -2px;
}
.rnf-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}
.rnf-summary {
  font-size: 10px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
  background: var(--color-canvas-inset, #f5f5f5);
  padding: 1px 6px;
  border-radius: 4px;
}
.rnf-active-tag {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-accent-fg, #2563eb);
  background: var(--color-accent-subtle, #eff6ff);
  padding: 1px 6px;
  border-radius: 4px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rnf-hint {
  font-size: 10px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
  white-space: nowrap;
}
.rnf-chevron-wrap {
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  transition: background 0.15s;
}
.rnf-header:hover .rnf-chevron-wrap {
  background: var(--color-border-default, #e5e5e5);
}
.rnf-chevron {
  color: var(--color-fg-subtle, #888888);
  transition: transform 0.2s;
}
.rnf-chevron.rotated {
  transform: rotate(180deg);
}
.rnf-body {
  padding: 4px 14px 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
}
.rnf-lbl {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  white-space: nowrap;
}
.rnf-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1;
}
.rnf-chip:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  border-color: var(--color-accent-fg, #2563eb);
}
.rnf-chip.active {
  background: var(--color-accent-subtle, #eff6ff);
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
  font-weight: 500;
}
.rnf-cnt {
  font-size: 10px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
  background: var(--color-canvas-inset, #f5f5f5);
  padding: 0 4px;
  border-radius: 3px;
}
</style>
