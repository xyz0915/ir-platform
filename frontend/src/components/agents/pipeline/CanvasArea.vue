<template>
  <div class="canvas-wrap" ref="canvasWrapRef">
    <!-- 上操作栏 -->
    <div class="canvas-topbar">
      <div class="title">{{ store.pipelineName || '应急响应工作流' }} · {{ store.nodeCount }} 个节点 · {{ store.connectionCount }} 条连线</div>
      <div class="actions">
        <button class="btn" @click="onLoadSample">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          加载示例
        </button>
        <button class="btn" @click="onClear">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          清空
        </button>
        <button class="btn" @click="onValidate">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          校验
        </button>
        <button class="btn btn-primary" :disabled="store.runLoading" @click="onRun">
          <svg v-if="!store.runLoading" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          <span v-if="store.runLoading" class="spinner"></span>
          {{ store.runLoading ? '运行中...' : '运行' }}
        </button>
      </div>
    </div>

    <!-- 校验结果 -->
    <div v-if="store.validationMessages.length > 0" class="validation-bar" :class="{ 'is-valid': store.isValid, 'is-error': !store.isValid }">
      <div v-for="(msg, i) in store.validationMessages" :key="i" class="validation-msg">{{ msg }}</div>
    </div>

    <!-- 画布 -->
    <div class="canvas" ref="canvasRef" @drop="onDrop" @dragover.prevent="onDragOver" @mousemove="onCanvasMouseMove" @click="onCanvasClick">
      <div class="canvas-inner" :style="canvasInnerStyle">

        <!-- 阶段标签 -->
        <div
          v-for="phase in phases"
          :key="phase.id"
          class="phase-label"
          :style="{ left: phase.x + 'px' }"
        >{{ phase.label }}</div>

        <!-- 对准基线 guide-h -->
        <div class="guide-h guide-h-1"></div>
        <div class="guide-h guide-h-2"></div>

        <!-- 管道轨道 -->
        <div class="pipeline-track track-0" :style="{ left: '80px', right: '80px' }">
          <div class="pipeline-track-inner"></div>
        </div>
        <div class="pipeline-track track-1" :style="{ left: '80px', right: '80px' }">
          <div class="pipeline-track-inner"></div>
        </div>

        <!-- 节点 -->
        <PipelineNode
          v-for="node in store.pipelineNodes"
          :key="node.id"
          :node-data="node"
          @select="onNodeSelect"
          @connector-click="onConnectorClick"
          @drag-start="onNodeDragStart"
        />

        <!-- SVG 连线层 -->
        <ConnectionLayer
          :width="canvasWidth"
          :height="canvasHeight"
        />

        <!-- 临时预览线 (H4) -->
        <svg v-if="store.connectMode && tempLine" class="temp-line-layer"
          :style="{ position: 'absolute', top: 0, left: 0, width: canvasWidth + 'px', height: canvasHeight + 'px', pointerEvents: 'none', zIndex: 4 }">
          <path :d="tempLine.path" stroke="#2563eb" stroke-width="2" stroke-dasharray="5 3" fill="none" />
        </svg>

        <!-- 步骤指示器 -->
        <div class="step-indicator">
          <span
            v-for="(step, i) in store.pipelineNodes"
            :key="step.id"
            class="step-dot"
            :class="{ active: step.id === store.selectedNodeId }"
          ></span>
          <span class="step-label">{{ store.selectedNode?.name || '就绪' }}</span>
        </div>
      </div>
    </div>

    <!-- 缩放栏 -->
    <ZoomBar :zoom="store.zoomLevel" @zoom-change="onZoomChange" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'
import { PipelinePhase } from '@/constants/pipelineTypes'
import { ElMessage, ElMessageBox } from 'element-plus'
import PipelineNode from './PipelineNode.vue'
import ConnectionLayer from './ConnectionLayer.vue'
import ZoomBar from './ZoomBar.vue'

const store = usePipelineEditorStore()
const route = useRoute()
const router = useRouter()

const canvasWrapRef = ref(null)
const canvasRef = ref(null)
const canvasWidth = ref(2000)
const canvasHeight = ref(1200)
const tempLine = ref(null)

const phases = PipelinePhase

