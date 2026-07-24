<template>
  <div class="node-palette">
    <div class="np-title">节点面板</div>
    <p class="np-hint">点击添加到画布中心，再拖拽调整位置、连线编排 DAG。</p>
    <div class="np-list">
      <button
        v-for="item in nodeTypes"
        :key="item.type"
        class="np-item"
        :style="{ '--np-color': item.color }"
        @click="$emit('add-node', item.type)"
      >
        <span class="np-dot" :style="{ background: item.color }" />
        <span class="np-label">{{ item.label }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { NODE_TYPE_LABELS, NODE_TYPE_COLOR } from '@/constants/agentLabels'

const emit = defineEmits(['add-node'])

const nodeTypes = [
  'trigger',
  'investigate',
  'forensic',
  'guardrail',
  'remediate',
  'hitl',
  'end',
].map((t) => ({ type: t, label: NODE_TYPE_LABELS[t], color: NODE_TYPE_COLOR[t] }))
</script>

<style scoped>
.node-palette { padding: 12px; }
.np-title { font-size: 13px; font-weight: 600; color: var(--color-fg-default); margin-bottom: 4px; }
.np-hint { font-size: 11px; color: var(--color-fg-subtle); line-height: 1.5; margin: 0 0 12px; }
.np-list { display: flex; flex-direction: column; gap: 8px; }
.np-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: 8px; cursor: pointer;
  background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default);
  transition: all 0.15s; text-align: left;
}
.np-item:hover { border-color: var(--np-color); background: var(--color-canvas-subtle); transform: translateX(2px); }
.np-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.np-label { font-size: 13px; color: var(--color-fg-default); }
</style>
