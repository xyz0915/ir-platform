<template>
  <svg
    class="connection-layer"
    :style="svgStyle"
    ref="svgRef"
    @click.stop="onSvgClick"
  >
    <defs>
      <marker id="arrow-default" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="5" markerHeight="5" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#d4d4d4" />
      </marker>
      <marker id="arrow-accent" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="5" markerHeight="5" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb" />
      </marker>
    </defs>
    <g>
      <path
        v-for="(conn, idx) in connections"
        :key="`conn-${idx}`"
        :d="conn.pathD"
        :class="['conn-path', { 'conn-cross': conn.isCrossTrack, 'branch-active': conn.isBranchActive, 'branch-pruned': conn.isPruned }]"
        :stroke="selectedConnectionIdx === idx ? '#2563eb' : (conn.isHovered ? '#2563eb' : '#d4d4d4')"
        :stroke-width="selectedConnectionIdx === idx ? 2.5 : 1.5"
        :stroke-dasharray="conn.isCrossTrack ? '4 3' : 'none'"
        fill="none"
        :marker-end="(selectedConnectionIdx === idx || conn.isHovered) ? 'url(#arrow-accent)' : 'url(#arrow-default)'"
        @mouseenter="onPathHover(idx, true)"
        @mouseleave="onPathHover(idx, false)"
        @click.stop="onPathClick(idx)"
        @contextmenu.prevent="onPathContextMenu($event, idx)"
      />
    </g>
  </svg>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

const props = defineProps({
  width: { type: Number, default: 0 },
  height: { type: Number, default: 0 },
})

const svgRef = ref(null)
const hoveredIndex = ref(-1)

const store = usePipelineEditorStore()

const selectedConnectionIdx = computed(() => store.selectedConnectionId)

const svgStyle = computed(() => ({
  width: props.width ? `${props.width}px` : '100%',
  height: props.height ? `${props.height}px` : '100%',
}))

// 生成路径数据
const connections = computed(() => {
  const branchPath = store.branchPath || { activeNodes: null, prunedEdges: [] }
  const activeNodes = branchPath.activeNodes instanceof Set ? branchPath.activeNodes : null
  const prunedEdges = branchPath.prunedEdges || []
  return store.connections.map((conn, idx) => {
    const sourceNode = store.pipelineNodes.find(n => n.id === conn.sourceId)
    const targetNode = store.pipelineNodes.find(n => n.id === conn.targetId)
    if (!sourceNode || !targetNode) {
      return { ...conn, pathD: '', isCrossTrack: conn.isCrossTrack || false, isHovered: false, isPruned: false, isBranchActive: false }
    }
    const pathD = computeBezierPath(sourceNode, targetNode)
    // Phase 3 · 分支路径着色：
    // - pruned：边命中 branchPath.prunedEdges（灰虚线）
    // - active：边的两端都在 activeNodes 内（绿实线）
    const isPruned = prunedEdges.some(
      pe => pe.sourceId === conn.sourceId && pe.targetId === conn.targetId,
    )
    const isBranchActive = !!(
      activeNodes
      && conn.sourceId && conn.targetId
      && activeNodes.has(conn.sourceId)
      && activeNodes.has(conn.targetId)
    )
    return {
      ...conn,
      pathD,
      isCrossTrack: conn.isCrossTrack || false,
      isHovered: false,
      isPruned,
      isBranchActive,
    }
  }).filter(conn => conn.pathD !== '')
})

function onPathHover(idx, isHovered) {
  hoveredIndex.value = isHovered ? idx : -1
}

function onPathClick(idx) {
  store.selectConnection(idx)
}

function onPathContextMenu(event, idx) {
  store.selectConnection(idx)
  ElMessageBox.confirm('删除此连线？', '确认', {
    confirmButtonText: '删除',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    store.removeConnectionByIndex(idx)
  }).catch(() => {})
}

function onSvgClick() {
  // 点击 SVG 背景空白处取消连线选中
  if (store.selectedConnectionId !== null) {
    store.selectedConnectionId = null
  }
}

function onKeyDown(e) {
  // 如果焦点在输入框中，不处理键盘事件
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable) return
  if ((e.key === 'Delete' || e.key === 'Backspace') && store.selectedConnectionId !== null) {
    store.removeConnectionByIndex(store.selectedConnectionId)
    e.preventDefault()
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeyDown)
})

/**
 * 计算从源节点到目标节点的贝塞尔曲线路径。
 *
 * 节点宽度: 160px, 节点高度: 100px
 * cn-out: right: -7px, top: 50%  → (x + 160 + 7, y + 50)
 * cn-in:  left: -7px, top: 50%   → (x - 7, y + 50)
 *
 * 同层 → 水平贝塞尔曲线（实线）
 * 跨层 → 先垂直再水平再垂直（虚线）
 *
 * @param {object} sourceNode
 * @param {object} targetNode
 * @returns {string} SVG path d attribute
 */
function computeBezierPath(sourceNode, targetNode) {
  // 源节点出点坐标
  const sx = sourceNode.position.x + 160 + 7
  const sy = sourceNode.position.y + 50

  // 目标节点入点坐标
  const tx = targetNode.position.x - 7
  const ty = targetNode.position.y + 50

  const crossTrack = sourceNode.track !== targetNode.track

  if (!crossTrack) {
    // 同层水平线
    const cpOffset = Math.min((tx - sx) / 2, 80)
    return `M ${sx} ${sy} C ${sx + cpOffset} ${sy}, ${tx - cpOffset} ${ty}, ${tx} ${ty}`
  } else {
    // 跨层：先垂直再水平再垂直
    const midY = (sy + ty) / 2
    return `M ${sx} ${sy} C ${sx} ${midY}, ${tx} ${midY}, ${tx} ${ty}`
  }
}
</script>

<style scoped>
.connection-layer {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 3;
  overflow: visible;
}
.conn-path {
  cursor: pointer;
  pointer-events: stroke;
  transition: stroke 0.12s;
}
.conn-path:hover {
  stroke: #2563eb;
}
/* Phase 3 · 分支路径着色（!important 覆盖内联 stroke） */
.conn-path.branch-active {
  stroke: #2f9e44 !important;
  stroke-width: 2.5px !important;
  stroke-dasharray: none !important;
}
.conn-path.branch-pruned {
  stroke: #b0b0b0 !important;
  stroke-width: 1.5px !important;
  stroke-dasharray: 5 4 !important;
  opacity: 0.7;
}
</style>
