<template>
  <div class="attack-chain-timeline" ref="containerRef">
    <!-- 主时间轴区域 -->
    <div class="timeline-canvas" ref="canvasRef" @wheel.prevent="onWheel">
      <!-- ATT&CK 阶段背景色带 -->
      <div
        v-for="(stage, idx) in stageBands"
        :key="idx"
        class="stage-band"
        :style="{
          left: stage.left + 'px',
          width: stage.width + 'px',
          backgroundColor: stage.color,
        }"
        :title="stage.label"
      />

      <!-- 攻击链行 -->
      <div
        v-for="chain in displayChains"
        :key="chain.chainId"
        class="chain-row"
        :style="{ top: chainRowTop(chain) + 'px' }"
      >
        <!-- 链标签 -->
        <span class="chain-label" :title="chain.chainId || '未分组'">
          {{ chain.chainId ? chain.chainId.substring(0, 12) + '...' : '未分组' }}
        </span>

        <!-- 事件节点连线 -->
        <svg class="chain-line" :width="canvasWidth" :height="rowHeight">
          <line
            v-if="chain.events.length > 1"
            :x1="eventX(chain.events[0])"
            :y1="rowHeight / 2"
            :x2="eventX(chain.events[chain.events.length - 1])"
            :y2="rowHeight / 2"
            stroke="#e5e5e5"
            stroke-width="1"
          />
        </svg>

        <!-- 事件节点 -->
        <div
          v-for="ev in chain.events"
          :key="ev.id"
          class="event-node"
          :class="{ active: selectedId === ev.id }"
          :style="{
            left: eventX(ev) + 'px',
            top: '4px',
            backgroundColor: severityColor(ev.severity),
          }"
          :title="`${ev.event_type} @ ${formatTime(ev.timestamp)} [${ev.severity}]`"
          @click.stop="$emit('select-event', ev.id)"
        />
      </div>

      <!-- 事件密度图（chains 为空时显示） -->
      <div v-if="chains.length === 0 && events.length > 0" class="density-row">
        <div class="density-label">事件密度</div>
        <div class="density-chart">
          <div
            v-for="(bar, idx) in densityBars"
            :key="idx"
            class="density-bar"
            :style="{ left: bar.x + 'px', width: bar.width + 'px', height: bar.height + 'px', bottom: '0', backgroundColor: bar.color }"
            :title="bar.tooltip"
            @click.stop="$emit('select-event', bar.eventId)"
          />
        </div>
      </div>

      <!-- X 轴时间刻度 -->
      <div class="time-axis" :style="{ width: canvasWidth + 'px' }">
        <div
          v-for="(tick, idx) in timeTicks"
          :key="idx"
          class="time-tick"
          :style="{ left: tick.x + 'px' }"
        >
          <span>{{ tick.label }}</span>
        </div>
      </div>
    </div>

    <!-- Minimap -->
    <div class="timeline-minimap" ref="minimapRef">
      <div class="minimap-track" ref="trackRef">
        <div
          v-for="ev in allEvents"
          :key="ev.id"
          class="minimap-dot"
          :style="{
            left: minimapX(ev) + 'px',
            backgroundColor: severityColor(ev.severity),
          }"
        />
        <div
          class="minimap-viewport"
          :style="{ left: viewportLeft + '%', width: viewportWidth + '%' }"
          @mousedown="onMinimapDragStart"
        />
      </div>
    </div>

    <!-- 状态栏 -->
    <div class="status-bar">
      <span class="status-text">系统状态: 运行中</span>
      <span class="status-events">事件: {{ allEvents.length }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'

const props = defineProps({
  chains: { type: Array, default: () => [] },
  events: { type: Array, default: () => [] },
})

const emit = defineEmits(['select-event'])

const containerRef = ref(null)
const canvasRef = ref(null)
const minimapRef = ref(null)
const trackRef = ref(null)

const selectedId = ref('')
const scrollLeft = ref(0)
const canvasWidth = ref(1200)
const rowHeight = 28

// 严重等级颜色
const SEV_COLORS = {
  critical: '#dc2626',
  high: '#dc2626',
  medium: '#d97706',
  low: '#2563eb',
  info: '#a3a3a3',
}

// ATT&CK 阶段颜色
const STAGE_COLORS = {
  initial_access: '#f5f5f5',
  execution: '#f5f5f5',
  persistence: '#f5f5f5',
  privilege_escalation: '#f5f5f5',
  defense_evasion: '#f5f5f5',
  credential_access: '#f5f5f5',
  discovery: '#f5f5f5',
  lateral_movement: '#f5f5f5',
  collection: '#f5f5f5',
  command_and_control: '#f5f5f5',
  exfiltration: '#f5f5f5',
  impact: '#f5f5f5',
  unknown: '#f5f5f5',
}

const STAGE_LABELS = {
  initial_access: '初始访问',
  execution: '执行',
  persistence: '持久化',
  privilege_escalation: '提权',
  defense_evasion: '防御规避',
  credential_access: '凭据访问',
  discovery: '发现',
  lateral_movement: '横向移动',
  collection: '收集',
  command_and_control: 'C2',
  exfiltration: '外泄',
  impact: '影响',
  unknown: '未知',
}

// 所有事件（扁平化）
const allEvents = computed(() => {
  const result = []
  for (const chain of props.chains) {
    for (const ev of chain.events || []) {
      result.push({ ...ev, _chainId: chain.chain_id })
    }
  }
  // 兼容：chains 为空但 events 有数据时，把 events 视为所有事件
  if (result.length === 0 && props.events.length > 0) {
    for (const ev of props.events) {
      result.push({ ...ev })
    }
  }
  return result
})

// 时间范围
const timeRange = computed(() => {
  const events = allEvents.value
  if (!events.length) return { min: Date.now() - 3600000, max: Date.now() }
  let min = Infinity; let max = -Infinity
  for (const ev of events) {
    const t = new Date(ev.timestamp).getTime()
    if (t < min) min = t
    if (t > max) max = t
  }
  if (min === max) max = min + 60000
  return { min, max }
})

// 事件密度柱状图（chains 为空时渲染）
const densityBars = computed(() => {
  if (props.chains.length > 0 || props.events.length === 0) return []
  const sorted = [...props.events].sort((a, b) =>
    new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  )
  const firstTs = new Date(sorted[0].timestamp).getTime()
  const lastTs = new Date(sorted[sorted.length - 1].timestamp).getTime()
  if (lastTs <= firstTs) return []

  const bucketCount = Math.min(80, Math.max(20, Math.floor(canvasWidth.value / 18)))
  const bucketSize = (lastTs - firstTs) / bucketCount
  if (bucketSize === 0) return []

  const buckets = Array.from({ length: bucketCount }, () => [])
  for (const ev of sorted) {
    const idx = Math.min(bucketCount - 1, Math.floor(
      (new Date(ev.timestamp).getTime() - firstTs) / bucketSize
    ))
    buckets[idx].push(ev)
  }

  const maxCount = Math.max(...buckets.map(b => b.length), 1)
  const width = Math.max(1, canvasWidth.value / bucketCount - 1)
  const heightMax = 60

  return buckets.map((items, idx) => {
    const count = items.length
    const x = (idx / bucketCount) * (canvasWidth.value - 0)
    const h = count > 0 ? (count / maxCount) * heightMax : 0
    const color = count > 0 ? severityColor(items[0].severity) : 'transparent'
    return {
      x, width, height: h, color,
      tooltip: count > 0
        ? `${items.length} events @ ${new Date(items[0].timestamp).toLocaleString('zh-CN')}`
        : '',
      eventId: count > 0 ? items[0].id : null,
    }
  })
})

// 显示用的链（添加序号）
const displayChains = computed(() => {
  return props.chains.map((chain, idx) => ({
    ...chain,
    chainId: chain.chain_id || `single-${idx}`,
    displayIdx: idx,
    events: (chain.events || []).sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    ),
  }))
})

