<template>
  <div class="monitor-page">
    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="stat-card" v-for="s in statCards" :key="s.label">
        <div class="s-label">{{ s.label }}</div>
        <div class="s-value" :class="s.color">{{ s.value }}</div>
        <div class="s-sub">{{ s.sub }}</div>
        <span class="s-rate" :class="s.rateDir">{{ s.rate }}</span>
      </div>
    </div>

    <!-- 图表行 -->
    <div class="charts-row">
      <div class="chart-card">
        <div class="c-title">实时事件速率</div>
        <div class="c-sub">最近 30 分钟 · 条/分钟</div>
        <div ref="rateChartRef" class="chart-box" />
      </div>
      <div class="chart-card">
        <div class="c-title">告警严重度分布</div>
        <div class="c-sub">按严重度占比</div>
        <div ref="severityChartRef" class="chart-box" />
      </div>
    </div>

    <!-- 底部 -->
    <div class="bottom-row">
      <div class="panel">
        <div class="p-title">
          <span>🔔 最近告警</span>
          <router-link to="/alerts" class="p-link">查看全部 →</router-link>
        </div>
        <div v-if="recentAlerts.length === 0" class="empty">暂无告警</div>
        <div v-for="(a, i) in recentAlerts" :key="i" class="alert-item" @click="$router.push('/alerts')">
          <span :class="['alert-dot', `ad-${a.severity}`]" />
          <div class="alert-body">
            <div class="alert-title">{{ a.title }}</div>
            <div class="alert-meta">{{ a.hostname }}</div>
          </div>
          <span class="alert-time">{{ formatTime(a.last_seen_at || a.first_seen_at) }}</span>
        </div>
      </div>
      <div class="panel">
        <div class="p-title">
          <span>🖥 主机在线状态</span>
          <span class="p-link" @click="$router.push('/cases')">主机列表 →</span>
        </div>
        <div v-if="hosts.length === 0" class="empty">暂无主机</div>
        <div v-for="(h, i) in hosts" :key="i" class="host-item" @click="$router.push(`/hosts/${h.id}`)">
          <span :class="['h-dot', h.status === 'online' ? 'h-online' : 'h-offline']" />
          <span class="h-name">{{ h.hostname }}</span>
          <span class="h-status">{{ h.status === 'online' ? '在线' : '离线' }}</span>
          <span class="h-agent">v{{ h.agent_version || '-' }}</span>
          <span class="h-time">{{ h.last_heartbeat ? formatTime(h.last_heartbeat) : '未连接' }}</span>
        </div>
      </div>
    </div>

    <!-- 状态栏 -->
    <div class="status-bar">
      <span class="sb-item"><span class="sb-dot sb-green"></span> 事件通道</span>
      <span class="sb-item"><span class="sb-dot sb-green"></span> WebSocket</span>
      <span class="sb-item" style="margin-left:auto;">最后事件: <span id="lastEventTime" style="color:#9ca3af;">-</span></span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { getAlerts, getAlertStats } from '@/api/alerts'
import { getHostsStatus } from '@/api/alerts'

const rateChartRef = ref(null)
const severityChartRef = ref(null)
let rateChart = null
let severityChart = null

const statCards = ref([
  { label: '待处理告警', value: '-', color: 'critical', sub: '严重 0 条', rate: '-', rateDir: '' },
  { label: '今日新增', value: '-', color: 'high', sub: '近 1h 0 条', rate: '-', rateDir: '' },
  { label: '在线主机', value: '-', color: 'medium', sub: '总计 0 台', rate: '-', rateDir: '' },
  { label: '规则命中', value: '-', color: 'green', sub: '活跃规则 0 条', rate: '-', rateDir: '' },
])

const recentAlerts = ref([])
const hosts = ref([])

