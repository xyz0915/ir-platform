<template>
  <div class="graph-panel" ref="panelRef">
    <div class="gp-toolbar">
      <GraphLegend />
      <button class="gp-fit-btn" @click="fitToScreen" title="缩放到全部显示">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2 5V2H5M10 5V2H7M2 7V10H5M10 7V10H7" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        适应屏幕
      </button>
    </div>

    <div class="gp-sep"></div>

    <!-- SVG 画布 -->
    <svg
      ref="svgRef"
      class="gp-svg"
      :width="svgWidth"
      :height="svgHeight"
      @mousedown="onSvgMouseDown"
      @mousemove="onSvgMouseMove"
      @mouseup="onSvgMouseUp"
      @mouseleave="onSvgMouseUp"
      @wheel.prevent="onSvgWheel"
    >
      <defs>
        <!-- 箭头标记 -->
        <marker
          id="arrowhead"
          viewBox="0 0 10 10"
          refX="10"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0 0L10 5L0 10z" fill="#64748b" />
        </marker>

        <!-- 节点类型渐变（带轻微立体感） -->
        <linearGradient id="grad-host" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#F87171" />
          <stop offset="100%" stop-color="#DC2626" />
        </linearGradient>
        <linearGradient id="grad-url" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#60A5FA" />
          <stop offset="100%" stop-color="#2563EB" />
        </linearGradient>
        <linearGradient id="grad-action" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#FBBF24" />
          <stop offset="100%" stop-color="#D97706" />
        </linearGradient>
        <linearGradient id="grad-file" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#6EE7B7" />
          <stop offset="100%" stop-color="#059669" />
        </linearGradient>
        <linearGradient id="grad-process" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#C084FC" />
          <stop offset="100%" stop-color="#7C3AED" />
        </linearGradient>
        <linearGradient id="grad-default" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#9CA3AF" />
          <stop offset="100%" stop-color="#6B7280" />
        </linearGradient>
      </defs>

      <g :transform="`translate(${panX}, ${panY}) scale(${zoom})`">
        <!-- 边（用 Q 路径画曲线，引用树布局的边） -->
        <g v-for="edge in treeEdges" :key="edge.id">
          <path
            :d="edgePath(edge)"
            class="gp-edge"
            :class="['rel-' + (edge.relation || '关联')]"
            fill="none"
          />
        </g>

        <!-- 节点（胶囊形 + 类型图标 + 内部 label） -->
        <g
          v-for="node in renderedNodes"
          :key="node.id"
          class="gp-node"
          :class="{ dragging: dragNodeId === node.id }"
          :transform="`translate(${node.x || 0}, ${node.y || 0})`"
          @mousedown.stop="onNodeMouseDown(node, $event)"
          @mouseenter="onNodeHover(node, $event)"
          @mouseleave="onNodeHoverOut"
          @click.stop="onNodeClick(node)"
          @dblclick.stop="onNodeDblClick(node)"
        >
          <!-- 阴影 -->
          <rect
            :x="-pillWidth(node) / 2"
            :y="-pillHeight / 2"
            :width="pillWidth(node)"
            :height="pillHeight"
            :rx="pillHeight / 2"
            :ry="pillHeight / 2"
            class="gp-node-shadow"
            :fill="nodeColor(node.type)"
            opacity="0.18"
            :transform="`translate(0, 2)`"
          />
          <!-- 胶囊主体 -->
          <rect
            :x="-pillWidth(node) / 2"
            :y="-pillHeight / 2"
            :width="pillWidth(node)"
            :height="pillHeight"
            :rx="pillHeight / 2"
            :ry="pillHeight / 2"
            :fill="nodeColor(node.type)"
            stroke="#fff"
            stroke-width="1.5"
          />
          <!-- 类型小图标 + 标签 -->
          <text
            :x="0"
            y="4"
            text-anchor="middle"
            fill="#fff"
            font-size="11"
            font-weight="500"
            style="pointer-events: none; user-select: none;"
          >{{ nodePillText(node) }}</text>
          <!-- 组节点 count 徽标（聚合节点才有） -->
          <g v-if="node.count && node.count > 1" :transform="`translate(${pillWidth(node) / 2 - 6}, ${-pillHeight / 2 + 2})`">
            <circle cx="0" cy="0" r="9" fill="#fbbf24" stroke="#fff" stroke-width="1.5"/>
            <text x="0" y="3" text-anchor="middle" fill="#7c2d12" font-size="10" font-weight="700" style="pointer-events: none; user-select: none;">{{ node.count }}</text>
          </g>
        </g>
      </g>

      <!-- Tooltip -->
      <g v-if="hoveredNode" class="gp-tooltip-group">
        <rect
          :x="tooltipX"
          :y="tooltipY"
          :width="tooltipWidth"
          :height="tooltipHeight"
          rx="6"
          fill="rgba(15, 23, 42, 0.95)"
          stroke="#475569"
          stroke-width="0.5"
        />
        <text :x="tooltipX + 8" :y="tooltipY + 14" fill="#fff" font-size="11" font-weight="600">
          {{ hoveredNode.label || hoveredNode.id }}
        </text>
        <text :x="tooltipX + 8" :y="tooltipY + 28" fill="#cbd5e1" font-size="10">
          {{ typeLabel(hoveredNode.type) }} · {{ hoveredNode.id }}
        </text>
        <text v-if="hoveredNode.properties?.severity" :x="tooltipX + 8" :y="tooltipY + 42" fill="#fbbf24" font-size="10">
          严重度: {{ hoveredNode.properties.severity }}
        </text>
      </g>
    </svg>

    <!-- 节点详情抽屉（点击胶囊后弹出） -->
    <transition name="gp-detail-fade">
      <div v-if="selectedNode" class="gp-detail-panel" @click.stop>
        <div class="gp-detail-header">
          <div class="gp-detail-title">
            <span class="gp-detail-icon" :style="{ background: nodeColor(selectedNode.type) }">
              {{ nodeIcon(selectedNode.type) }}
            </span>
            <div>
              <div class="gp-detail-label">{{ selectedNode.label || selectedNode.id }}</div>
              <div class="gp-detail-type">{{ typeLabel(selectedNode.type) }} · {{ selectedNode.id.slice(0, 50) }}{{ selectedNode.id.length > 50 ? '…' : '' }}</div>
            </div>
          </div>
          <button class="gp-detail-close" @click="selectedNode = null" title="关闭">×</button>
        </div>

        <div class="gp-detail-body">
          <!-- 基础属性 -->
          <section class="gp-section">
            <h4>基础属性</h4>
            <table class="gp-attr-table">
              <tr v-for="(val, key) in selectedNode.properties || {}" :key="key">
                <td class="gp-attr-k">{{ key }}</td>
                <td class="gp-attr-v">{{ formatAttr(val) }}</td>
              </tr>
            </table>
          </section>

          <!-- 聚合节点的 originalIds 列表 -->
          <section v-if="(selectedNode.originalIds || []).length > 1" class="gp-section">
            <h4>聚合证据 ({{ selectedNode.originalIds.length }} 条)</h4>
            <ul class="gp-id-list">
              <li v-for="id in selectedNode.originalIds" :key="id">{{ id }}</li>
            </ul>
          </section>

          <!-- 关联的 Step -->
          <section class="gp-section">
            <h4>关联调查步骤</h4>
            <div v-if="relatedSteps.length === 0" class="gp-empty">该节点未出现在任何 Step</div>
            <div v-for="(s, i) in relatedSteps" :key="s.step_id" class="gp-related-step">
              <div class="gp-rs-header">
                <span class="gp-rs-agent">{{ s.agent }}</span>
                <span class="gp-rs-stage">{{ s.stage }}</span>
                <span class="gp-rs-status">{{ s.status === 'completed' ? '✓' : s.status === 'running' ? '⏳' : s.status === 'failed' ? '✗' : s.status }}</span>
              </div>
              <div class="gp-rs-output">{{ truncate(s.output, 200) }}</div>
            </div>
          </section>
        </div>
      </div>
    </transition>

    <!-- 空状态 -->
    <div v-if="renderedNodes.length === 0" class="gp-empty">
      <p>暂无证据图谱数据</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import GraphLegend from './GraphLegend.vue'
