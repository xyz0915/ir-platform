<template>
  <aside class="dbg-panel" :class="{ open: store.debugMode }">
    <div class="dbg-header">
      <div class="dbg-title">
        <span class="dbg-bug">🐞</span>
        <span class="dbg-name">{{ nodeName }}</span>
        <span v-if="nodeType" class="dbg-type">{{ nodeTypeLabel }}</span>
      </div>
      <div class="dbg-header-right">
        <el-radio-group v-model="mode" size="small" class="dbg-mode-toggle">
          <el-radio-button label="real">真实</el-radio-button>
          <el-radio-button label="simulate">模拟</el-radio-button>
        </el-radio-group>
        <button class="dbg-close" type="button" title="关闭调试面板" @click="store.closeDebug()">×</button>
      </div>
    </div>

    <div v-if="!node" class="dbg-no-node">
      请先在画布中选择一个节点，再开始调试。
    </div>

    <div v-else class="dbg-body">
      <!-- 输入编辑 -->
      <section class="dbg-section">
        <div class="dbg-section-title">输入</div>
        <DebugInputEditor />
      </section>

      <!-- 执行按钮 -->
      <div class="dbg-run-row">
        <button class="dbg-run" type="button" :disabled="running" @click="onRun">
          <span v-if="running" class="dbg-spinner"></span>
          <span v-else>▶</span>
          {{ running ? '执行中…' : '执行单节点' }}
        </button>
        <span class="dbg-run-hint">host_id 优先于 event_id 反查</span>
      </div>

      <!-- 输出 -->
      <section class="dbg-section">
        <DebugOutputViewer />
      </section>

      <!-- 分支模拟（仅 branch 节点） -->
      <section v-if="nodeType === 'branch'" class="dbg-section">
        <BranchSimulator />
      </section>

      <!-- 数据流追踪 -->
      <section class="dbg-section">
        <DataFlowTrace />
      </section>

      <!-- 历史 -->
      <section class="dbg-section">
        <DebugHistoryList />
      </section>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import { NodeTypeMeta } from '@/constants/pipelineTypes'
import DebugInputEditor from './debug/DebugInputEditor.vue'
import DebugOutputViewer from './debug/DebugOutputViewer.vue'
import BranchSimulator from './debug/BranchSimulator.vue'
import DataFlowTrace from './debug/DataFlowTrace.vue'
import DebugHistoryList from './debug/DebugHistoryList.vue'

const store = usePipelineEditorStore()
const node = computed(() => store.selectedNode)
const nodeName = computed(() => (node.value ? node.value.name : '调试面板'))
const nodeType = computed(() => (node.value ? node.value.type : ''))
const nodeTypeLabel = computed(() => {
  if (!nodeType.value) return ''
  const meta = NodeTypeMeta[nodeType.value]
  return meta ? meta.label : nodeType.value
})
const running = computed(() => {
  const id = store.selectedNodeId
  return id ? store.nodeRunStatus[id] === 'running' : false
})

// mode 双向绑定到 debugDraft[selectedNodeId].mode
const mode = computed({
  get() {
    const id = store.selectedNodeId
    if (!id) return 'real'
    const d = store.ensureDebugDraft(id)
    return d.mode || 'real'
  },
  set(val) {
    const id = store.selectedNodeId
    if (!id) return
    const d = store.ensureDebugDraft(id)
    store.saveDebugDraft(id, { ...d, mode: val })
  },
})

// 选中节点变化 → 自动加载历史
watch(
  () => store.selectedNodeId,
  (id) => {
    if (id) store.loadNodeRuns(id)
  },
  { immediate: true },
)

function onRun() {
  const id = store.selectedNodeId
  if (!id) return
  store.runNodeDebug(id)
}
</script>

<style scoped>
.dbg-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 340px;
  background: var(--color-canvas-default);
  border-left: 0.5px solid var(--color-border-default);
  z-index: 20;
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.18s ease;
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.06);
}
.dbg-panel.open {
  transform: translateX(0);
}

.dbg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 0.5px solid var(--color-border-default);
  flex-shrink: 0;
}
.dbg-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.dbg-bug { font-size: 13px; }
.dbg-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 110px;
}
.dbg-type {
  font-size: 10px;
  color: var(--color-fg-muted);
  background: var(--color-canvas-subtle);
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}
.dbg-header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.dbg-close {
  width: 22px;
  height: 22px;
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-default);
  color: var(--color-fg-muted);
  border-radius: var(--r-btn);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.dbg-close:hover { color: var(--color-danger-fg); border-color: var(--color-danger-fg); }

.dbg-no-node {
  padding: 24px 16px;
  font-size: 12px;
  color: var(--color-fg-light);
  line-height: 1.6;
}

.dbg-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 12px 16px;
}
.dbg-section { margin-bottom: 12px; }
.dbg-section-title {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 6px;
}

.dbg-run-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 14px;
}
.dbg-run {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 14px;
  font-size: 12px;
  font-weight: 500;
  border-radius: var(--r-btn);
  border: 0.5px solid var(--color-accent-fg);
  background: var(--color-accent-fg);
  color: #fff;
  cursor: pointer;
  white-space: nowrap;
}
.dbg-run:hover:not(:disabled) { opacity: 0.9; }
.dbg-run:disabled { opacity: 0.6; cursor: not-allowed; }
.dbg-run-hint {
  font-size: 10px;
  color: var(--color-fg-light);
}
.dbg-spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 1.5px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: dbg-spin 0.6s linear infinite;
}
@keyframes dbg-spin { to { transform: rotate(360deg); } }
</style>