function formatTime(iso) {
  if (!iso) return ''
  const utc = iso.includes('T') ? iso : iso.replace(' ', 'T')
  const d = new Date(utc.endsWith('Z') ? utc : utc + 'Z')
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前'
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function fetchStats() {
  try {
    const s = await getAlertStats()
    const d = s.data || {}
    statCards.value[0] = { ...statCards.value[0], value: d.open || 0, sub: `严重 ${d.critical || 0} 条`, rate: d.total ? `共 ${d.total}` : '0' }
    statCards.value[1] = { ...statCards.value[1], value: d.today || 0, sub: `待处置 ${d.open || 0} 条`, rate: `+${d.today || 0}` }
  } catch (e) { console.error(e) }
}

async function fetchAlerts() {
  try {
    const res = await getAlerts({ status: 'open', limit: 5 })
    recentAlerts.value = (res.data || []).slice(0, 5)
  } catch (e) { console.error(e) }
}

async function fetchHosts() {
  try {
    const res = await getHostsStatus()
    const h = res.data || []
    hosts.value = h
    const online = h.filter(x => x.status === 'online').length
    statCards.value[2] = { ...statCards.value[2], value: online, sub: `总计 ${h.length} 台`, rate: `${online}/${h.length}` }
  } catch (e) { console.error(e) }
}

let ws = null
function connectWebSocket() {
  const token = localStorage.getItem('ir_token')
  if (!token) return
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${proto}//${location.host}/api/ws/alerts?token=${token}`)
  ws.onmessage = (event) => {
    try {
      const d = JSON.parse(event.data)
      if (d.type === 'new_alert') {
        const a = d.alert
        recentAlerts.value.unshift(a)
        if (recentAlerts.value.length > 5) recentAlerts.value.pop()
        document.getElementById('lastEventTime').textContent = formatTime(a.last_seen_at || a.first_seen_at)
      }
    } catch (e) { /* ignore */ }
  }
  ws.onclose = () => setTimeout(connectWebSocket, 5000)
}

// ECharts init is deferred, handled in onMounted
let rateTimer = null

onMounted(async () => {
  await Promise.all([fetchStats(), fetchAlerts(), fetchHosts()])
  connectWebSocket()

  // ECharts rate chart
  if (rateChartRef.value) {
    rateChart = echarts.init(rateChartRef.value)
    const labels = [], data = []
    for (let i = 29; i >= 0; i--) {
      const t = new Date(Date.now() - i * 60000)
      labels.push(t.getHours() + ':' + String(t.getMinutes()).padStart(2, '0'))
      data.push(Math.floor(Math.random() * 20) + 2)
    }
    rateChart.setOption({
      tooltip: { trigger: 'axis', backgroundColor: '#1a1d27', borderColor: '#2a2d37', textStyle: { color: '#e5e7eb', fontSize: 11 } },
      grid: { left: 40, right: 10, top: 10, bottom: 20 },
      xAxis: { type: 'category', data: labels, axisLine: { lineStyle: { color: '#2a2d37' } }, axisLabel: { color: '#6b7280', fontSize: 10 } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#2a2d37', type: 'dashed' } }, axisLabel: { color: '#6b7280', fontSize: 10 } },
      series: [{
        type: 'line', smooth: true, symbol: 'none', lineStyle: { color: '#60a5fa', width: 2 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(96,165,250,0.2)' }, { offset: 1, color: 'rgba(96,165,250,0)' }] } },
        data,
      }]
    })
    rateTimer = setInterval(() => {
      if (rateChart) {
        const shift = Math.floor(Math.random() * 20) + 2
        rateChart.setOption({ series: [{ data: (data.slice(1), data.push(shift), data) }] })
        if (data.length > 30) data.shift()
      }
    }, 60000)
  }

  if (severityChartRef.value) {
    severityChart = echarts.init(severityChartRef.value)
    severityChart.setOption({
      tooltip: { trigger: 'item', backgroundColor: '#1a1d27', borderColor: '#2a2d37', textStyle: { color: '#e5e7eb', fontSize: 11 } },
      series: [{
        type: 'pie', radius: ['50%', '70%'], avoidLabelOverlap: true,
        itemStyle: { borderRadius: 4, borderColor: '#13151d', borderWidth: 2 },
        label: { show: true, formatter: '{b}\n{d}%', fontSize: 10, color: '#9ca3af', lineHeight: 14 },
        data: [
          { value: 23, name: '严重', itemStyle: { color: '#ef4444' } },
          { value: 67, name: '高危', itemStyle: { color: '#f59e0b' } },
          { value: 156, name: '中危', itemStyle: { color: '#3b82f6' } },
          { value: 432, name: '低危', itemStyle: { color: '#6b7280' } },
        ]
      }]
    })
  }
})

onUnmounted(() => {
  if (rateTimer) clearInterval(rateTimer)
  rateChart?.dispose()
  severityChart?.dispose()
  ws?.close()
})
</script>

<style scoped>
.monitor-page { padding: 16px 20px; background: #0f1117; min-height: calc(100vh - 100px); color: #e5e7eb; }

.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.stat-card {
  background: #1a1d27; border: 1px solid #2a2d37; border-radius: 8px;
  padding: 14px 16px; position: relative;
}
.s-label { font-size: 11px; color: #6b7280; margin-bottom: 2px; }
.s-value { font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }
.s-value.critical { color: #fca5a5; }
.s-value.high { color: #fcd34d; }
.s-value.medium { color: #93c5fd; }
.s-value.green { color: #86efac; }
.s-sub { font-size: 11px; color: #6b7280; margin-top: 4px; }
.s-rate {
  position: absolute; right: 14px; top: 14px; font-size: 11px;
  padding: 2px 8px; border-radius: 10px;
}

.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.chart-card {
  background: #1a1d27; border: 1px solid #2a2d37; border-radius: 8px; padding: 14px 16px;
}
.c-title { font-size: 13px; font-weight: 600; margin-bottom: 2px; }
.c-sub { font-size: 11px; color: #6b7280; margin-bottom: 12px; }
.chart-box { width: 100%; height: 200px; }

.bottom-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.panel {
  background: #1a1d27; border: 1px solid #2a2d37; border-radius: 8px; padding: 14px 16px;
}
.p-title { font-size: 13px; font-weight: 600; margin-bottom: 10px; display: flex; justify-content: space-between; }
.p-link { font-size: 11px; color: #60a5fa; cursor: pointer; font-weight: 400; text-decoration: none; }
.empty { text-align: center; padding: 20px; color: #6b7280; font-size: 12px; }

.alert-item {
  display: flex; align-items: center; gap: 10px; padding: 8px 0;
  border-bottom: 1px solid #1a1d27; font-size: 12px; cursor: pointer;
}
.alert-item:last-child { border-bottom: none; }
.alert-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.ad-critical { background: #ef4444; }
.ad-high { background: #f59e0b; }
.ad-medium { background: #3b82f6; }
.alert-body { flex: 1; min-width: 0; }
.alert-title { color: #e5e7eb; }
.alert-meta { font-size: 10px; color: #6b7280; margin-top: 1px; }
.alert-time { font-size: 10px; color: #6b7280; white-space: nowrap; }

.host-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 0;
  border-bottom: 1px solid #1a1d27; font-size: 12px; cursor: pointer;
}
.host-item:last-child { border-bottom: none; }
.h-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.h-online { background: #2da44e; box-shadow: 0 0 4px rgba(45,164,78,0.4); }
.h-offline { background: #6b7280; }
.h-name { color: #e5e7eb; width: 100px; }
.h-status { font-size: 10px; color: #6b7280; }
.h-agent { font-size: 10px; color: #4b5563; margin-left: 8px; }
.h-time { margin-left: auto; font-size: 10px; color: #6b7280; }

.status-bar {
  margin-top: 16px; padding: 8px 16px; background: #1a1d27; border: 1px solid #2a2d37;
  border-radius: 8px; display: flex; align-items: center; font-size: 11px; color: #6b7280; gap: 20px;
}
.sb-item { display: flex; align-items: center; gap: 4px; }
.sb-dot { width: 6px; height: 6px; border-radius: 50%; }
.sb-green { background: #2da44e; }
</style>
