<template>
  <div class="dbg-output">
    <div class="dbg-section-title">
      输出
      <span v-if="status" :class="['dbg-badge', 'is-' + status]">{{ statusText }}</span>
    </div>
    <div v-if="!run" class="dbg-empty">尚未执行，点击「执行单节点」查看结果</div>
    <template v-else>
      <div v-if="run.error" class="dbg-error">⚠️ {{ run.error }}</div>
      <div class="dbg-meta">
        <span>耗时 {{ run.elapsed_ms != null ? run.elapsed_ms : '—' }} ms</span>
        <span>置信度 {{ run.confidence != null ? run.confidence : '—' }}</span>
        <span>模式 {{ run.mode || '—' }}</span>
      </div>
      <div class="dbg-subtitle">output_text（Markdown）</div>
      <pre class="dbg-md">{{ run.output_text || '（空）' }}</pre>
      <div class="dbg-subtitle">
        结构化结果 structured
        <button class="dbg-toggle" type="button" @click="showStruct = !showStruct">{{ showStruct ? '收起' : '展开' }}</button>
      </div>
      <pre v-if="showStruct" class="dbg-json">{{ structText }}</pre>
      <div v-if="run.evidence && run.evidence.length" class="dbg-subtitle">证据 evidence</div>
      <div v-if="run.evidence && run.evidence.length" class="dbg-evidence">
        <el-tag v-for="(e, i) in run.evidence" :key="i" size="small" type="info">
          {{ e.type }} · {{ e.ref }}
        </el-tag>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

const store = usePipelineEditorStore()
const run = computed(() => store.activeNodeRun)
const status = computed(() => {
  const id = store.selectedNodeId
  return id ? (store.nodeRunStatus[id] || null) : null
})
const statusText = computed(
  () => ({ running: '执行中', success: '成功', failed: '失败', idle: '空闲' }[status.value] || status.value || ''),
)
const showStruct = ref(false)
const structText = computed(() => {
  const s = run.value?.result?.structured || run.value?.structured || {}
  try { return JSON.stringify(s, null, 2) } catch { return String(s) }
})
</script>

<style scoped>
.dbg-output { padding: 4px 0; }
.dbg-empty { font-size: 11px; color: var(--color-fg-light); padding: 12px 0; }
.dbg-section-title {
  font-size: 11px; font-weight: 500; color: var(--color-fg-subtle);
  margin-bottom: 6px; display: flex; align-items: center; gap: 8px;
}
.dbg-badge {
  font-size: 10px; font-weight: 500; padding: 1px 6px; border-radius: 3px;
}
.dbg-badge.is-running { background: var(--color-accent-subtle); color: var(--color-accent-fg); }
.dbg-badge.is-success { background: var(--color-success-subtle); color: var(--color-success-fg); }
.dbg-badge.is-failed { background: var(--color-danger-subtle); color: var(--color-danger-fg); }
.dbg-badge.is-idle { background: var(--color-canvas-inset); color: var(--color-fg-subtle); }
.dbg-error {
  font-size: 11px; color: var(--color-danger-fg);
  background: var(--color-danger-subtle); padding: 6px 8px; border-radius: var(--r-btn);
  margin-bottom: 8px; white-space: pre-wrap; word-break: break-word;
}
.dbg-meta { display: flex; gap: 12px; font-size: 10px; color: var(--color-fg-muted); margin-bottom: 8px; }
.dbg-subtitle {
  font-size: 10px; color: var(--color-fg-muted); margin: 10px 0 4px;
  display: flex; align-items: center; gap: 8px;
}
.dbg-md {
  font-size: 11px; line-height: 1.5; color: var(--color-fg-default);
  background: var(--color-canvas-subtle); border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn); padding: 8px 10px; margin: 0; white-space: pre-wrap; word-break: break-word;
  max-height: 220px; overflow: auto;
}
.dbg-json {
  font-size: 10px; line-height: 1.5; color: var(--color-fg-default);
  background: var(--color-canvas-inset); border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn); padding: 8px 10px; margin: 0; white-space: pre-wrap; word-break: break-word;
  max-height: 200px; overflow: auto;
}
.dbg-toggle {
  font-size: 10px; color: var(--color-accent-fg); background: none;
  border: none; cursor: pointer; padding: 0;
}
.dbg-evidence { display: flex; flex-wrap: wrap; gap: 4px; }
</style>
