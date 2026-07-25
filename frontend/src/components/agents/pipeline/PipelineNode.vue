<template>
  <div
    class="node"
    :class="{ selected: isSelected, error: props.nodeData.validationError, running: runStatus === 'running', success: runStatus === 'success', failed: runStatus === 'failed' }"
    :style="nodeStyle"
    @click.stop="onSelect"
    @mousedown.prevent="onMouseDown"
    @dblclick.prevent="onDblClick"
    @contextmenu.prevent="onContextMenu"
  >
    <!-- 运行态指示点 -->
    <span v-if="runStatus" class="run-dot" :class="runStatus"></span>
    <!-- 头部 -->
    <div class="node-head">
      <span class="type-tag">{{ typeTag }}</span>
      <span class="title">{{ nodeName }}</span>
      <span class="menu">⋯</span>
    </div>
    <!-- 主体 -->
    <div class="node-body">
      <span v-if="badgeText" :class="['badge', badgeClass]">{{ badgeText }}</span>
      <div v-if="statText" class="node-stat">{{ statText }}</div>
    </div>
    <!-- 输入连接器 -->
    <div
      v-if="hasInConn"
      class="connector cn-in"
      :class="{ 'cn-active': isConnectSource }"
      @mousedown.stop="onConnectorClick('in', $event)"
    ></div>
    <!-- 输出连接器 -->
    <div
      v-if="hasOutConn"
      class="connector cn-out"
      :class="{ 'cn-active': isConnectSource }"
      @mousedown.stop="onConnectorClick('out', $event)"
    ></div>
    <!-- 序号 -->
    <div class="node-index">Step {{ stepIndex }}</div>
  </div>
</template>

<script setup>
import { computed, h } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { NodeTypeMeta } from '@/constants/pipelineTypes'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

const store = usePipelineEditorStore()

const props = defineProps({
  nodeData: {
    type: Object,
    required: true,
  },
})

const emit = defineEmits(['select', 'connectorClick', 'dragStart'])

// ===== 计算属性 =====
const typeTag = computed(() => props.nodeData.typeLabel || NodeTypeMeta[props.nodeData.type]?.label || props.nodeData.type || '')
const nodeName = computed(() => props.nodeData.name || '')
const badgeText = computed(() => props.nodeData.badgeText || '')
const statText = computed(() => props.nodeData.statText || '')
const hasInConn = computed(() => props.nodeData.hasInConnector !== false)
const hasOutConn = computed(() => props.nodeData.hasOutConnector !== false)
const isSelected = computed(() => props.nodeData.selected || false)
const stepIndex = computed(() => props.nodeData.stepIndex || 0)
// Phase 3 · 调试运行态（独立于 validationError）
const runStatus = computed(() => store.nodeRunStatus[props.nodeData.id] || null)
const isConnectSource = computed(() => props.nodeData.isConnectSource || false)

const badgeClass = computed(() => {
  const meta = NodeTypeMeta[props.nodeData.type]
  return meta ? meta.badgeColor : 'badge-info'
})

const nodeStyle = computed(() => ({
  left: `${props.nodeData.position?.x || 0}px`,
  top: `${props.nodeData.position?.y || 0}px`,
}))

// ===== 事件处理 =====
function onSelect() {
  emit('select', props.nodeData.id)
}

function onMouseDown(event) {
  if (event.button !== 0) return // 只响应左键
  emit('dragStart', {
    nodeId: props.nodeData.id,
    startX: props.nodeData.position.x,
    startY: props.nodeData.position.y,
    mouseX: event.clientX,
    mouseY: event.clientY,
  })
}

function onDblClick() {
  emit('select', props.nodeData.id)
}

function onConnectorClick(direction, event) {
  emit('connectorClick', { nodeId: props.nodeData.id, direction, event })
}

// ===== M4: 右键菜单 =====

function onContextMenu(event) {
  // 先选中自己
  emit('select', props.nodeData.id)

  ElMessageBox({
    title: `节点操作 — ${props.nodeData.name}`,
    message: h('div', { class: 'context-menu' }, [
      h('div', { class: 'ctx-item', onClick: () => { ElMessageBox.close(); onSelect() } }, '✏️ 编辑配置'),
      h('div', { class: 'ctx-item ctx-danger', onClick: () => { ElMessageBox.close(); onDeleteNode() } }, '🗑️ 删除节点'),
      h('div', { class: 'ctx-item', onClick: () => { ElMessageBox.close(); onCopyNode() } }, '📋 复制节点'),
    ]),
    showCancelButton: false,
    showConfirmButton: false,
    closeOnClickModal: true,
  })
}

