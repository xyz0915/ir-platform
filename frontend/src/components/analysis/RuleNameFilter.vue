<template>
  <div class="rnf" v-if="rules.length">
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
</template>

<script setup>
defineProps({
  rules: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
})
defineEmits(['select'])
</script>

<style scoped>
.rnf {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
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
