<template>
  <div ref="chartRef" class="kill-chain-chart" :style="{ height: chartHeight + 'px' }"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'
import * as echarts from 'echarts'
import { KILL_CHAIN_SWIMLANE, EVENT_TYPE } from '@/constants/design-tokens.js'

/** Maximum number of data points rendered to prevent chart.setOption from blocking */
const MAX_RENDER_POINTS = 2000

/** 最小有效时间（2000-01-01），早于该时间的时间戳视为脏数据 */
const MIN_VALID_MS = Date.UTC(2000, 0, 1)

/** 无 kill_chain_stage 或无法映射到泳道的事件，单独归入「未映射」泳道 */
const UNMAPPED_KEY = '__unmapped__'
const UNMAPPED_LABEL = '未映射'
const UNMAPPED_COLOR = '#C0C4CC'

/** 单泳道高度 / 图表非绘图区（轴标签 + dataZoom）预留高度 */
const LANE_H = 34
const CHROME_H = 70

const props = defineProps({
  events: { type: Array, default: () => [] },
})

const chartRef = ref(null)
let chart = null
let ro = null

/** 实际渲染的泳道数量，用于图表高度自适应 */
const laneCount = ref(KILL_CHAIN_SWIMLANE.length)

const chartHeight = computed(() => {
  return Math.min(420, Math.max(160, laneCount.value * LANE_H + CHROME_H))
})

