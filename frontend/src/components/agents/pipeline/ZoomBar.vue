<template>
  <div class="zoom-bar">
    <button @click="onZoomOut" :disabled="zoom <= 50" title="缩小">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
    </button>
    <span>{{ zoom }}%</span>
    <button @click="onZoomIn" :disabled="zoom >= 200" title="放大">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="12" y1="5" x2="12" y2="19"/>
        <line x1="5" y1="12" x2="19" y2="12"/>
      </svg>
    </button>
    <span class="sep"></span>
    <button @click="onFit" title="适应画布">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>
      </svg>
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { usePipelineEditorStore } from '@/stores/pipelineEditor'

const props = defineProps({
  zoom: {
    type: Number,
    default: 100,
  },
})

const emit = defineEmits(['zoomChange'])

const zoom = computed(() => props.zoom)

function onZoomIn() {
  const newZoom = Math.min(zoom.value + 10, 200)
  emit('zoomChange', newZoom)
}

function onZoomOut() {
  const newZoom = Math.max(zoom.value - 10, 50)
  emit('zoomChange', newZoom)
}

function onFit() {
  const store = usePipelineEditorStore()
  const nodes = store.pipelineNodes
  if (!nodes.length) {
    emit('zoomChange', 100)
    return
  }
  // 计算所有节点的边界
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const NODE_W = 160, NODE_H = 100
  nodes.forEach(n => {
    minX = Math.min(minX, n.position.x)
    minY = Math.min(minY, n.position.y)
    maxX = Math.max(maxX, n.position.x + NODE_W)
    maxY = Math.max(maxY, n.position.y + NODE_H)
  })
  // 加上边距
  const padding = 80
  minX -= padding; minY -= padding; maxX += padding; maxY += padding

  const canvasEl = document.querySelector('.canvas')
  if (!canvasEl) return
  const viewW = canvasEl.clientWidth
  const viewH = canvasEl.clientHeight
  const contentW = maxX - minX
  const contentH = maxY - minY

  // 计算最佳 zoom
  const zoomX = (viewW / contentW) * 100
  const zoomY = (viewH / contentH) * 100
  const fitZoom = Math.floor(Math.min(zoomX, zoomY, 200))
  emit('zoomChange', Math.max(fitZoom, 50))
}
</script>

<style scoped>
.zoom-bar {
  position: absolute;
  bottom: 14px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  padding: 3px 8px;
  z-index: 20;
}
.zoom-bar span {
  font-size: 11px;
  color: var(--color-fg-subtle);
  min-width: 28px;
  text-align: center;
}
.zoom-bar .sep {
  display: inline-block;
  width: 0.5px;
  height: 12px;
  background: var(--color-border-default);
  margin: 0 2px;
  min-width: auto;
}
.zoom-bar button {
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--color-fg-muted);
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.zoom-bar button:hover {
  background: var(--color-canvas-subtle);
}
.zoom-bar button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
</style>