import { ForceLayout } from './ForceLayout'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  steps: { type: Array, default: () => [] },  // 新增：关联调查步骤列表
})

const emit = defineEmits(['node-click'])

// 详情面板
const selectedNode = ref(null)

function onNodeClick(node) {
  selectedNode.value = node
  emit('node-click', node)
}

function onNodeDblClick(node) {
  // 双击节点：以该节点为根重新布局（下钻）
  if (layout) {
    layout.setRoot(node.id)
    renderedNodes.value = [...layout.nodes]
    treeEdges.value = layout.getTreeEdges() || []
    selectedNode.value = node
    nextTick(() => fitToScreen())
  }
}

function closeDetail() {
  selectedNode.value = null
}

const relatedSteps = computed(() => {
  if (!selectedNode.value) return []
  const targetIds = new Set(selectedNode.value.originalIds || [selectedNode.value.id])
  return props.steps.filter(s => {
    const ev = s.evidence_json
    if (!ev) return false
    if (Array.isArray(ev)) {
      return ev.some(e => targetIds.has(e.ref || e.id))
    }
    if (ev.data_sources) {
      return ev.data_sources.some(src => targetIds.has(src.id || src.ref))
    }
    return false
  })
})

function formatAttr(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'object') return JSON.stringify(val)
  if (typeof val === 'string' && val.length > 100) return val.slice(0, 100) + '…'
  return val
}

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}

