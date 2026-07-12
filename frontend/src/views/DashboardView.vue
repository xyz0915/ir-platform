<template>
  <div class="dashboard-page">
    <div v-if="loading" class="loading-overlay">
      <el-skeleton :rows="10" animated />
    </div>

    <div v-else-if="error" class="error-box">
      <el-result icon="error" title="加载失败" :sub-title="error">
        <template #extra>
          <el-button type="primary" @click="fetchData">重试</el-button>
        </template>
      </el-result>
    </div>

    <template v-else>
      <!-- 时间选择器 -->
      <div class="time-range">
        <span
          v-for="r in timeRanges" :key="r.key"
          :class="['pill', { active: activeRange === r.key }]"
          @click="activeRange = r.key"
        >{{ r.label }}</span>
      </div>

      <!-- KPI 卡片行 -->
      <div class="kpi-row">
        <div class="kpi-card critical" @click="$router.push('/iocs')">
          <div class="kpi-label">待处理告警</div>
          <div class="kpi-value">{{ stats.pending_alerts }}</div>
          <div class="kpi-sub">
            需立即处置 <strong>{{ stats.critical_alerts }}</strong> 条
            <span v-if="stats.alert_trend_dir === 'up'" class="trend-up">↑ {{ Math.abs(stats.alert_trend || 0) }}</span>
            <span v-else-if="stats.alert_trend_dir === 'down'" class="trend-down">↓ {{ Math.abs(stats.alert_trend || 0) }}</span>
          </div>
          <div class="kpi-icon" style="background:#ffebe9;">⚡</div>
        </div>
        <div class="kpi-card high">
          <div class="kpi-label">活跃案件</div>
          <div class="kpi-value">{{ stats.active_cases }}</div>
          <div class="kpi-sub">
            今日新增 <strong>{{ stats.new_cases_today }}</strong> 件
            <span v-if="stats.cases_trend > 0" class="trend-up">↑ {{ stats.cases_trend }}</span>
          </div>
          <div class="kpi-icon" style="background:#fff8c5;">📋</div>
        </div>
        <div class="kpi-card medium">
          <div class="kpi-label">已采集主机</div>
          <div class="kpi-value">{{ stats.total_hosts }}</div>
          <div class="kpi-sub">
            待分析 <strong>{{ stats.pending_hosts }}</strong> 台 · 最近 24h <strong>{{ stats.recent_hosts_24h || 0 }}</strong>
          </div>
          <div class="kpi-icon" style="background:#ddf4ff;">🖥</div>
        </div>
        <div class="kpi-card purple">
          <div class="kpi-label">规则命中</div>
          <div class="kpi-value kpi-purple">{{ formatNum(stats.total_rule_hits) }}</div>
          <div class="kpi-sub">活跃规则 <strong>{{ stats.active_rules }}</strong> 条</div>
          <div class="kpi-icon" style="background:#f3eefc;">📊</div>
        </div>
        <div class="kpi-card green">
          <div class="kpi-label">知识库命中</div>
          <div class="kpi-value kpi-green">{{ stats.kb_hits }}</div>
          <div class="kpi-sub">
            覆盖率 <strong>{{ stats.kb_coverage }}%</strong>
            <span v-if="stats.kb_coverage > 0 && stats.kb_coverage < 30" style="color:#d4a72c;">（偏低）</span>
            <span v-else-if="stats.kb_coverage >= 50" style="color:#2da44e;">（良好）</span>
          </div>
          <div class="kpi-icon" style="background:#e6f6e8;">📚</div>
        </div>
        <div class="kpi-card teal">
          <div class="kpi-label">AI 分析</div>
          <div class="kpi-value kpi-teal">{{ stats.ai_analyses_recent || 0 }}</div>
          <div class="kpi-sub">
            可用率 <strong :style="{ color: aiAvailColor }">{{ stats.ai_availability || 0 }}%</strong>
            <span v-if="stats.ai_trend > 0" class="trend-up">↑ {{ stats.ai_trend }}</span>
            <span v-else-if="stats.ai_trend < 0" class="trend-down">↓ {{ Math.abs(stats.ai_trend) }}</span>
          </div>
          <div class="kpi-icon" style="background:#e6fffa;">🤖</div>
        </div>
      </div>

      <!-- 图表行 -->
      <div class="charts-row">
        <div class="chart-card">
          <div class="chart-header">
            <div>
              <div class="chart-title">案件与规则命中趋势</div>
              <div class="chart-subtitle">最近 {{ trendDays }} 天 · 含告警量与规则命中数</div>
            </div>
          </div>
          <div ref="trendChartRef" class="chart-box" />
        </div>
        <div class="chart-card">
          <div class="chart-header">
            <div>
              <div class="chart-title">告警类别分布</div>
              <div class="chart-subtitle">按规则聚合 top 8</div>
            </div>
          </div>
          <div ref="categoryChartRef" class="chart-box" />
        </div>
      </div>

      <!-- 底部三列 -->
      <div class="bottom-row">
        <!-- 左：待处理告警 -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">🔔 待处理告警</span>
            <router-link to="/cases" class="panel-link">查看全部 →</router-link>
          </div>
          <div v-if="recentAlerts.length === 0" class="empty-state">暂无待处理告警</div>
          <div v-for="(alert, i) in recentAlerts" :key="i" class="alert-item">
            <span :class="['alert-severity-dot', `dot-${alert.severity}`]" />
            <div class="alert-body">
              <div class="alert-title">{{ alert.title }}</div>
              <div class="alert-meta">{{ alert.host }} · PID {{ alert.pid }} · {{ alert.detail || 'N/A' }}</div>
            </div>
            <span :class="['alert-badge', `badge-${alert.severity}`]">{{ alert.severity.toUpperCase() }}</span>
          </div>
        </div>

        <!-- 中：最近主机 -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">🖥 最近主机</span>
            <router-link to="/cases" class="panel-link">主机列表 →</router-link>
          </div>
          <div v-if="recentHosts.length === 0" class="empty-state">暂未采集主机</div>
          <div class="host-grid">
            <div v-for="(h, i) in recentHosts" :key="i" class="host-item" @click="$router.push(`/hosts/${h.id}`)">
              <span :class="['host-risk-dot', h.risk_level === 'pending' ? 'low' : h.risk_level]" />
              <div>
                <div class="host-name">{{ h.hostname }}</div>
                <div class="host-ip">{{ h.ip }}</div>
              </div>
              <span style="margin-left:auto;font-size:10px;" :style="{ color: riskColor(h.risk_level) }">
                {{ (h.risk_level || 'PENDING').toUpperCase() }}
              </span>
            </div>
          </div>
        </div>

        <!-- 右：规则命中 Top 8 -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">📊 规则命中 Top 8</span>
            <router-link to="/rules" class="panel-link">规则管理 →</router-link>
          </div>
          <div v-if="ruleTop.length === 0" class="empty-state">暂无命中记录</div>
          <div v-for="(r, i) in ruleTop" :key="i" class="eff-item">
            <span class="eff-name">{{ r.name }}</span>
            <div class="eff-bar-bg">
              <div class="eff-bar-fill" :style="{ width: r.pct + '%', background: barColor(i) }" />
            </div>
            <span class="eff-count">{{ r.hits }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'

const loading = ref(true)
const error = ref('')
const stats = ref({})
const recentAlerts = ref([])
const recentHosts = ref([])
const ruleTop = ref([])
const activeRange = ref('7d')
const trendData = ref({})

const timeRanges = [
  { key: '24h', label: '最近 24 小时' },
  { key: '7d', label: '最近 7 天' },
  { key: '30d', label: '最近 30 天' },
  { key: 'all', label: '全部' },
]

const trendDays = computed(() => {
  const m = { '24h': 1, '7d': 7, '30d': 30, 'all': 14 }
  return m[activeRange.value] || 7
})

const aiAvailColor = computed(() => {
  const v = stats.value.ai_availability || 0
  if (v >= 95) return '#2da44e'
  if (v >= 80) return '#d4a72c'
  return '#cf222e'
})

const trendChartRef = ref(null)
const categoryChartRef = ref(null)
let trendChart = null
let categoryChart = null

const BAR_COLORS = ['#cf222e', '#d4a72c', '#0969da', '#8250df', '#0d9488', '#e94e4e', '#c4801a', '#2da44e']

function formatNum(n) {
  if (!n && n !== 0) return '0'
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

function riskColor(level) {
  const m = { critical: '#cf222e', high: '#d4a72c', medium: '#0969da', low: '#2da44e', pending: '#9ca3af' }
  return m[level] || '#9ca3af'
}

function barColor(i) { return BAR_COLORS[i % BAR_COLORS.length] }

async function fetchData() {
  loading.value = true
  error.value = ''
  try {
    const res = await axios.get('/api/dashboard/stats', {
      params: { range: activeRange.value }
    })
    const data = res.data
    if (data.error) {
      throw new Error(data.error)
    }
    stats.value = data.metrics || {}
    recentAlerts.value = (data.recent_alerts || []).slice(0, 6)
    recentHosts.value = (data.recent_hosts || []).slice(0, 8)
    ruleTop.value = (data.rule_top || []).slice(0, 8)
    trendData.value = data.trend || {}
    // 等待 DOM 完全渲染后再初始化图表
    await nextTick()
    setTimeout(() => renderCharts(data), 100)
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '请求失败'
  } finally {
    loading.value = false
  }
}

function renderCharts(data) {
  const trend = data.trend || {}
  const riskDist = data.risk_distribution || {}

  try {
    if (trendChartRef.value && trend.labels && trend.labels.length > 0) {
      trendChart?.dispose()
      trendChart = echarts.init(trendChartRef.value)
      trendChart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: '#fff',
        borderColor: '#e5e7eb', borderWidth: 1,
        textStyle: { fontSize: 12, color: '#1f2937' },
      },
      legend: {
        data: ['高危告警', '中危告警', '规则命中（次）'],
        bottom: 0,
        textStyle: { fontSize: 11, color: '#6b7280' },
      },
      grid: { left: 45, right: 50, top: 20, bottom: 40 },
      xAxis: {
        type: 'category',
        data: trend.labels || [],
        axisLine: { lineStyle: { color: '#e5e7eb' } },
        axisLabel: { color: '#6b7280', fontSize: 11 },
      },
      yAxis: [
        {
          type: 'value', name: '告警数', nameTextStyle: { fontSize: 11, color: '#9ca3af' },
          splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } },
          axisLabel: { color: '#6b7280', fontSize: 11 },
        },
        {
          type: 'value', name: '命中数', nameTextStyle: { fontSize: 11, color: '#9ca3af' },
          splitLine: { show: false },
          axisLabel: { color: '#6b7280', fontSize: 11 },
        },
      ],
      series: [
        {
          name: '高危告警', type: 'bar', stack: 'alert', barWidth: 22,
          itemStyle: { color: '#cf222e', borderRadius: [2, 2, 0, 0] },
          data: trend.critical || [],
        },
        {
          name: '中危告警', type: 'bar', stack: 'alert',
          itemStyle: { color: '#d4a72c' },
          data: trend.high || [],
        },
        {
          name: '规则命中（次）', type: 'line', yAxisIndex: 1,
          smooth: true, symbol: 'circle', symbolSize: 6,
          lineStyle: { color: '#8250df', width: 2 },
          itemStyle: { color: '#8250df' },
          areaStyle: { color: 'rgba(130,80,223,0.08)' },
          data: trend.rule_hits || [],
        },
      ],
    })
    trendChart.resize()
  }
  } catch (e) {
    console.error('Dashboard trend chart error:', e)
  }

  try {
    if (categoryChartRef.value && riskDist.types && riskDist.types.length > 0) {
      categoryChart?.dispose()
      categoryChart = echarts.init(categoryChartRef.value)
      categoryChart.setOption({
        tooltip: {
          trigger: 'item',
          backgroundColor: '#fff',
          borderColor: '#e5e7eb', borderWidth: 1,
          textStyle: { fontSize: 12, color: '#1f2937' },
          formatter: '{b}: {c} 条 ({d}%)',
        },
        series: [{
          type: 'pie',
          radius: ['40%', '68%'],
          center: ['50%', '48%'],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
          label: {
            show: true, formatter: '{b}', fontSize: 11, color: '#374151', lineHeight: 16,
          },
          emphasis: {
            label: { show: true, fontSize: 13, fontWeight: 'bold' },
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.15)' },
          },
          data: (riskDist.types || []).map((d, i) => ({
            name: d.name,
            value: d.value,
            itemStyle: { color: BAR_COLORS[i % BAR_COLORS.length] },
          })),
        }],
      })
      categoryChart.resize()
    }
  } catch (e) {
    console.error('Dashboard chart render error:', e)
  }
}

