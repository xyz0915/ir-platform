<template>
  <div class="related-events-card" v-if="relatedIds && relatedIds.length">
    <div class="rel-title">关联事件 ({{ relatedIds.length }})</div>
    <div class="rel-list">
      <button
        v-for="rid in relatedIds"
        :key="rid"
        class="rel-item"
        @click="onViewEvent(rid)"
      >
        {{ rid.substring(0, 16) + '...' }}
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  relatedIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['view-event'])

function onViewEvent(eventId) {
  emit('view-event', eventId)
}
</script>

<style scoped>
.related-events-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 12px;
}
.rel-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 10px;
}
.rel-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.rel-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 6px 8px;
  font-size: 12px;
  font-family: 'Courier New', monospace;
  background: var(--color-canvas-inset);
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  color: var(--color-accent-fg);
  cursor: pointer;
  transition: all 0.1s;
}
.rel-item:hover {
  background: var(--color-accent-subtle);
}
</style>
