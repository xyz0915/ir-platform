<template>
  <div ref="chartRef" class="kill-chain-chart"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { KILL_CHAIN_SWIMLANE, EVENT_TYPE } from '@/constants/design-tokens.js'

/** Maximum number of data points rendered to prevent chart.setOption from blocking */
const MAX_RENDER_POINTS = 2000

const props = defineProps({
  events: { type: Array, default: () => [] },
})

const chartRef = ref(null)
let chart = null

onMounted(() => {
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
  const validEvents = props.events
    .filter(e => e.timestamp)
    .map(e => {
      const stageKey = e.kill_chain_stage || ''
      const swimKey = stageToSwimlane[stageKey] || 'reconnaissance'
      const sw = swimlaneMap[swimKey]
      return {
        ...e,
        _swimKey: swimKey,
        _swimLabel: sw ? sw.label : '未知',
        _color: sw ? sw.color : '#909399',
        _ts: new Date(e.timestamp),
      }
    })
    .filter(e => !isNaN(e._ts.getTime()))

  // Cap data points to prevent chart.setOption from blocking the main thread
  if (validEvents.length > MAX_RENDER_POINTS) {
    console.warn(`[KillChainView] Truncating ${validEvents.length} events to ${MAX_RENDER_POINTS} for rendering performance`)
    validEvents.length = MAX_RENDER_POINTS
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

  const yCategories = KILL_CHAIN_SWIMLANE.map(s => s.label)

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
      bottom: '3%',
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
          const pad = n => String(n).padStart(2, '0')
          return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
        },
      },
    },
    yAxis: {
      type: 'category',
      data: yCategories,
      axisLabel: { interval: 0, fontSize: 12 },
    },
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
  height: 350px;
}
</style>