const canvasInnerStyle = computed(() => ({
  transform: `scale(${store.zoomLevel / 100})`,
  transformOrigin: 'top left',
}))

// ===== 辅助函数 =====

/**
 * 获取默认 eventId：优先从路由 query 取，次选 query.caseId，最后自动生成。
 */
function getDefaultEventId() {
  if (route.query?.eventId) return route.query.eventId
  if (route.query?.caseId) return `case-${route.query.caseId}`
  return `manual-${Date.now()}`
}

// ===== 事件处理 =====

function onNodeSelect(nodeId) {
  store.selectNode(nodeId)
}

function onConnectorClick({ nodeId, direction }) {
  if (direction === 'out') {
    store.startConnect(nodeId)
  } else if (direction === 'in' && store.connectMode) {
    store.completeConnect(nodeId)
    tempLine.value = null
  }
}

function onNodeDragStart(payload) {
  const { nodeId, startX, startY, mouseX, mouseY } = payload
  const zoom = store.zoomLevel / 100
  let dragged = false

  function onMouseMove(e) {
    dragged = true
    const dx = (e.clientX - mouseX) / zoom
    const dy = (e.clientY - mouseY) / zoom
    const node = store.pipelineNodes.find(n => n.id === nodeId)
    if (node) {
      node.position.x = startX + dx
      node.position.y = Math.round((startY + dy) / 8) * 8
    }
  }

  function onMouseUp() {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    if (dragged) store.configDirty = true
  }

  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}

function onZoomChange(newZoom) {
  store.zoomLevel = newZoom
}

function onLoadSample() {
  store.loadSample()
  ElMessage.success('已加载示例工作流')
  // L2: 加载示例后自动滚动
  setTimeout(() => {
    canvasRef.value?.scrollTo({ top: 200, behavior: 'smooth' })
  }, 100)
}

function onClear() {
  store.clearCanvas()
  ElMessage.info('画布已清空')
}

function onValidate() {
  store.validatePipeline()
  if (store.isValid) {
    ElMessage.success('管道校验通过')
  } else {
    ElMessage.warning('管道校验未通过，请查看详情')
  }
}

async function onRun() {
  try {
    store.validatePipeline()
    if (!store.isValid) {
      ElMessage.warning('请先修复校验问题')
      return
    }
    const defaultEventId = getDefaultEventId()
    const { value: eventId } = await ElMessageBox.prompt('请输入事件ID', '运行管道', {
      inputValue: defaultEventId,
      inputPattern: /\S+/,
      inputErrorMessage: '事件ID不能为空',
    })
    store.runLoading = true
    try {
      const result = await store.runPipeline(eventId)
      ElMessage.success(`管道已启动，运行 ID: ${result.run_id || result.id || '—'}`)
      // C2: 运行成功后跳转到执行历史视图
      router.push('/agent-orchestration/pipeline')
    } catch (e) {
      ElMessage.error('启动失败: ' + (e.message || e))
    } finally {
      store.runLoading = false
    }
  } catch (e) {
    // 用户取消弹窗等 — 不做处理
    if (store.runLoading) store.runLoading = false
  }
}

// ===== 拖拽支持 =====

function onDragOver(event) {
  event.dataTransfer.dropEffect = 'copy'
}

function onDrop(event) {
  const type = event.dataTransfer.getData('application/node-type') ||
               event.dataTransfer.getData('text/plain')
  if (!type) return

  const canvasRect = canvasRef.value?.getBoundingClientRect()
  if (!canvasRect) return

  // H1: 加入 zoom 缩放转换
  const zoom = store.zoomLevel / 100
  const x = (event.clientX - canvasRect.left) / zoom + canvasRef.value.scrollLeft
  const y = (event.clientY - canvasRect.top) / zoom + canvasRef.value.scrollTop

  store.addNode(type, { x, y })
  ElMessage.success(`已添加节点`)
}

// ===== H4: 临时预览线 =====

