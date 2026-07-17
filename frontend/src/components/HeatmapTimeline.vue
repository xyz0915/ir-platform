<template>
  <div class="heatmap-timeline">
    <div class="ht-title">本日事件热力图</div>
    <div class="ht-bars">
      <div v-for="(h, i) in hours" :key="i" class="ht-bar" :style="{ height: (h.count / Math.max(1, ...hours.filter(x => x.count > 0).map(x => x.count))) * 36 + 'px', background: h.count > 0 ? (h.severity === 'high' ? 'var(--color-danger-fg, #dc2626)' : 'var(--color-accent-fg, #2563eb)') : 'var(--color-border-tertiary, #eee)' }"></div>
    </div>
    <div class="ht-labels">
      <span v-for="(h, i) in hours" :key="'l'+i" class="ht-label" :class="{ 'ht-label-active': h.count > 0 }">
        {{ i % 4 === 0 ? i + ':00' : '' }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
const hours = ref(Array.from({length: 24}, (_, i) => ({ hour: i, count: Math.floor(Math.random() * 5), severity: Math.random() > 0.7 ? 'high' : 'normal' })))
</script>

<style scoped>
.heatmap-timeline { margin-top: 8px; }
.ht-title { font-size: 11px; color: var(--color-fg-subtle, #888); margin-bottom: 6px; }
.ht-bars { display: flex; align-items: flex-end; gap: 2px; height: 36px; }
.ht-bar { flex: 1; border-radius: 2px 2px 0 0; transition: height .3s; min-height: 3px; }
.ht-labels { display: flex; gap: 2px; margin-top: 2px; }
.ht-label { flex: 1; font-size: 8px; color: var(--color-fg-light, #ccc); text-align: center; }
.ht-label-active { color: var(--color-fg-subtle, #888); }
</style>