function onDeleteNode() {
  ElMessageBox.confirm(`确定删除节点"${props.nodeData.name}"？`, '删除确认', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    const store = usePipelineEditorStore()
    store.removeNode(props.nodeData.id)
    ElMessage.success('节点已删除')
  }).catch(() => {})
}

function onCopyNode() {
  const store = usePipelineEditorStore()
  const newNode = store.duplicateNode(props.nodeData.id)
  if (newNode) {
    ElMessage.success(`已复制节点"${newNode.name}"`)
  }
}
</script>

<style scoped>
.node {
  position: absolute;
  width: 160px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-card);
  cursor: pointer;
  z-index: 10;
  transition: border-color 0.12s, box-shadow 0.12s;
}
.node:hover {
  border-color: var(--color-accent-fg);
  box-shadow: 0 0 0 2px var(--color-accent-subtle);
}
.node.selected {
  border-color: var(--color-accent-fg);
  box-shadow: 0 0 0 2px var(--color-accent-subtle);
}

/* M3: 校验错误红色标注 */
.node.error {
  border-color: var(--color-danger-fg);
  box-shadow: 0 0 0 2px var(--color-danger-subtle);
}
.node.error:hover {
  border-color: var(--color-danger-fg);
  box-shadow: 0 0 0 2px var(--color-danger-subtle);
}

/* Phase 3 · 调试运行态（独立于校验错误） */
/* running: 蓝边 + 左上旋转点 */
.node.running {
  border-color: var(--color-accent-fg);
  box-shadow: 0 0 0 2px var(--color-accent-subtle);
}
.run-dot {
  position: absolute;
  top: -5px;
  left: -5px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  z-index: 12;
}
.run-dot.running {
  background: var(--color-accent-fg);
  border: 1.5px solid #fff;
  box-shadow: 0 0 0 2px var(--color-accent-subtle);
  animation: dbg-node-spin 0.8s linear infinite;
}
.run-dot.success {
  background: var(--color-success-fg);
  border: 1.5px solid #fff;
}
.run-dot.failed {
  background: var(--color-danger-fg);
  border: 1.5px solid #fff;
}
@keyframes dbg-node-spin {
  to { transform: rotate(360deg); }
}
.node.success {
  border-color: var(--color-success-fg);
  box-shadow: 0 0 0 2px var(--color-success-subtle);
}
.node.failed {
  border-color: var(--color-danger-fg);
  box-shadow: 0 0 0 2px var(--color-danger-subtle);
}

.node-head {
  padding: 10px 12px 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.node-head .type-tag {
  font-size: 10px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  background: var(--color-canvas-subtle);
  padding: 1px 5px;
  border-radius: 3px;
}
.node-head .title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-head .menu {
  color: var(--color-fg-light);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}

.node-body {
  padding: 0 12px 8px;
  font-size: 11px;
  color: var(--color-fg-subtle);
  line-height: 1.5;
}
.node-stat {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  font-size: 10px;
  color: var(--color-fg-light);
}

.badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}
.badge-low {
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
}
.badge-medium {
  background: var(--color-warning-subtle);
  color: var(--color-warning-fg);
}
.badge-critical {
  background: var(--color-danger-subtle);
  color: var(--color-danger-fg);
}
.badge-info {
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
}
.badge-success {
  background: var(--color-success-subtle);
  color: var(--color-success-fg);
}

/* M6: Connector hover 增强样式 */
.connector {
  position: absolute;
  width: 12px;
  height: 12px;
  background: var(--color-canvas-default);
  border: 1.5px solid var(--color-border-default);
  border-radius: 50%;
  z-index: 10;
  cursor: crosshair;
  transition: border-color 0.12s, background 0.12s, transform 0.12s;
}
.connector:hover {
  border-color: var(--color-accent-fg);
  background: var(--color-accent-subtle);
  transform: scale(1.3) translateY(-50%);
}
.cn-in {
  left: -7px;
  top: 50%;
  transform: translateY(-50%);
}
.cn-in:hover {
  transform: scale(1.3) translateY(-50%);
}
.cn-out {
  right: -7px;
  top: 50%;
  transform: translateY(-50%);
}
.cn-out:hover {
  transform: scale(1.3) translateY(-50%);
}
.cn-active {
  border-color: var(--color-accent-fg);
  background: var(--color-accent-subtle);
}

.node-index {
  position: absolute;
  bottom: -18px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 10px;
  color: var(--color-fg-light);
  white-space: nowrap;
}
</style>