function onCanvasMouseMove(e) {
  if (!store.connectMode || !store.connectSource) {
    tempLine.value = null
    return
  }
  const sourceNode = store.pipelineNodes.find(n => n.id === store.connectSource)
  if (!sourceNode) return

  const canvasRect = canvasRef.value?.getBoundingClientRect()
  if (!canvasRect) return

  // 源节点出点坐标
  const sx = sourceNode.position.x + 160 + 7
  const sy = sourceNode.position.y + 50

  // 鼠标在画布中的坐标
  const zoom = store.zoomLevel / 100
  const mx = (e.clientX - canvasRect.left) / zoom + canvasRef.value.scrollLeft
  const my = (e.clientY - canvasRect.top) / zoom + canvasRef.value.scrollTop

  const cpOffset = Math.min((mx - sx) / 2, 80)
  tempLine.value = {
    path: `M ${sx} ${sy} C ${sx + cpOffset} ${sy}, ${mx - cpOffset} ${my}, ${mx} ${my}`,
  }
}

function onCanvasClick() {
  if (store.connectMode) {
    store.cancelConnect()
    tempLine.value = null
  }
}

// ===== 窗口大小自适应 =====
function updateCanvasSize() {
  if (canvasWrapRef.value) {
    const rect = canvasWrapRef.value.getBoundingClientRect()
    // canvas area 减去 topbar 高度
    const topbarH = 44
    canvasWidth.value = Math.max(rect.width, 2000)
    canvasHeight.value = Math.max(rect.height - topbarH, 1200)
  }
}

onMounted(() => {
  updateCanvasSize()
  window.addEventListener('resize', updateCanvasSize)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateCanvasSize)
})
</script>

<style scoped>
.canvas-wrap {
  background: var(--color-canvas-inset);
  position: relative;
  overflow: hidden;
}

/* 上操作栏 */
.canvas-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 16px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}
.canvas-topbar .title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default);
}
.canvas-topbar .actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 500;
  border-radius: var(--r-btn);
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-default);
  color: var(--color-fg-muted);
  cursor: pointer;
  white-space: nowrap;
}
.btn:hover {
  background: var(--color-canvas-subtle);
}
.btn-primary {
  background: var(--color-accent-fg);
  color: #fff;
  border-color: var(--color-accent-fg);
}
.btn-primary:hover {
  opacity: 0.9;
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 1.5px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 校验结果条 */
.validation-bar {
  padding: 6px 16px;
  font-size: 11px;
  border-bottom: 0.5px solid var(--color-border-default);
}
.validation-bar.is-valid {
  background: var(--color-success-subtle);
  color: var(--color-success-fg);
}
.validation-bar.is-error {
  background: var(--color-danger-subtle);
  color: var(--color-danger-fg);
}
.validation-msg {
  padding: 1px 0;
}

/* 画布 */
.canvas {
  position: absolute;
  top: 44px;
  left: 0;
  right: 0;
  bottom: 0;
  overflow: auto;
}
.canvas-inner {
  min-width: 2000px;
  min-height: 1200px;
  position: relative;
  background-image:
    linear-gradient(rgba(200,200,200,0.25) 0.5px, transparent 0.5px),
    linear-gradient(90deg, rgba(200,200,200,0.25) 0.5px, transparent 0.5px);
  background-size: 16px 16px;
}

/* 阶段标签 */
.phase-label {
  position: absolute;
  top: 60px;
  font-size: 10px;
  color: var(--color-fg-light);
  letter-spacing: 0.3px;
  white-space: nowrap;
}

/* 对准基线 */
.guide-h {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 0.5px dashed #d4d4d4;
  pointer-events: none;
  z-index: 1;
}
.guide-h-1 {
  top: 330px;
}
.guide-h-2 {
  top: 450px;
}

/* 管道轨道 */
.pipeline-track {
  position: absolute;
  height: 2px;
  background: #d4d4d4;
  z-index: 0;
  pointer-events: none;
}
.track-0 {
  top: 340px;
}
.track-1 {
  top: 450px;
}
.pipeline-track-inner {
  height: 100%;
  background: transparent;
}

/* 步骤指示器 */
.step-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  position: absolute;
  top: 56px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 15;
}
.step-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #d4d4d4;
}
.step-dot.active {
  background: var(--color-accent-fg);
}
.step-label {
  font-size: 10px;
  color: var(--color-fg-light);
  margin: 0 6px;
}
</style>