onMounted(() => {
  nextTick(() => {
    initChart()
  })
  window.addEventListener('resize', handleResize)

  // 容器尺寸变化（tab 切换、折叠展开、高度自适应）时重新初始化/重绘
  if (chartRef.value && typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => {
      if (!chartRef.value) return
      const { width, height } = chartRef.value.getBoundingClientRect()
      if (width === 0 || height === 0) return
      if (!chart) initChart()
      else chart.resize()
    })
    ro.observe(chartRef.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (ro) {
    ro.disconnect()
    ro = null
  }
  if (chart) {
    chart.dispose()
    chart = null
  }
})

// Shallow watch — events array is always replaced, never mutated in-place.
// deep:true causes Vue to recursively traverse every property during setup(),
// blocking the main thread for large datasets — the primary cause of browser freeze.
watch(() => props.events, () => {
  nextTick(() => {
    initChart()
  })
})

function handleResize() {
  if (chart) chart.resize()
}

function initChart() {
  if (!chartRef.value) return

  // Guard: skip init if container has zero dimensions
  const rect = chartRef.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) {
    return
  }

  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const swimlaneMap = {}
  KILL_CHAIN_SWIMLANE.forEach((s, idx) => {
    swimlaneMap[s.key] = { ...s, index: idx }
  })

  // 将 kill_chain_stage 映射到泳道 key
  const stageToSwimlane = {
    'reconnaissance': 'reconnaissance',
    'resource_development': 'weaponization',
    'initial_access': 'delivery',
    'execution': 'exploitation',
    'persistence': 'installation',
    'privilege_escalation': 'exploitation',
    'defense_evasion': 'installation',
    'credential_access': 'exploitation',
    'discovery': 'reconnaissance',
    'lateral_movement': 'exploitation',
    'collection': 'actions',
    'command_and_control': 'c2',
    'exfiltration': 'actions',
    'impact': 'actions',
  }

  // 准备数据
  // 无 kill_chain_stage 的事件不再兜底到「侦查」泳道，避免虚假的攻击链归因
  const validEvents = props.events
    .filter(e => e.timestamp)
    .map(e => {
      const stageKey = e.kill_chain_stage || ''
      const swimKey = stageToSwimlane[stageKey] || UNMAPPED_KEY
      const sw = swimlaneMap[swimKey]
      return {
        ...e,
        _swimKey: swimKey,
        _swimLabel: sw ? sw.label : UNMAPPED_LABEL,
        _color: sw ? sw.color : UNMAPPED_COLOR,
        _ts: new Date(e.timestamp),
      }
    })
    .filter(e => !isNaN(e._ts.getTime()) && e._ts.getTime() >= MIN_VALID_MS)

  // Cap data points to prevent chart.setOption from blocking the main thread.
  // 事件已按时间升序排列，截断时保留尾部（最新事件）而非头部。
  if (validEvents.length > MAX_RENDER_POINTS) {
    console.warn(`[KillChainView] Truncating ${validEvents.length} → ${MAX_RENDER_POINTS} (保留最新)`)
    validEvents.splice(0, validEvents.length - MAX_RENDER_POINTS)
  }

  if (validEvents.length === 0) {
    try {
      chart.setOption({
        title: { text: '暂无 Kill Chain 数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
      }, true)
    } catch (e) {
      console.error('[KillChainView] setOption (empty) failed:', e)
    }
    return
  }

  // ── Y 轴泳道：只保留本次数据中实际出现的阶段，「未映射」置于最上方 ──
  const presentKeys = new Set(validEvents.map(e => e._swimKey))
  const yCategories = [
    ...KILL_CHAIN_SWIMLANE.filter(s => presentKeys.has(s.key)).map(s => s.label),
    ...(presentKeys.has(UNMAPPED_KEY) ? [UNMAPPED_LABEL] : []),
  ]
  laneCount.value = yCategories.length

  /**
   * 计算默认聚焦视窗：少量极早/极晚离群点会把绝大多数事件压成一条竖线，
   * 用 1% 分位数作为左边界，让默认视图聚焦在数据密集区。
   * 若离群点不明显（聚焦区已覆盖 60% 以上跨度）则不做裁剪。
   */
  function computeFocusWindow(items) {
    const tsList = items
      .map(e => e._ts.getTime())
      .filter(t => !isNaN(t))
      .sort((a, b) => a - b)
    const n = tsList.length
    if (n < 10) return null
    const lo = tsList[Math.floor(n * 0.01)]
    const hi = tsList[n - 1]
    const full = tsList[n - 1] - tsList[0]
    if (full <= 0) return null
    if ((hi - lo) / full > 0.6) return null
    const pad = Math.max((hi - lo) * 0.05, 60 * 1000)
    return { startValue: lo - pad, endValue: hi + pad }
  }
  const focus = computeFocusWindow(validEvents)
  const tsListForSpan = validEvents
    .map(e => e._ts.getTime())
    .filter(t => !isNaN(t))
    .sort((a, b) => a - b)
  const fullSpanMs = tsListForSpan.length >= 2
    ? tsListForSpan[tsListForSpan.length - 1] - tsListForSpan[0]
    : 0
  const showZoom = validEvents.length > 50
  const dataZoomCommon = focus
    ? { startValue: focus.startValue, endValue: focus.endValue }
    : { start: 0, end: 100 }

  const seriesData = validEvents.map(e => ({
    name: e.description || '',
    value: [e._ts, e._swimLabel],
    itemStyle: { color: e._color },
    severity: e.severity,
    event_type: e.event_type,
    _raw_ts: e.timestamp,
  }))

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: function (params) {
        const d = params.data
        return `<b>${d.name}</b><br/>时间: ${d._raw_ts}<br/>严重度: ${d.severity || '-'}`
      },
    },
    grid: {
      left: '10%',
      right: '4%',
      bottom: showZoom ? 34 : '3%',
      top: '3%',
      containLabel: true,
    },
    xAxis: {
      type: 'time',
      axisLabel: {
        rotate: 30,
        formatter: function (value) {
          const d = new Date(value)
          if (isNaN(d.getTime())) return value
          const p = n => String(n).padStart(2, '0')
          const spanMs = focus ? focus.endValue - focus.startValue : fullSpanMs
          if (spanMs > 365 * 864e5) return `${d.getFullYear()}-${p(d.getMonth() + 1)}`
          if (spanMs > 3 * 864e5) return `${p(d.getMonth() + 1)}-${p(d.getDate())}`
          return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
        },
      },
    },
    yAxis: {
      type: 'category',
      data: yCategories,
      axisLabel: { interval: 0, fontSize: 12 },
    },
    // slider 仅在事件数 > 50 时显示，inside 始终启用以支持滚轮缩放
    dataZoom: [
      {
        type: 'slider',
        bottom: 6,
        height: 16,
        show: showZoom,
        ...dataZoomCommon,
        textStyle: { color: '#5F5E5A', fontSize: 10 },
        borderColor: 'transparent',
        backgroundColor: 'rgba(0,0,0,0.02)',
        fillerColor: 'rgba(99,153,34,0.08)',
        handleStyle: { color: '#639922', borderColor: '#639922' },
      },
      { type: 'inside', ...dataZoomCommon },
    ],
    series: [{
      type: 'scatter',
      data: seriesData,
      symbolSize: 12,
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' },
      },
    }],
  }

  try {
    chart.setOption(option, true)
  } catch (e) {
    console.error('[KillChainView] setOption failed:', e)
  }
}
</script>

<style scoped>
.kill-chain-chart {
  width: 100%;
}
</style>
