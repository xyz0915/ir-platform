<template>
  <div ref="chartRef" class="timeline-chart"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'
import * as echarts from 'echarts'
import { SEVERITY, EVENT_TYPE, SLA } from '@/constants/design-tokens.js'

/** Maximum number of data points rendered per series to prevent chart.setOption from blocking */
const MAX_RENDER_POINTS = 2000

const props = defineProps({
  events: { type: Array, default: () => [] },
  stats: { type: Object, default: null },
  adaptiveMode: { type: Boolean, default: false },
  showSlaLine: { type: Boolean, default: false },
})

const emit = defineEmits(['highlight-change'])

const chartRef = ref(null)
let chart = null

onMounted(() => {
  // Defer to nextTick so the DOM (container dimensions) is settled before ECharts init.
  // This prevents echarts.init() on a 0×0 container which can cause rendering issues.
  nextTick(() => {
    initChart()
  })
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})

// Shallow watch — the events array is always replaced (new reference),
// never mutated in-place. deep:true causes Vue to recursively traverse every
// property of every event during setup(), which blocks the main thread for
// large datasets (10k+ events). This was the PRIMARY cause of the browser freeze.
watch(() => props.events, () => {
  nextTick(() => {
    initChart()
  })
})

watch(() => props.showSlaLine, () => {
  nextTick(() => {
    initChart()
  })
})

function handleResize() {
  if (chart) chart.resize()
}

/**
 * 将时间戳标准化为 ISO 8601 格式字符串 (YYYY-MM-DDTHH:mm:ss).
 * 支持: ISO 8601 字符串、Unix 时间戳（秒/毫秒）、Python datetime 默认序列化格式.
 */