function onResize() {
  trendChart?.resize()
  categoryChart?.resize()
}

onMounted(() => {
  fetchData()
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  trendChart?.dispose()
  categoryChart?.dispose()
})

watch(activeRange, () => fetchData())
</script>

<style scoped>
.dashboard-page {
  padding: 20px;
  min-height: calc(100vh - 100px);
}
.loading-overlay { padding: 40px; }
.error-box { max-width: 500px; margin: 80px auto; }

.time-range { display: flex; gap: 4px; margin-bottom: 20px; }
.pill {
  padding: 4px 14px; border-radius: 16px; font-size: 12px;
  border: 1px solid #e5e7eb; background: #fff; color: #6b7280;
  cursor: pointer; transition: all .15s;
}
.pill.active { background: #409eff; color: #fff; border-color: #409eff; }
.pill:hover:not(.active) { background: #f3f4f6; }

.kpi-row {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px;
  margin-bottom: 20px;
}
.kpi-card {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 16px 18px; position: relative; overflow: hidden;
  cursor: pointer; transition: box-shadow .2s, transform .15s;
}
.kpi-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.06); transform: translateY(-1px); }
.kpi-label { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
.kpi-value { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; line-height: 1.1; }
.kpi-sub { font-size: 11px; color: #9ca3af; margin-top: 6px; }
.kpi-sub strong { font-weight: 600; }
.trend-up { color: #cf222e; margin-left: 4px; font-weight: 500; }
.trend-down { color: #2da44e; margin-left: 4px; font-weight: 500; }
.kpi-icon {
  position: absolute; right: 14px; top: 14px;
  width: 36px; height: 36px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; opacity: 0.85;
}
.kpi-card.critical .kpi-value { color: #cf222e; }
.kpi-card.high .kpi-value { color: #d4a72c; }
.kpi-card.medium .kpi-value { color: #0969da; }
.kpi-value.kpi-purple { color: #8250df; }
.kpi-value.kpi-green { color: #2da44e; }
.kpi-value.kpi-teal { color: #0d9488; }

.charts-row {
  display: grid; grid-template-columns: 2fr 1fr; gap: 12px;
  margin-bottom: 20px;
}
.chart-card {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 18px 20px;
}
.chart-header { margin-bottom: 12px; }
.chart-title { font-size: 14px; font-weight: 600; color: #1f2937; }
.chart-subtitle { font-size: 11px; color: #9ca3af; margin-top: 2px; }
.chart-box { width: 100%; height: 280px; }

.bottom-row {
  display: grid; grid-template-columns: 1.5fr 1fr 1fr; gap: 12px;
}
.panel {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
  padding: 18px 20px;
}
.panel-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px;
}
.panel-title { font-size: 14px; font-weight: 600; }
.panel-link { font-size: 12px; color: #409eff; text-decoration: none; }
.panel-link:hover { text-decoration: underline; }

.empty-state { text-align: center; color: #9ca3af; font-size: 13px; padding: 30px 0; }

.alert-item {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 0; border-bottom: 1px solid #f3f4f6;
}
.alert-item:last-child { border-bottom: none; }
.alert-severity-dot { flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; }
.dot-critical { background: #cf222e; }
.dot-high { background: #d4a72c; }
.dot-medium { background: #0969da; }
.dot-low { background: #2da44e; }
.alert-body { flex: 1; min-width: 0; }
.alert-title { font-size: 13px; font-weight: 500; color: #1f2937; }
.alert-meta { font-size: 11px; color: #9ca3af; margin-top: 2px; }
.alert-badge {
  flex-shrink: 0; padding: 1px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 500; margin-top: 2px;
}
.badge-critical { background: #ffebe9; color: #cf222e; }
.badge-high { background: #fff8c5; color: #9a6700; }
.badge-medium { background: #ddf4ff; color: #0969da; }

.host-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.host-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 6px; border: 1px solid #f3f4f6;
  font-size: 12px; cursor: pointer; transition: background .15s;
}
.host-item:hover { background: #f9fafb; }
.host-name { font-weight: 500; color: #1f2937; }
.host-ip { font-size: 10px; color: #9ca3af; margin-top: 1px; }
.host-risk-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.host-risk-dot.critical { background: #cf222e; }
.host-risk-dot.high { background: #d4a72c; }
.host-risk-dot.medium { background: #0969da; }
.host-risk-dot.low { background: #2da44e; }

.eff-item {
  display: flex; align-items: center; padding: 8px 0;
  border-bottom: 1px solid #f3f4f6; font-size: 12px;
}
.eff-item:last-child { border-bottom: none; }
.eff-name { flex: 1; font-weight: 500; color: #1f2937; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.eff-count { font-size: 11px; color: #6b7280; width: 40px; text-align: right; flex-shrink: 0; }
.eff-bar-bg { width: 80px; height: 6px; background: #f3f4f6; border-radius: 3px; margin: 0 10px; overflow: hidden; flex-shrink: 0; }
.eff-bar-fill { height: 100%; border-radius: 3px; transition: width 1s ease; }

@media (max-width: 1100px) {
  .kpi-row { grid-template-columns: repeat(3, 1fr); }
  .charts-row { grid-template-columns: 1fr; }
  .bottom-row { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