// 事件 X 坐标
function eventX(ev) {
  const t = new Date(ev.timestamp).getTime()
  const ratio = (t - timeRange.value.min) / (timeRange.value.max - timeRange.value.min)
  return 60 + ratio * (canvasWidth.value - 80)
}

// Minimap X 坐标
function minimapX(ev) {
  const t = new Date(ev.timestamp).getTime()
  const ratio = (t - timeRange.value.min) / (timeRange.value.max - timeRange.value.min)
  return ratio * 100
}

// 链行 top
function chainRowTop(chain) {
  return chain.displayIdx * rowHeight + 4
}

// 严重等级颜色
function severityColor(sev) {
  return SEV_COLORS[sev] || '#a3a3a3'
}

// 时间格式化
function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// 时间刻度
const timeTicks = computed(() => {
  const { min, max } = timeRange.value
  const duration = max - min
  const count = Math.min(8, Math.floor(canvasWidth.value / 100))
  const step = duration / count
  const ticks = []
  for (let i = 0; i <= count; i++) {
    const t = new Date(min + step * i)
    ticks.push({
      x: 60 + (i / count) * (canvasWidth.value - 80),
      label: t.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    })
  }
  return ticks
})

// ATT&CK 阶段色带
const stageBands = computed(() => {
  const { min, max } = timeRange.value
  const duration = max - min
  if (!duration) return []
  const bands = []
  for (const chain of props.chains) {
    for (const ev of chain.events || []) {
      const stage = ev.attack_stage || 'unknown'
      const t = new Date(ev.timestamp).getTime()
      const left = 60 + ((t - min) / duration) * (canvasWidth.value - 80)
      // 每个事件单独一个小色块表示阶段
      bands.push({
        left,
        width: 10,
        color: STAGE_COLORS[stage] || '#f5f5f5',
        label: STAGE_LABELS[stage] || stage,
      })
    }
  }
  return bands
})