function normalizeTimestamp(ts) {
  if (ts == null) return ''
  // ── 数字类型：Unix 时间戳 ──
  if (typeof ts === 'number') {
    // 秒级时间戳（< 10000000000）转为毫秒
    const ms = ts < 10000000000 ? ts * 1000 : ts
    const d = new Date(ms)
    if (isNaN(d.getTime())) return ''
    return d.toISOString()
  }
  // ── 字符串类型 ──
  if (typeof ts !== 'string') return ''
  ts = ts.trim()
  if (!ts) return ''
  // 替换 / 为 -
  ts = ts.replace(/\//g, '-')
  // 将 "YYYY-MM-DD HH:mm:ss" 转换为 "YYYY-MM-DDTHH:mm:ss"
  ts = ts.replace(/^(\d{4}-\d{2}-\d{2})\s(\d{2}:\d{2}:\d{2})/, '$1T$2')
  const parsed = new Date(ts)
  if (isNaN(parsed.getTime())) return ''
  return ts
}

function formatTimeForDisplay(ts) {
  if (!ts) return '未知时间'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hours = String(d.getHours()).padStart(2, '0')
  const minutes = String(d.getMinutes()).padStart(2, '0')
  const seconds = String(d.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

/**
 * 自适应符号大小计算
 * 基于事件总数调整 symbolSize 缩放因子
 */
const adaptiveSymbolSize = computed(() => {
  return function (baseSize) {
    if (!props.adaptiveMode) return baseSize
    const len = props.events.length
    if (len < 50) return baseSize
    if (len <= 200) return Math.round(baseSize * 0.8)
    return Math.round(baseSize * 0.6)
  }
})

/**
 * 聚合事件：同 event_type 按 5 分钟窗口分组，超过阈值合并为聚合气泡
 */
function aggregateEvents(events, windowMinutes = 5, threshold = 5) {
  if (!events || events.length === 0) return { aggregated: [], original: events }

  const valid = events
    .map(e => ({ ...e, _ts: normalizeTimestamp(e.timestamp) }))
    .filter(e => e._ts !== '')

  const groups = {}
  for (const e of valid) {
    const dt = new Date(e._ts)
    const bucket = Math.floor(dt.getTime() / (windowMinutes * 60 * 1000))
    const typeKey = e.event_type || 'other'
    const groupKey = `${bucket}_${typeKey}`
    if (!groups[groupKey]) {
      groups[groupKey] = { type: typeKey, bucket, events: [] }
    }
    groups[groupKey].events.push(e)
  }

  const aggregated = []
  const originalEvents = []
  for (const key of Object.keys(groups)) {
    const group = groups[key]
    if (group.events.length > threshold) {
      const firstEvt = group.events[0]
      aggregated.push({
        name: `${group.events.length} 个${EVENT_TYPE.LABEL[group.type] || group.type}事件在此时间段密集发生`,
        value: [firstEvt._ts, group.type],
        severity: 'info',
        source: 'aggregated',
        isAggregate: true,
        aggregatedCount: group.events.length,
        aggregatedEvents: group.events,
        _raw_ts: firstEvt._ts,
      })
    } else {
      for (const e of group.events) {
        originalEvents.push(e)
      }
    }
  }

  return { aggregated, original: originalEvents }
}

function initChart() {
  if (!chartRef.value) return

  // Guard: skip init if container has zero dimensions (e.g. during v-if transition)
  const rect = chartRef.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) {
    return
  }

  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const events = props.events || []

  // DEBUG: 打印前 3 条事件的原始 timestamp 格式，用于诊断后端返回格式
  if (events.length > 0) {
    const sampleTypes = events.slice(0, 3).map(e => ({
      raw: e.timestamp,
      type: typeof e.timestamp,
      normalized: normalizeTimestamp(e.timestamp),
    }))
    console.log('[TimelineChart] DEBUG timestamp samples:', sampleTypes)
  }

  const validEvents = events
    .map(e => ({ ...e, _normalized_ts: normalizeTimestamp(e.timestamp) }))
    .filter(e => e._normalized_ts !== '')

  // Cap data points to prevent chart.setOption from blocking the main thread
  if (validEvents.length > MAX_RENDER_POINTS) {
    console.warn(`[TimelineChart] Truncating ${validEvents.length} events to ${MAX_RENDER_POINTS} for rendering performance`)
    validEvents.length = MAX_RENDER_POINTS
  }

  console.log('[TimelineChart] total events:', events.length, 'valid (timestamp parsed):', validEvents.length)

  if (validEvents.length === 0) {
    try {
      chart.setOption({
        title: { text: '暂无时间线数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } }
      }, true)
    } catch (e) {
      console.error('[TimelineChart] setOption (empty) failed:', e)
    }
    return
  }

  // V3-1: 自适应聚合（仅在 adaptiveMode 时启用）
  let eventsToRender = validEvents
  let aggregatedBubbles = []
  if (props.adaptiveMode) {
    const result = aggregateEvents(validEvents, 5, 5)
    eventsToRender = result.original
    aggregatedBubbles = result.aggregated
  }

  // ── V1-2: dataZoom 底部留空间 ──
  const grid = { left: '3%', right: '4%', bottom: 80, top: 60, containLabel: true }

  // ── V1-1: 按 severity 分组为多个 scatter series ──
  const severityGroups = { high: [], medium: [], low: [], info: [] }
  for (const e of eventsToRender) {
    const sev = e.severity || 'info'
    if (severityGroups[sev]) {
      severityGroups[sev].push(e)
    } else {
      severityGroups.info.push(e)
    }
  }

  // ── V1-6: IOC 命中事件提取 ──
  const iocEvents = eventsToRender.filter(e => e.ioc_hit_id != null)

  const baseSize = adaptiveSymbolSize

  const severitySeries = ['high', 'medium', 'low', 'info'].map(sev => {
    const items = severityGroups[sev]
    if (items.length === 0) return null
    const size = baseSize(SEVERITY.SYMBOL_SIZE[sev] || 6)
    const color = SEVERITY.COLOR[sev] || '#C0C4CC'
    const isHigh = sev === 'high'
    return {
      name: SEVERITY.LABEL[sev] || sev,
      type: 'scatter',
      data: items.map(e => ({
        name: e.description || '',
        value: [e._normalized_ts, EVENT_TYPE.LABEL[e.event_type] || e.event_type || '其他'],
        severity: e.severity,
        source: e.source,
        event_type: e.event_type,
        _raw_ts: e.timestamp,
        _event_id: e.id,
        ioc_hit_id: e.ioc_hit_id,
      })),
      symbolSize: size,
      itemStyle: {
        color: color,
        borderColor: isHigh ? '#C0392B' : 'transparent',
        borderWidth: isHigh ? 1 : 0,
      },
      emphasis: {
        itemStyle: isHigh ? {
          shadowBlur: 10,
          shadowColor: 'rgba(245,108,108,0.8)',
        } : {},
      },
    }
  }).filter(Boolean)

  // ── V1-6: IOC 命中 scatter series（钻石形状、红色、z-index 最高）──
  if (iocEvents.length > 0) {
    severitySeries.push({
      name: 'IOC 命中',
      type: 'scatter',
      data: iocEvents.map(e => ({
        name: e.description || '',
        value: [e._normalized_ts, EVENT_TYPE.LABEL[e.event_type] || e.event_type || '其他'],
        severity: e.severity,
        source: e.source,
        event_type: e.event_type,
        _raw_ts: e.timestamp,
        _event_id: e.id,
        ioc_hit_id: e.ioc_hit_id,
      })),
      symbol: 'diamond',
      symbolSize: 18,
      z: 10,
      itemStyle: { color: '#FF0000' },
    })
  }

  // ── V3-1: 聚合气泡 series ──
  if (aggregatedBubbles.length > 0) {
    severitySeries.push({
      name: '聚合事件',
      type: 'scatter',
      data: aggregatedBubbles.map(b => ({
        name: b.name,
        value: [b.value[0], EVENT_TYPE.LABEL[b.value[1]] || b.value[1]],
        severity: 'info',
        source: 'aggregated',
        isAggregate: true,
        aggregatedCount: b.aggregatedCount,
        _raw_ts: b._raw_ts,
      })),
      symbolSize: (val) => {
        return Math.min(val.aggregatedCount * 2, 40)
      },
      z: 5,
      itemStyle: {
        color: 'rgba(144,147,153,0.4)',
        borderColor: '#909399',
        borderWidth: 1,
        borderType: 'dashed',
      },
    })
  }

  // ── 图例数据 ──
  const legendData = [
    ...severitySeries.filter(s => s.name !== 'IOC 命中' && s.name !== '聚合事件').map(s => s.name),
  ]
  if (iocEvents.length > 0) legendData.push('IOC 命中')
  if (aggregatedBubbles.length > 0) legendData.push('聚合事件')

  // ── Y 轴类别 ──
  const typeCategories = Object.keys(EVENT_TYPE.LABEL).map(k => EVENT_TYPE.LABEL[k])
  const yAxisData = typeCategories

  // ── V3-6: SLA markLine（24h 前时间边界）──
  const markLineData = []
  if (props.showSlaLine) {
    const now = new Date()
    const slaBoundary = new Date(now.getTime() - SLA.TIMEOUT_HOURS * 60 * 60 * 1000)
    const slaStr = slaBoundary.toISOString()
    markLineData.push({
      xAxis: slaStr,
      lineStyle: { type: 'dashed', color: '#FF0000', width: 1 },
      label: { formatter: '24h SLA 边界', color: '#FF0000', fontSize: 10 },
    })
  }

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: function (params) {
        const d = params.data
        if (d.isAggregate) {
          return `<b>${d.name}</b>`
        }
        const displayTime = formatTimeForDisplay(d.value[0])
        const typeLabel = d.value[1] || ''
        let html = `<b>${d.name}</b><br/>时间: ${displayTime}<br/>类型: ${typeLabel}`
        if (d.source) html += `<br/>来源: ${d.source}`
        if (d.severity) html += `<br/>严重度: ${d.severity}`
        if (d.ioc_hit_id) html += `<br/>⚠ IOC 命中`
        return html
      },
    },
    legend: {
      data: legendData,
      top: 10,
      selectedMode: 'multiple',
    },
    grid: grid,
    xAxis: {
      type: 'time',
      axisLabel: {
        rotate: 30,
        formatter: function (value) {
          const d = new Date(value)
          if (isNaN(d.getTime())) return value
          const month = String(d.getMonth() + 1).padStart(2, '0')
          const day = String(d.getDate()).padStart(2, '0')
          const hours = String(d.getHours()).padStart(2, '0')
          const minutes = String(d.getMinutes()).padStart(2, '0')
          return `${month}-${day} ${hours}:${minutes}`
        },
      },
    },
    yAxis: {
      type: 'category',
      data: yAxisData,
      axisLabel: { interval: 0 },
    },
    dataZoom: [
      {
        type: 'slider',
        bottom: 10,
        height: 20,
      },
      {
        type: 'inside',
      },
    ],
    series: severitySeries.length > 0 ? severitySeries : [{
      type: 'scatter',
      data: [],
      symbolSize: 10,
    }],
  }

  // 添加 SLA markLine 到第一个有数据的 series
  if (markLineData.length > 0 && severitySeries.length > 0) {
    const markLineSeries = severitySeries[0]
    markLineSeries.markLine = {
      silent: true,
      symbol: 'none',
      data: markLineData,
    }
  }

  try {
    chart.setOption(option, true)
  } catch (e) {
    console.error('[TimelineChart] setOption failed:', e)
  }
}
</script>

<style scoped>
.timeline-chart {
  width: 100%;
  height: 400px;
}
</style>
