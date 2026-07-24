<template>
  <div class="step-flow">
    <div
      v-for="(step, i) in steps"
      :key="i"
      class="sf-step"
      :class="['sf-' + (step.status || 'pending')]"
    >
      <div class="sf-node">
        <span v-if="step.status === 'running'" class="sf-spinner" />
        <span v-else-if="step.status === 'completed'" class="sf-check">✓</span>
        <span v-else-if="step.status === 'failed'" class="sf-cross">✗</span>
        <span v-else class="sf-idle">{{ i + 1 }}</span>
      </div>
      <div class="sf-label">{{ step.label }}</div>
      <div class="sf-desc" v-if="step.description">{{ step.description }}</div>
      <div v-if="i < steps.length - 1" class="sf-line" :class="{ done: isDone(step.status) }" />
    </div>
  </div>
</template>

<script setup>
import { NODE_TYPE_LABELS } from '@/constants/agentLabels'

const props = defineProps({
  /** 步骤数组：{ label, status, description? }，status: completed|running|failed|pending */
  steps: { type: Array, default: () => [] },
})

function isDone(status) {
  return status === 'completed'
}

// 兼容 DAG 节点类型的着色辅助（可选）
const nodeLabels = NODE_TYPE_LABELS
</script>

<style scoped>
.step-flow { display: flex; align-items: flex-start; width: 100%; overflow-x: auto; padding: 4px 0; }
.sf-step {
  position: relative;
  flex: 1;
  min-width: 90px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.sf-node {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  border: 2px solid var(--color-border-default);
  background: var(--color-canvas-default);
  color: var(--color-fg-subtle);
  z-index: 1;
}
.sf-running .sf-node { border-color: #3B82F6; color: #3B82F6; }
.sf-completed .sf-node { border-color: #22C55E; background: #22C55E; color: #fff; }
.sf-failed .sf-node { border-color: #EF4444; background: #EF4444; color: #fff; }
.sf-label { font-size: 12px; margin-top: 6px; color: var(--color-fg-default); max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sf-desc { font-size: 10px; color: var(--color-fg-subtle); max-width: 110px; }
.sf-line {
  position: absolute;
  top: 14px;
  left: 50%;
  width: 100%;
  height: 2px;
  background: var(--color-border-default);
  z-index: 0;
}
.sf-line.done { background: #22C55E; }
.sf-spinner {
  width: 12px; height: 12px;
  border: 2px solid #cbd5e1;
  border-top-color: #3B82F6;
  border-radius: 50%;
  animation: sf-spin 0.6s linear infinite;
}
@keyframes sf-spin { to { transform: rotate(360deg); } }
</style>
