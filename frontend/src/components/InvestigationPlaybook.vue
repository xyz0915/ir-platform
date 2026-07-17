<template>
  <div class="playbook-panel">
    <div class="pb-title">调查剧本</div>
    <div v-for="pb in playbooks" :key="pb.id" class="pb-item">
      <div class="pb-head">
        <span class="pb-name clickable" @click="toggleExpand(pb.id)">{{ pb.name }}</span>
        <el-button size="small" text @click="$emit('start', pb.id)">▶ 执行</el-button>
      </div>
      <div class="pb-desc">{{ pb.description }}</div>
      <div v-if="expanded === pb.id" class="pb-steps">
        <div v-for="(s, i) in pb.steps || []" :key="i" class="pb-step-item">
          <span class="pbs-num">{{ i + 1 }}</span>
          <span class="pbs-name">{{ s.name }}</span>
        </div>
      </div>
      <div v-if="pb.tags?.length" class="pb-tags">
        <el-tag v-for="t in pb.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
      </div>
    </div>
    <div v-if="progress.total > 0" class="pb-progress">
      <div class="pb-progress-bar">
        <div class="pb-progress-fill" :style="{ width: (progress.current / progress.total * 100) + '%' }" />
      </div>
      <div class="pb-progress-label">{{ progress.current }} / {{ progress.total }} 步</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
defineProps({
  playbooks: { type: Array, default: () => [] },
  progress: { type: Object, default: () => ({ current: 0, total: 0 }) },
})
defineEmits(['start'])
const expanded = ref(null)
function toggleExpand(id) {
  expanded.value = expanded.value === id ? null : id
}
</script>

<style scoped>
.playbook-panel { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 10px; padding: 12px; }
.pb-title { font-size: 12px; font-weight: 500; color: var(--color-fg-default, #111); margin-bottom: 8px; }
.pb-item { margin-bottom: 8px; padding: 8px; border: 0.5px solid var(--color-border-tertiary, #eee); border-radius: 6px; }
.pb-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.pb-name { font-size: 12px; font-weight: 500; color: var(--color-fg-default, #111); }
.pb-desc { font-size: 11px; color: var(--color-fg-subtle, #888); line-height: 1.4; margin-bottom: 4px; }
.pb-tags { display: flex; gap: 2px; flex-wrap: wrap; }
.pb-tags :deep(.el-tag) { font-size: 10px !important; height: 18px !important; padding: 0 6px !important; }
.pb-progress { margin-top: 8px; }
.pb-progress-bar { height: 4px; background: var(--color-border-tertiary, #eee); border-radius: 2px; overflow: hidden; }
.pb-progress-fill { height: 100%; background: var(--color-accent-fg, #2563eb); border-radius: 2px; transition: width .3s; }
.pb-progress-label { font-size: 10px; color: var(--color-fg-subtle, #888); margin-top: 2px; }

.pb-steps { margin: 6px 0; display: flex; flex-direction: column; gap: 3px; }
.pb-step-item { display: flex; align-items: center; gap: 6px; padding: 3px 0 3px 4px; font-size: 11px; color: var(--color-fg-muted, #555); }
.pbs-num { width: 16px; height: 16px; border-radius: 50%; background: var(--color-bg-subtle, #f5f5f5); display: flex; align-items: center; justify-content: center; font-size: 9px; font-weight: 500; color: var(--color-fg-subtle, #888); flex-shrink: 0; }
.pbs-name { line-height: 1.3; }
</style>