const panelRef = ref(null)
const svgRef = ref(null)
const svgWidth = ref(600)
const svgHeight = ref(400)

const pillHeight = 28       // 胶囊高度
const pillBaseWidth = 80    // 胶囊基础宽度
const pillCharWidth = 7     // 每个字符宽度估算

// 树边（由 ForceLayout 的 _treeEdges 暴露）
const treeEdges = ref([])

function pillWidth(node) {
  const text = nodePillText(node)
  // 中文字符按 2 倍宽度估算
  let width = 0
  for (const ch of text) {
    width += /[\u4e00-\u9fa5]/.test(ch) ? pillCharWidth * 1.4 : pillCharWidth
  }
  return Math.max(pillBaseWidth, width + 36) // 36 = 左右内边距
}

function nodePillText(node) {
  // 内部显示：类型图标 + 简称
  const icon = nodeIcon(node.type)
  const label = nodeLabel(node)
  return `${icon} ${label}`
}

// Pan / Zoom
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
let isPanning = false
let panStartX = 0
let panStartY = 0
let panStartPanX = 0
let panStartPanY = 0

// Drag
const dragNodeId = ref(null)
let dragNode = null
let dragStartX = 0
let dragStartY = 0
let mouseMoveHandler = null
let mouseUpHandler = null

// Tooltip
const hoveredNode = ref(null)
const tooltipX = ref(0)
const tooltipY = ref(0)
const tooltipWidth = ref(160)
const tooltipHeight = ref(48)

// Layout
let layout = null
const renderedNodes = ref([])
const renderedEdges = ref([])

// 类型 → 渐变 ID / 图标
const TYPE_META = {
  host:    { gradient: 'url(#grad-host)',    icon: 'H', label: '主机' },
  url:     { gradient: 'url(#grad-url)',     icon: 'U', label: '资源' },
  action:  { gradient: 'url(#grad-action)',  icon: 'A', label: '动作' },
  file:    { gradient: 'url(#grad-file)',    icon: 'F', label: '文件' },
  process: { gradient: 'url(#grad-process)', icon: 'P', label: '进程' },
}

function nodeColor(type) {
  return TYPE_META[type]?.gradient || 'url(#grad-default)'
}

function nodeIcon(type) {
  return TYPE_META[type]?.icon || '?'
}

function typeLabel(type) {
  return TYPE_META[type]?.label || type
}

function labelWidth(node) {
  const len = (node.label || node.id || '?').length
  return Math.max(len * 7, 20)
}

function nodeLabel(node) {
  const lbl = node.label || node.id || '?'
  if (lbl.length > 16) return lbl.substring(0, 15) + '…'
  return lbl
}

