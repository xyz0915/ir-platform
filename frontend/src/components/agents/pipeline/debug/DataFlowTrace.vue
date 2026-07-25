<template>
  <div class="dbg-flow">
    <div class="dbg-section-title">数据流追踪（字段级 I/O）</div>
    <div v-if="!node" class="dbg-empty">未选中节点</div>
    <div v-else-if="!run" class="dbg-empty">执行节点后展示输入/输出字段</div>
    <template v-else>
      <div class="dbg-flow-block">
        <div class="dbg-flow-h">输入 input_received</div>
        <div v-if="!ir" class="dbg-flow-broken">⚠ 无 input_received（输入断裂）</div>
        <template v-else>
          <div class="dbg-kv">
            <span class="dbg-k">resolved_host_id</span>
            <span :class="['dbg-v', { broken: !ir.resolved_host_id }]">{{ ir.resolved_host_id || '（空）' }}</span>
          </div>
          <div class="dbg-kv">
            <span class="dbg-k">context_vars</span>
            <span class="dbg-v">{{ cvText }}</span>
          </div>
          <div class="dbg-kv">
            <span class="dbg-k">input_params</span>
            <span class="dbg-v">{{ ipText }}</span>
          </div>
        </template>
      </div>

      <div class="dbg-flow-block">
        <div class="dbg-flow-h">输出 structured</div>
        <div v-if="!structKeys.length" class="dbg-flow-broken">⚠ 结构化输出为空（输出断裂）</div>
        <div v-for="k in structKeys" :key="k" class="dbg-kv">
          <span class="dbg-k">{{ k }}</span>
          <span class="dbg-v">{{ short(structured[k]) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

const store = usePipelineEditorStore()
const node = computed(() => store.selectedNode)
const run = computed(() => store.activeNodeRun)
const ir = computed(() => run.value?.result?.input_received || run.value?.input_received || null)
const structured = computed(() => run.value?.result?.structured || run.value?.structured || {})
const structKeys = computed(() => Object.keys(structured.value || {}))
const cvText = computed(() => (ir.value ? JSON.stringify(ir.value.context_vars || {}) : ''))
const ipText = computed(() => (ir.value ? JSON.stringify(ir.value.input_params || {}) : ''))

function short(v) {
  if (v == null) return '（空）'
  const s = typeof v === 'object' ? JSON.stringify(v) : String(v)
  return s.length > 80 ? s.slice(0, 80) + '…' : s
}
</script>

<style scoped>
.dbg-flow { padding: 4px 0; }
.dbg-empty { font-size: 11px; color: var(--color-fg-light); padding: 12px 0; }
.dbg-section-title {
  font-size: 11px; font-weight: 500; color: var(--color-fg-subtle);
  margin-bottom: 6px;
}
.dbg-flow-block {
  background: var(--color-canvas-subtle); border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn); padding: 8px 10px; margin-bottom: 8px;
}
.dbg-flow-h { font-size: 10px; color: var(--color-fg-muted); margin-bottom: 4px; }
.dbg-flow-broken { font-size: 10px; color: var(--color-danger-fg); }
.dbg-kv { display: flex; gap: 8px; font-size: 10px; padding: 2px 0; align-items: baseline; }
.dbg-k { width: 110px; flex-shrink: 0; color: var(--color-fg-muted); }
.dbg-v { color: var(--color-fg-default); word-break: break-word; }
.dbg-v.broken { color: var(--color-danger-fg); font-weight: 500; }
</style>