// 视口相关
const viewportLeft = ref(0)
const viewportWidth = ref(100)

// Minimap 拖拽
let isDragging = false
function onMinimapDragStart(e) {
  isDragging = true
  const track = trackRef.value
  if (!track) return
  const rect = track.getBoundingClientRect()
  const startX = e.clientX
  const startLeft = viewportLeft.value

  function onMove(ev) {
    if (!isDragging) return
    const dx = ((ev.clientX - startX) / rect.width) * 100
    viewportLeft.value = Math.max(0, Math.min(100 - viewportWidth.value, startLeft + dx))
  }

  function onUp() {
    isDragging = false
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

// 滚轮缩放
function onWheel(e) {
  // 简单缩放 canvas 宽度
  const delta = e.deltaY > 0 ? -100 : 100
  canvasWidth.value = Math.max(600, Math.min(5000, canvasWidth.value + delta))
}

// 选择事件
function selectEvent(eventId) {
  selectedId.value = eventId
}
</script>

<style scoped>
.attack-chain-timeline {
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

.timeline-canvas {
  flex: 1;
  overflow-x: auto;
  overflow-y: hidden;
  position: relative;
  min-height: 80px;
}

.stage-band {
  position: absolute;
  top: 0;
  bottom: 24px;
  opacity: 0.3;
  pointer-events: none;
}

.chain-row {
  position: absolute;
  left: 0;
  right: 0;
  height: v-bind(rowHeight + 'px');
  display: flex;
  align-items: center;
}

.chain-label {
  position: absolute;
  left: 2px;
  font-size: 10px;
  color: var(--color-fg-subtle, #888888);
  width: 56px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  z-index: 2;
}

.chain-line {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}

.event-node {
  position: absolute;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  cursor: pointer;
  z-index: 3;
  border: 2px solid #fff;
  transition: transform 0.15s;
}

.event-node:hover {
  transform: scale(1.5);
  z-index: 4;
}

.event-node.active {
  transform: scale(1.5);
  border-color: var(--color-accent-fg, #2563eb);
  z-index: 4;
}

.time-axis {
  position: absolute;
  bottom: 0;
  height: 20px;
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
}

.time-tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-size: 9px;
  color: var(--color-fg-subtle, #888888);
  white-space: nowrap;
  font-weight: 400;
}

.density-row {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 24px;
  z-index: 1;
}

.density-label {
  position: absolute;
  top: 4px;
  left: 4px;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  background: rgba(255, 255, 255, 0.85);
  padding: 2px 6px;
  border-radius: var(--r-btn, 6px);
  z-index: 2;
}

.density-chart {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 64px;
  display: flex;
  align-items: flex-end;
}

.density-bar {
  position: absolute;
  border-radius: 2px 2px 0 0;
  cursor: pointer;
  transition: opacity 0.15s;
  min-height: 1px;
}

.density-bar:hover {
  opacity: 0.7;
}

.timeline-minimap {
  height: 20px;
  background: var(--color-canvas-inset, #f5f5f5);
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
  padding: 2px 0;
}

.minimap-track {
  position: relative;
  height: 100%;
  margin: 0 10px;
}

.minimap-dot {
  position: absolute;
  top: 50%;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  transform: translate(-50%, -50%);
}

.minimap-viewport {
  position: absolute;
  top: 0;
  height: 100%;
  border: 0.5px solid var(--color-accent-fg, #2563eb);
  background: rgba(37, 99, 235, 0.1);
  cursor: grab;
}

/* 状态栏 */
.status-bar {
  flex-shrink: 0;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  background: var(--color-canvas-inset, #f5f5f5);
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
}
</style>