function getNodeX(nodeId) {
  const n = renderedNodes.value.find(n => n.id === nodeId)
  return n ? (n.x || 0) : 0
}

function getNodeY(nodeId) {
  const n = renderedNodes.value.find(n => n.id === nodeId)
  return n ? (n.y || 0) : 0
}

// 计算边路径（带曲线） — 用二次贝塞尔，控制点在两端中点垂直偏移
function edgePath(edge) {
  const x1 = getNodeX(edge.source)
  const y1 = getNodeY(edge.source)
  const x2 = getNodeX(edge.target)
  const y2 = getNodeY(edge.target)
  if (x1 === 0 && y1 === 0) return ''
  if (x2 === 0 && y2 === 0) return ''
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  // 偏移量：让两条相同起终点的边不重叠
  const hash = (edge.id || '').split('').reduce((a, c) => a + c.charCodeAt(0), 0)
  const offset = (hash % 5) * 8 - 16
  // 垂直中点的偏移
  const dx = x2 - x1
  const dy = y2 - y1
  const len = Math.sqrt(dx * dx + dy * dy) || 1
  // 偏移方向（垂直于线段）
  const px = -dy / len * offset
  const py = dx / len * offset
  // 裁剪到节点边缘（用 pillHeight/2 近似胶囊半径）
  const r = pillHeight / 2
  const ux = (dx / len) * r
  const uy = (dy / len) * r
  const sx1 = x1 + ux
  const sy1 = y1 + uy
  const sx2 = x2 - ux
  const sy2 = y2 - uy
  return `M ${sx1} ${sy1} Q ${mx + px} ${my + py} ${sx2} ${sy2}`
}

// Fit to Screen
function fitToScreen() {
  if (!layout || renderedNodes.value.length === 0) return
  const bounds = layout.getBounds()
  if (!bounds) return
  const padding = 60
  const w = bounds.width + padding * 2
  const h = bounds.height + padding * 2
  const scaleX = svgWidth.value / w
  const scaleY = svgHeight.value / h
  const scale = Math.min(scaleX, scaleY, 1.5)
  zoom.value = scale
  // 居中
  panX.value = (svgWidth.value - bounds.width * scale) / 2 - bounds.minX * scale + padding * scale
  panY.value = (svgHeight.value - bounds.height * scale) / 2 - bounds.minY * scale + padding * scale
}

// 重新运行布局
function runLayout() {
  const w = svgWidth.value
  const h = svgHeight.value

  if (!layout) {
    layout = new ForceLayout(
      props.nodes.map(n => ({ ...n })),
      props.edges.map(e => ({ ...e })),
      w,
      h
    )
  } else {
    layout.width = w
    layout.height = h
    for (const n of props.nodes) {
      if (!layout.nodes.find(en => en.id === n.id)) {
        layout.addNode({ ...n })
      }
    }
    for (const e of props.edges) {
      if (!layout.edges.find(ee => ee.id === e.id)) {
        layout.addEdge({ ...e })
      }
    }
  }

  const isNewData = props.nodes.length > renderedNodes.value.length
  layout.run()

  renderedNodes.value = [...layout.nodes]
  treeEdges.value = layout.getTreeEdges() || []

  // 首次或新数据时自动 fit
  if (isNewData || renderedNodes.value.length === props.nodes.length) {
    nextTick(() => fitToScreen())
  }
}

watch(
  () => [props.nodes.length, props.edges.length],
  () => {
    runLayout()
  },
  { deep: false }
)

onMounted(() => {
  if (panelRef.value) {
    const rect = panelRef.value.getBoundingClientRect()
    svgWidth.value = Math.max(rect.width - 20, 300)
    svgHeight.value = Math.max(rect.height - 40, 200)
  }
  if (props.nodes.length > 0) {
    runLayout()
  }

  // 窗口大小变化时重新 fit
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  if (mouseMoveHandler) window.removeEventListener('mousemove', mouseMoveHandler)
  if (mouseUpHandler) window.removeEventListener('mouseup', mouseUpHandler)
  if (tooltipTimer) clearTimeout(tooltipTimer)
  window.removeEventListener('resize', onResize)
})

