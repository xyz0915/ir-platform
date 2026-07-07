<template>
  <div ref="chartRef" class="timeline-chart"></div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  events: { type: Array, default: () => [] }
})

const chartRef = ref(null)
let chart = null

onMounted(() => {
  initChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chart) chart.dispose()
})

watch(() => props.events, () => {
  initChart()
}, { deep: true })

function handleResize() {
  if (chart) chart.resize()
}

/**
 * 将时间戳字符串标准化为 ISO 8601 格式 (YYYY-MM-DDTHH:mm:ss).
 * 处理以下格式:
 *   - 2026-07-03T19:25:46.550278 → 2026-07-03T19:25:46
 *   - 2026-07-06 08:04:50 → 2026-07-06T08:04:50
 *   - 2026/07/06 08:04:50 → 2026-07-06T08:04:50
 *
 * @param {string} ts - 原始时间戳
 * @returns {string} 标准化后的 ISO 时间戳,或空字符串表示无效
 */
function normalizeTimestamp(ts) {
  if (!ts || typeof ts !== 'string') return ''
  ts = ts.trim()
  if (!ts) return ''

  // 替换斜杠分隔符为短横线
  ts = ts.replace(/\//g, '-')

  // 替换空格分隔符为 T (如果中间没有 T)
  // 匹配格式: YYYY-MM-DD HH:mm:ss 或 YYYY-MM-DD HH:mm:ss.ffffff
  ts = ts.replace(/^(\d{4}-\d{2}-\d{2})\s(\d{2}:\d{2}:\d{2})/, '$1T$2')

  // 验证是否可被 Date 解析
  const parsed = new Date(ts)
  if (isNaN(parsed.getTime())) {
    return ''
  }

  return ts
}

/**
 * 格式化时间戳为友好的显示格式.
 * @param {string} ts - ISO 8601 时间戳
 * @returns {string} 格式化的时间字符串
 */
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

function initChart() {
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const typeColors = {
    process: '#409EFF',
    network: '#67C23A',
    file: '#E6A23C',
    log: '#909399',
    persistence: '#F56C6C',
    system: '#9B59B6',
    other: '#95A5A6'
  }

  const typeNames = {
    process: '进程',
    network: '网络',
    file: '文件',
    log: '日志',
    persistence: '持久化',
    system: '系统',
    other: '其他'
  }

  // 预处理: 标准化时间戳并过滤无效事件
  const validEvents = props.events
    .map(e => ({
      ...e,
      _normalized_ts: normalizeTimestamp(e.timestamp)
    }))
    .filter(e => e._normalized_ts !== '')

  const data = validEvents.map(e => ({
    name: e.description || '',
    value: [e._normalized_ts, e.event_type || 'other'],
    itemStyle: { color: typeColors[e.event_type] || typeColors.other },
    severity: e.severity,
    source: e.source,
    _raw_ts: e.timestamp
  }))

  const types = Object.keys(typeNames)

  const option = {
    tooltip: {
      formatter: function (params) {
        const d = params.data
        const displayTime = formatTimeForDisplay(d.value[0])
        return `<b>${d.name}</b><br/>时间: ${displayTime}<br/>类型: ${typeNames[d.value[1]] || d.value[1]}<br/>来源: ${d.source || ''}<br/>严重度: ${d.severity || ''}`
      }
    },
    legend: {
      data: types.map(t => typeNames[t]),
      top: 10
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
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
        }
      }
    },
    yAxis: {
      type: 'category',
      data: types.map(t => typeNames[t]),
      axisLabel: { interval: 0 }
    },
    series: [{
      type: 'scatter',
      data: data.map(d => ({
        ...d,
        value: [d.value[0], typeNames[d.value[1]] || d.value[1]]
      })),
      symbolSize: 10,
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' }
      }
    }]
  }

  chart.setOption(option, true)
}
</script>

<style scoped>
.timeline-chart {
  width: 100%;
  height: 400px;
}
</style>
