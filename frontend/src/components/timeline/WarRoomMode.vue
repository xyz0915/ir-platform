<template>
  <Teleport to="body">
    <transition name="war-room">
      <div v-if="active" class="war-room-overlay">
        <!-- 顶部统计滚动条 -->
        <div class="war-room-header">
          <div class="war-room-title">🔴 作战视图 — {{ hostId ? `主机 ${hostId}` : '' }}</div>
          <div class="war-room-stats">
            <div class="stat-item critical">
              <span class="stat-number">{{ stats.highCount }}</span>
              <span class="stat-label">高危</span>
            </div>
            <div class="stat-item warning">
              <span class="stat-number">{{ stats.unresolved }}</span>
              <span class="stat-label">未处置</span>
            </div>
            <div class="stat-item danger">
              <span class="stat-number">{{ stats.iocHitCount }}</span>
              <span class="stat-label">IOC命中</span>
            </div>
            <div class="stat-item info">
              <span class="stat-number">{{ events.length }}</span>
              <span class="stat-label">总事件</span>
            </div>
          </div>
          <el-button class="close-btn" circle @click="$emit('close')">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>

        <!-- 全宽图表 -->
        <div class="war-room-body">
          <div ref="chartRef" class="war-room-chart"></div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { Close } from '@element-plus/icons-vue'
import { SEVERITY, EVENT_TYPE } from '@/constants/design-tokens.js'

const props = defineProps({
  events: { type: Array, default: () => [] },
  hostId: { type: Number, default: 0 },
  active: { type: Boolean, default: false },
})

defineEmits(['close'])

const chartRef = ref(null)
let chart = null

const stats = computed(() => {
  const evts = props.events || []
  return {
    highCount: evts.filter(e => e.severity === 'high').length,
    unresolved: evts.filter(e => !e.status || e.status === 'new' || e.status === 'triaging').length,
    iocHitCount: evts.filter(e => e.ioc_hit_id != null).length,
  }
})

function normalizeTimestamp(ts) {
  if (!ts || typeof ts !== 'string') return ''
  ts = ts.trim()
  if (!ts) return ''
  ts = ts.replace(/\//g, '-')
  ts = ts.replace(/^(\d{4}-\d{2}-\d{2})\s(\d{2}:\d{2}:\d{2})/, '$1T$2')
  const parsed = new Date(ts)
  if (isNaN(parsed.getTime())) return ''
  return ts
}

function initChart() {
  if (!chartRef.value || !props.active) return
  nextTick(() => {
    if (!chartRef.value) return
    if (chart) chart.dispose()
    chart = echarts.init(chartRef.value, 'dark')

    const valid = props.events
      .map(e => ({ ...e, _ts: normalizeTimestamp(e.timestamp) }))
      .filter(e => e._ts !== '')

    const sevGroups = { high: [], medium: [], low: [], info: [] }
    for (const e of valid) {
      const sev = e.severity || 'info'
      if (sevGroups[sev]) sevGroups[sev].push(e)
      else sevGroups.info.push(e)
    }

    const severitySeries = ['high', 'medium', 'low', 'info'].map(sev => {
      const items = sevGroups[sev]
      if (items.length === 0) return null
      return {
        name: SEVERITY.LABEL[sev],
        type: 'scatter',
        data: items.map(e => ({
          name: e.description || '',
          value: [e._ts, EVENT_TYPE.LABEL[e.event_type] || e.event_type || '其他'],
        })),
        symbolSize: SEVERITY.SYMBOL_SIZE[sev] || 6,
        itemStyle: { color: SEVERITY.COLOR[sev] },
      }
    }).filter(Boolean)

    chart.setOption({
      backgroundColor: '#1a1a2e',
      tooltip: { trigger: 'item' },
      legend: {
        data: ['高危', '中危', '低危', '信息'],
        top: 10,
        textStyle: { color: '#e0e0e0' },
      },
      grid: { left: '5%', right: '4%', bottom: 80, top: 50, containLabel: true },
      xAxis: {
        type: 'time',
        axisLabel: { color: '#e0e0e0' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      yAxis: {
        type: 'category',
        data: Object.values(EVENT_TYPE.LABEL),
        axisLabel: { color: '#e0e0e0', interval: 0 },
      },
      dataZoom: [
        { type: 'slider', bottom: 10, height: 20, textStyle: { color: '#e0e0e0' } },
        { type: 'inside' },
      ],
      series: severitySeries,
    }, true)
  })
}

watch(() => props.active, (val) => {
  if (val) {
    nextTick(() => initChart())
  }
})

watch(() => props.events, () => {
  if (props.active) initChart()
})

onUnmounted(() => {
  if (chart) chart.dispose()
})
</script>

<style scoped>
.war-room-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  background: #1a1a2e;
  display: flex;
  flex-direction: column;
}
.war-room-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: #16213e;
  border-bottom: 2px solid #0f3460;
}
.war-room-title {
  font-size: 20px;
  font-weight: 700;
  color: #e0e0e0;
}
.war-room-stats {
  display: flex;
  gap: 32px;
}
.stat-item {
  text-align: center;
  padding: 4px 16px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
}
.stat-item.critical .stat-number { color: #F56C6C; }
.stat-item.warning .stat-number { color: #E6A23C; }
.stat-item.danger .stat-number { color: #FF0000; }
.stat-item.info .stat-number { color: #409EFF; }
.stat-number {
  font-size: 28px;
  font-weight: 800;
  line-height: 1.2;
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
.stat-label {
  font-size: 11px;
  color: #808080;
  display: block;
}
.close-btn {
  background: transparent;
  border-color: #808080;
  color: #e0e0e0;
}
.war-room-body {
  flex: 1;
  padding: 16px;
}
.war-room-chart {
  width: 100%;
  height: 100%;
}

.war-room-enter-active,
.war-room-leave-active {
  transition: opacity 0.3s ease;
}
.war-room-enter-from,
.war-room-leave-to {
  opacity: 0;
}
</style>