let resizeTimer = null
function onResize() {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    if (panelRef.value) {
      const rect = panelRef.value.getBoundingClientRect()
      svgWidth.value = Math.max(rect.width - 20, 300)
      svgHeight.value = Math.max(rect.height - 40, 200)
      if (layout) {
        layout.width = svgWidth.value
        layout.height = svgHeight.value
        layout.run(30)
        renderedNodes.value = [...layout.nodes]
        nextTick(() => fitToScreen())
      }
    }
  }, 200)
}

// SVG Pan
function onSvgMouseDown(e) {
  const target = e.target
  if (target === svgRef.value || target.classList.contains('gp-svg') || target.tagName === 'svg') {
    isPanning = true
    panStartX = e.clientX
    panStartY = e.clientY
    panStartPanX = panX.value
    panStartPanY = panY.value
  }
}

function onSvgMouseMove(e) {
  if (isPanning) {
    panX.value = panStartPanX + (e.clientX - panStartX)
    panY.value = panStartPanY + (e.clientY - panStartY)
  }
}

function onSvgMouseUp() {
  isPanning = false
}

function onSvgWheel(e) {
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  zoom.value = Math.max(0.3, Math.min(3, zoom.value * delta))
}

// Node Drag
function onNodeMouseDown(node, e) {
  dragNodeId.value = node.id
  dragNode = node
  dragStartX = e.clientX
  dragStartY = e.clientY
  e.stopPropagation()

  mouseMoveHandler = (ev) => {
    if (dragNode) {
      const dx = (ev.clientX - dragStartX) / zoom.value
      const dy = (ev.clientY - dragStartY) / zoom.value
      dragNode.x += dx
      dragNode.y += dy
      dragStartX = ev.clientX
      dragStartY = ev.clientY
    }
  }

  mouseUpHandler = () => {
    window.removeEventListener('mousemove', mouseMoveHandler)
    window.removeEventListener('mouseup', mouseUpHandler)
    mouseMoveHandler = null
    mouseUpHandler = null
    dragNodeId.value = null
    dragNode = null
  }

  window.addEventListener('mousemove', mouseMoveHandler)
  window.addEventListener('mouseup', mouseUpHandler)
}

// Tooltip
let tooltipTimer = null

function onNodeHover(node, e) {
  if (tooltipTimer) clearTimeout(tooltipTimer)
  tooltipTimer = setTimeout(() => {
    const svgRect = svgRef.value?.getBoundingClientRect()
    if (svgRect) {
      const clientX = e.clientX - svgRect.left
      const clientY = e.clientY - svgRect.top
      // 浮在节点右上方
      tooltipX.value = (clientX - panX.value) / zoom.value + 24
      tooltipY.value = (clientY - panY.value) / zoom.value - 30
      const lbl = node.label || node.id || ''
      tooltipWidth.value = Math.max(lbl.length * 7 + 24, 160)
      tooltipHeight.value = 48
    }
    hoveredNode.value = node
  }, 250)
}

function onNodeHoverOut() {
  if (tooltipTimer) clearTimeout(tooltipTimer)
  tooltipTimer = setTimeout(() => {
    hoveredNode.value = null
  }, 150)
}
</script>

<style scoped>
.graph-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
}
.gp-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--color-canvas-default);
  flex-shrink: 0;
}
.gp-fit-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-size: 11px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  background: var(--color-canvas-subtle);
  color: var(--color-fg-muted);
  cursor: pointer;
  transition: all 0.15s;
}
.gp-fit-btn:hover {
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
}
.gp-sep {
  height: 1px;
  background: var(--color-border-default);
  margin: 0 12px;
  flex-shrink: 0;
}
.gp-svg {
  flex: 1;
  cursor: grab;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.08) 1px, transparent 1px);
  background-size: 24px 24px;
  background-position: -1px -1px;
}
.gp-svg:active {
  cursor: grabbing;
}
.gp-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: var(--color-fg-muted);
  font-size: 13px;
  pointer-events: none;
}

