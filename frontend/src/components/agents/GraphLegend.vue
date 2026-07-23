<template>
  <div class="graph-legend">
    <div v-for="item in legendItems" :key="item.type" class="gl-item">
      <span class="gl-dot" :style="{ background: item.color }"></span>
      <span class="gl-label">{{ item.label }}</span>
    </div>
  </div>
</template>

<script setup>
const legendItems = [
  { type: 'host', color: '#E74C3C', label: '主机' },
  { type: 'url', color: '#3498DB', label: '资源' },
  { type: 'action', color: '#F39C12', label: '动作' },
  { type: 'file', color: '#2ECC71', label: '文件' },
  { type: 'process', color: '#9B59B6', label: '进程' },
]
</script>

<style scoped>
.graph-legend {
  display: flex;
  gap: 12px;
  padding: 6px 12px;
  flex-wrap: wrap;
}
.gl-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.gl-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.gl-label {
  white-space: nowrap;
}
</style>
