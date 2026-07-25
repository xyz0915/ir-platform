<template>
  <div class="dbg-history">
    <div class="dbg-section-title">
      历史记录
      <button class="dbg-refresh" type="button" @click="onRefresh">刷新</button>
    </div>
    <div v-if="!items.length" class="dbg-empty">暂无调试历史（执行后自动留存）</div>
    <div
      v-for="(it, i) in items"
      :key="it.run_id || i"
      class="dbg-hist-item"
      :class="{ active: it.run_id === activeId }"
      @click="onPick(it)"
    >
      <span :class="['dbg-badge', 'is-' + (it.status || 'idle')]">{{ it.status }}</span>
      <span class="dbg-hist-mode">{{ it.mode }}</span>
      <span class="dbg-hist-time">{{ fmt(it.timestamp) }}</span>
      <span class="dbg-hist-el">{{ it.elapsed_ms != null ? it.elapsed_ms + 'ms' : '—' }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

const store = usePipelineEditorStore()
const items = computed(() => store.nodeRunHistory || [])
const activeId = computed(() => store.activeNodeRun?.run_id)

function fmt(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return isNaN(d.getTime()) ? String(ts) : d.toLocaleString()
}

function onRefresh() {
  const id = store.selectedNodeId
  if (id) store.loadNodeRuns(id)
}

function onPick(it) {
  const out = it.output || {}
  store.activeNodeRun = {
    status: it.status,
    node_type: it.node_type,
    node_name: it.node_name,
    mode: it.mode,
    elapsed_ms: it.elapsed_ms,
    confidence: it.confidence != null ? it.confidence : out.confidence,
    error: it.error,
    evidence: out.evidence || [],
    output_text: out.output_text || '',
    structured: out.structured || {},
    result: {
      input_received: it.input || {},
      output_text: out.output_text || '',
      structured: out.structured || {},
    },
    run_id: it.run_id,
    timestamp: it.timestamp,
  }
}
</script>

<style scoped>
.dbg-history { padding: 4px 0; }
.dbg-empty { font-size: 11px; color: var(--color-fg-light); padding: 12px 0; }
.dbg-section-title {
  font-size: 11px; font-weight: 500; color: var(--color-fg-subtle);
  margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between;
}
.dbg-refresh {
  font-size: 10px; color: var(--color-accent-fg); background: none;
  border: none; cursor: pointer; padding: 0;
}
.dbg-hist-item {
  display: flex; align-items: center; gap: 8px; font-size: 10px;
  padding: 6px 8px; border-radius: var(--r-btn); cursor: pointer;
  border: 0.5px solid transparent;
}
.dbg-hist-item:hover { background: var(--color-canvas-subtle); }
.dbg-hist-item.active { border-color: var(--color-accent-fg); background: var(--color-accent-subtle); }
.dbg-badge { font-size: 10px; font-weight: 500; padding: 1px 6px; border-radius: 3px; }
.dbg-badge.is-success { background: var(--color-success-subtle); color: var(--color-success-fg); }
.dbg-badge.is-failed { background: var(--color-danger-subtle); color: var(--color-danger-fg); }
.dbg-badge.is-running { background: var(--color-accent-subtle); color: var(--color-accent-fg); }
.dbg-badge.is-idle { background: var(--color-canvas-inset); color: var(--color-fg-subtle); }
.dbg-hist-mode { color: var(--color-fg-muted); }
.dbg-hist-time { color: var(--color-fg-muted); flex: 1; }
.dbg-hist-el { color: var(--color-fg-light); }
</style>