/* 节点 */
.gp-node {
  cursor: pointer;
  transition: filter 0.15s;
}
.gp-node:hover {
  filter: brightness(1.15) drop-shadow(0 4px 8px rgba(0, 0, 0, 0.18));
}
.gp-node.dragging {
  cursor: grabbing;
  filter: brightness(1.2) drop-shadow(0 6px 12px rgba(0, 0, 0, 0.25));
}
.gp-node-shadow {
  opacity: 0.15;
  filter: blur(4px);
  pointer-events: none;
}

/* 边 */
.gp-edge {
  stroke-width: 1.5;
  stroke-linecap: round;
  fill: none;
  transition: stroke-width 0.15s;
}
.gp-edge:hover {
  stroke-width: 2.5;
}
.gp-edge.rel-连接 { stroke: #64748b; }
.gp-edge.rel-启动 { stroke: #d97706; }
.gp-edge.rel-包含 { stroke: #2563eb; }
.gp-edge.rel-关联 { stroke: #64748b; }

.gp-tooltip-group {
  pointer-events: none;
}

/* 详情面板过渡 */
.gp-detail-fade-enter-active, .gp-detail-fade-leave-active {
  transition: all 0.2s ease;
}
.gp-detail-fade-enter-from, .gp-detail-fade-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
.gp-detail-panel {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 360px;
  background: var(--color-canvas-default, #fff);
  border-left: 0.5px solid var(--color-border-default, #e2e8f0);
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  z-index: 50;
  overflow: hidden;
}
.gp-detail-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 0.5px solid var(--color-border-default, #e2e8f0);
  background: var(--color-canvas-subtle, #f8fafc);
}
.gp-detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.gp-detail-icon {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  font-size: 12px;
  flex-shrink: 0;
}
.gp-detail-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-fg-default, #1e293b);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gp-detail-type {
  font-size: 10px;
  color: var(--color-fg-subtle, #64748b);
  font-family: monospace;
  margin-top: 2px;
}
.gp-detail-close {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  font-size: 18px;
  line-height: 1;
  color: var(--color-fg-subtle, #64748b);
  cursor: pointer;
  border-radius: 4px;
}
.gp-detail-close:hover {
  background: var(--color-canvas-inset, #f1f5f9);
  color: var(--color-fg-default, #1e293b);
}
.gp-detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}
.gp-section {
  margin-bottom: 16px;
}
.gp-section h4 {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--color-fg-subtle, #64748b);
  margin: 0 0 6px;
  letter-spacing: 0.5px;
}
.gp-attr-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.gp-attr-table tr {
  border-bottom: 0.5px solid var(--color-border-muted, #e2e8f0);
}
.gp-attr-k {
  padding: 4px 8px 4px 0;
  color: var(--color-fg-subtle, #64748b);
  font-family: monospace;
  width: 40%;
  vertical-align: top;
}
.gp-attr-v {
  padding: 4px 0;
  color: var(--color-fg-default, #1e293b);
  word-break: break-all;
}
.gp-id-list {
  margin: 0;
  padding: 0;
  list-style: none;
  font-family: monospace;
  font-size: 11px;
  color: var(--color-fg-default, #1e293b);
  max-height: 200px;
  overflow-y: auto;
}
.gp-id-list li {
  padding: 3px 6px;
  border-bottom: 0.5px solid var(--color-border-muted, #e2e8f0);
  word-break: break-all;
}
.gp-related-step {
  border: 0.5px solid var(--color-border-default, #e2e8f0);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 6px;
  background: var(--color-canvas-subtle, #f8fafc);
}
.gp-rs-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  margin-bottom: 4px;
}
.gp-rs-agent {
  font-weight: 600;
  color: var(--color-accent-fg, #2563eb);
}
.gp-rs-stage {
  color: var(--color-fg-subtle, #64748b);
}
.gp-rs-status {
  margin-left: auto;
  color: var(--color-fg-subtle, #64748b);
}
.gp-rs-output {
  font-size: 11px;
  color: var(--color-fg-default, #1e293b);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.gp-detail-body .gp-empty {
  position: static;
  transform: none;
  font-size: 11px;
  font-style: italic;
  padding: 12px 0;
  pointer-events: auto;
}
</style>
