<template>
  <div class="unified-alert">
    <!-- ===== 顶栏 ===== -->
    <div class="top-bar">
      <div class="top-left">
        <h2>🛡️ 告警监控中心</h2>
        <span class="top-sub">Alert &amp; Monitoring Center</span>
      </div>
      <div class="top-right">
        <span class="status-badge">
          <span class="dot online" /> <span class="stat-online">-</span> 在线
        </span>
        <el-button size="small" @click="fetchAll" :loading="loading" style="background:#242b3d;border-color:#2d3548;color:#c8cdd5;">
          ↻ 刷新
        </el-button>
      </div>
    </div>

    <!-- ===== 统计卡片 ===== -->
    <div class="stats-row">
      <div class="stat-card critical">
        <div class="s-label">🚨 待处理告警</div>
        <div class="s-value">{{ stats.open }}</div>
        <div class="s-sub">严重 <strong>{{ stats.critical }}</strong> 条</div>
      </div>
      <div class="stat-card high">
        <div class="s-label">📥 今日新增</div>
        <div class="s-value">{{ stats.today }}</div>
        <div class="s-sub">近 1h <strong>{{ hourlyNew }}</strong> 条</div>
      </div>
      <div class="stat-card green">
        <div class="s-label">✅ 已处置</div>
        <div class="s-value">{{ stats.total - stats.open }}</div>
        <div class="s-sub">处置率 {{ stats.total ? Math.round((stats.total - stats.open) / stats.total * 100) : 0 }}%</div>
      </div>
      <div class="stat-card blue">
        <div class="s-label">📊 规则命中</div>
        <div class="s-value">{{ ruleHitTotal }}</div>
        <div class="s-sub">活跃规则 <strong>{{ stats.active_rules || '-' }}</strong> 条</div>
      </div>
      <div class="stat-card green">
        <div class="s-label">💻 监控主机</div>
        <div class="s-value">{{ onlineCount }}</div>
        <div class="s-sub">总计 {{ hosts.length }} 台</div>
      </div>
      <div class="stat-card blue">
        <div class="s-label">⚡ 事件速率</div>
        <div class="s-value">{{ eventRate }}</div>
        <div class="s-sub">峰值 {{ eventPeak }}</div>
      </div>
    </div>

    <!-- ===== 图表 + 主机 ===== -->
    <div class="mid-section">
      <div class="mid-panel">
        <div class="p-head">📈 告警趋势 <span class="p-badge">过去 7 天</span></div>
        <div ref="trendChartRef" class="chart-box" />
      </div>
      <div class="mid-panel">
        <div class="p-head">🧩 严重度分布 <span class="p-badge">按告警等级</span></div>
        <div ref="pieChartRef" class="chart-box" />
      </div>
      <div class="mid-panel">
        <div class="p-head">🖥️ 主机在线 <span class="p-badge">实时</span></div>
        <div class="host-scroll">
          <div v-for="h in displayHosts" :key="h.id" class="h-item" @click="$router.push(`/hosts/${h.id}`)">
            <span :class="['h-dot', h.status === 'online' ? 'on' : 'off']" />
            <span class="h-name">{{ h.hostname }}</span>
            <span class="h-ip">{{ h.ip_address || '-' }}</span>
            <span class="h-badge" v-if="h.alertCount > 0">{{ h.alertCount }}</span>
          </div>
          <div v-if="hosts.length === 0" class="empty">暂无主机</div>
        </div>
      </div>
    </div>

    <!-- ===== 筛选栏 ===== -->
    <div class="filter-bar">
      <el-select v-model="f.severity" placeholder="严重度" clearable size="small" style="width:100px" @change="fetchAlerts">
        <el-option label="严重" value="critical" />
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <el-select v-model="f.status" placeholder="状态" clearable size="small" style="width:100px" @change="fetchAlerts">
        <el-option label="未处理" value="open" />
        <el-option label="已确认" value="acknowledged" />
        <el-option label="已解决" value="resolved" />
        <el-option label="已忽略" value="dismissed" />
      </el-select>
      <el-date-picker v-model="f.dateRange" type="datetimerange" range-separator="至"
        start-placeholder="开始日期" end-placeholder="结束日期" size="small" style="width:240px"
        :shortcuts="dateShortcuts" @change="fetchAlerts" />
      <el-cascader v-model="f.caseHost" :options="caseHostOptions"
        :props="{ expandTrigger: 'hover', label: 'label', value: 'value', children: 'children' }"
        placeholder="案件 → 主机" clearable size="small" style="width:180px" @change="onCaseChange" />
      <el-input v-model="f.search" placeholder="🔍 搜索标题/进程/规则..." size="small" style="width:160px"
        clearable @keyup.enter="fetchAlerts" @clear="fetchAlerts" />
      <el-button size="small" type="primary" @click="fetchAlerts">搜索</el-button>
      <el-button size="small" @click="resetFilters" :disabled="!hasFilter">重置</el-button>
      <div style="flex:1" />
      <el-button size="small" type="warning" plain :disabled="selected.length===0" @click="batchOp('ack')">✅ 批量确认</el-button>
      <el-button size="small" type="success" plain :disabled="selected.length===0" @click="batchOp('resolve')">✅ 批量解决</el-button>
    </div>
    <!-- 条件标签 -->
    <div v-if="hasFilter" class="filter-tags">
      <el-tag v-if="f.severity" closable size="small" @close="f.severity='';fetchAlerts()">严重度: {{ sevLabel(f.severity) }}</el-tag>
      <el-tag v-if="f.status" closable size="small" @close="f.status='';fetchAlerts()">状态: {{ stsLabel(f.status) }}</el-tag>
      <el-tag v-if="f.dateRange" closable size="small" @close="f.dateRange=null;fetchAlerts()">日期</el-tag>
      <el-tag v-if="f.caseHost.length" closable size="small" @close="f.caseHost=[];fetchAlerts()">范围</el-tag>
      <el-tag v-if="f.search" closable size="small" @close="f.search='';fetchAlerts()">搜索: {{ f.search }}</el-tag>
      <el-button size="small" text type="primary" @click="resetFilters">清除全部</el-button>
    </div>

    <!-- ===== 告警表格 ===== -->
    <el-table :data="alerts" v-loading="loading" stripe border style="margin-top:12px;width:100%;"
      @selection-change="onSelect" :max-height="420" size="small">
      <el-table-column type="selection" width="36" />
      <el-table-column label="严重度" width="72">
        <template #default="{row}">
          <el-tag :type="sevType(row.severity)" size="small" effect="dark" style="width:48px;text-align:center">
            {{ sevLabel(row.severity) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="150">
        <template #default="{row}"><span class="cell-time">{{ formatTime(row.last_seen_at || row.first_seen_at) }}</span></template>
      </el-table-column>
      <el-table-column label="告警内容" min-width="220">
        <template #default="{row}">
          <div class="cell-title">{{ row.title }}</div>
          <div class="cell-detail" v-if="row.detail">{{ row.detail }}</div>
        </template>
      </el-table-column>
      <el-table-column label="规则" width="120"><template #default="{row}"><span class="cell-rule">{{ row.rule_label || row.rule_name }}</span></template></el-table-column>
      <el-table-column label="主机" width="100"><template #default="{row}"><span class="cell-host">{{ row.hostname || '-' }}</span></template></el-table-column>
      <el-table-column label="次数" width="50" align="center"><template #default="{row}">{{ row.count }}</template></el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{row}"><el-tag :type="stsType(row.status)" size="small">{{ stsLabel(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{row}">
          <el-button link type="primary" size="small" @click="viewDetail(row)">详情</el-button>
          <el-button v-if="row.status==='open'" link type="warning" size="small" @click="handleAck(row)">确认</el-button>
          <el-button v-if="row.status!=='resolved'" link type="success" size="small" @click="handleResolve(row)">解决</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="page-wrap">
      <span class="page-info">共 {{ stats.total }} 条告警，显示 {{ alerts.length }} 条</span>
      <el-pagination v-model:current-page="page" :page-size="50" :total="stats.total"
        layout="prev, pager, next" background small @current-change="fetchAlerts" />
    </div>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="'🔍 ' + (detail?.title || '告警详情')" size="420px">
      <template v-if="detail">
        <div class="d-section"><span class="d-lbl">严重度</span><el-tag :type="sevType(detail.severity)" effect="dark">{{ sevLabel(detail.severity) }}</el-tag></div>
        <el-divider />
        <div class="d-section"><span class="d-lbl">告警描述</span><div class="d-val">{{ detail.title }}</div><div class="d-sub">{{ detail.detail || '无' }}</div></div>
        <el-divider />
        <div class="d-section"><span class="d-lbl">触发进程</span><div class="d-val">{{ detail.source_process || 'N/A' }}</div><div class="d-sub">PID: {{ detail.source_pid || 'N/A' }}</div></div>
        <el-divider />
        <div class="d-section"><span class="d-lbl">命中规则</span><div class="d-val">{{ detail.rule_name }}</div></div>
        <el-divider />
        <div class="d-section"><span class="d-lbl">时间</span><div class="d-sub">首次: {{ detail.first_seen_at }}<br>最近: {{ detail.last_seen_at }}<br>聚合: {{ detail.count }} 次</div></div>
        <el-divider />
        <div class="d-section"><span class="d-lbl">状态</span><el-tag :type="stsType(detail.status)" size="small">{{ stsLabel(detail.status) }}</el-tag></div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getAlerts, getAlertStats, acknowledgeAlert, resolveAlert, dismissAlert, getHostsStatus, getCasesWithHosts, getAlertTrend } from '@/api/alerts'

// ===== 状态 =====
const alerts = ref([])
const stats = ref({ total: 0, open: 0, critical: 0, today: 0, active_rules: 0 })
const loading = ref(false)
const page = ref(1)
const selected = ref([])
const drawerVisible = ref(false)
const detail = ref(null)
const onlineCount = ref(0)
const hosts = ref([])
const caseHostOptions = ref([])
const hourlyNew = ref('-')
const ruleHitTotal = ref('-')
const eventRate = ref('-')
const eventPeak = ref('-')

const f = reactive({ severity: '', status: '', dateRange: null, caseHost: [], search: '' })
const hasFilter = computed(() => f.severity || f.status || f.dateRange || f.caseHost.length || f.search)

const dateShortcuts = [
  { text: '近 1 小时', value: () => [new Date(Date.now() - 3600000), new Date()] },
  { text: '近 24 小时', value: () => [new Date(Date.now() - 86400000), new Date()] },
  { text: '近 7 天', value: () => [new Date(Date.now() - 604800000), new Date()] },
  { text: '近 30 天', value: () => [new Date(Date.now() - 2592000000), new Date()] },
  { text: '今天', value: () => { const d = new Date(); d.setHours(0,0,0,0); return [d, new Date()] } },
]

const displayHosts = computed(() => hosts.value.slice(0, 8))

// ===== 工具函数 =====
function sevType(s) { return { critical: 'danger', high: 'warning', medium: 'primary', low: 'info' }[s] || 'info' }
function sevLabel(s) { return { critical: '严重', high: '高危', medium: '中危', low: '低危' }[s] || s }
function stsType(s) { return { open: 'danger', acknowledged: 'warning', resolved: 'success', dismissed: 'info' }[s] || 'info' }
function stsLabel(s) { return { open: '未处理', acknowledged: '已确认', resolved: '已解决', dismissed: '已忽略' }[s] || s }

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z')
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前'
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// ===== 数据拉取 =====
async function fetchStats() {
  try {
    const res = await getAlertStats()
    // 后端返回 {success, data: {total, open, ...}}，res 是 success/data 整体，res.data 是 stats dict
    stats.value = res.data || { total: 0, open: 0, critical: 0, today: 0 }
    hourlyNew.value = res.data?.hourly || '-'
    ruleHitTotal.value = res.data?.rule_hits ?? '-'
    console.log('Stats:', stats.value)
  } catch (e) { console.error(e) }
}

async function fetchAlerts() {
  loading.value = true
  try {
    const params = { limit: 50, offset: (page.value - 1) * 50 }
    if (f.severity) params.severity = f.severity
    if (f.status) params.status = f.status
    if (f.dateRange) { params.date_from = f.dateRange[0].toISOString(); params.date_to = f.dateRange[1].toISOString() }
    if (f.caseHost.length >= 2) params.host_id = f.caseHost[1]
    else if (f.caseHost.length === 1) params.case_id = f.caseHost[0]
    if (f.search) params.search = f.search
    const res = await getAlerts(params)
    alerts.value = res.data || []
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function fetchHosts() {
  try {
    const res = await getHostsStatus()
    hosts.value = res.data || []
    onlineCount.value = hosts.value.filter(h => h.status === 'online').length
  } catch (e) { console.error(e) }
}

async function fetchCaseHosts() {
  try {
    const res = await getCasesWithHosts()
    // getCasesWithHosts 返回 {success, data: [...]}
    // res.data 是数组
    caseHostOptions.value = res.data || []
    console.log('Case host options loaded:', caseHostOptions.value.length)
  } catch (e) { console.error(e) }
}

function onCaseChange(val) { fetchAlerts() }
function resetFilters() { f.severity = ''; f.status = ''; f.dateRange = null; f.caseHost = []; f.search = ''; fetchAlerts() }
function onSelect(rows) { selected.value = rows }

// ===== 操作 =====
async function handleAck(row) {
  try {
    await acknowledgeAlert(row.id)
    row.status = 'acknowledged'
    ElMessage.success('已确认')
  } catch (e) { ElMessage.error(e.message) }
}
async function handleResolve(row) {
  try {
    await resolveAlert(row.id)
    row.status = 'resolved'
    ElMessage.success('已解决')
  } catch (e) { ElMessage.error(e.message) }
}
async function batchOp(op) {
  const ids = selected.value.map(r => r.id)
  try {
    const fn = op === 'ack' ? acknowledgeAlert : resolveAlert
    await Promise.all(ids.map(fn))
    ElMessage.success(`已${op === 'ack' ? '确认' : '解决'} ${ids.length} 条`)
    selected.value = []
    fetchAlerts()
  } catch (e) { ElMessage.error(e.message) }
}
function viewDetail(row) { detail.value = row; drawerVisible.value = true }

// ===== ECharts =====
const trendChartRef = ref(null)
const pieChartRef = ref(null)
let trendChart = null, pieChart = null

function renderCharts(trendData) {
  if (trendChartRef.value) {
    trendChart?.dispose()
    trendChart = echarts.init(trendChartRef.value)
    // 后端已自动补全空桶，直接用 bucket/label
    const hours = trendData?.length ? trendData.map(h => h.label) : []
    const critical = trendData?.length ? trendData.map(h => h.critical || 0) : []
    const high = trendData?.length ? trendData.map(h => h.high || 0) : []
    const medium = trendData?.length ? trendData.map(h => h.medium || 0) : []
    const low = trendData?.length ? trendData.map(h => h.low || 0) : []
    trendChart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: '#1a1f2e', borderColor: '#2d3548', textStyle: { color: '#e0e4ea', fontSize: 11 },
      },
      legend: { data: ['严重', '高危', '中危', '低危'], textStyle: { color: '#8b929a', fontSize: 10 }, bottom: 30, itemWidth: 10, itemHeight: 8 },
      grid: { left: 36, right: 12, top: 6, bottom: 60 },
      dataZoom: [
        {
          type: 'inside',       // 鼠标滚轮 + 拖拽
          xAxisIndex: 0,
          start: 0,
          end: 100,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
        },
        {
          type: 'slider',       // 底部滑块
          xAxisIndex: 0,
          start: 0,
          end: 100,
          height: 18,
          bottom: 6,
          borderColor: '#2d3548',
          backgroundColor: 'rgba(45,53,72,0.3)',
          fillerColor: 'rgba(88,166,255,0.15)',
          handleStyle: { color: '#58a6ff', borderColor: '#58a6ff' },
          textStyle: { color: '#6e7681', fontSize: 10 },
          dataBackground: { lineStyle: { color: '#3d475e' }, areaStyle: { color: 'rgba(88,166,255,0.1)' } },
          selectedDataBackground: { lineStyle: { color: '#58a6ff' }, areaStyle: { color: 'rgba(88,166,255,0.2)' } },
        }
      ],
      xAxis: {
        type: 'category', data: hours,
        axisLabel: { color: '#6e7681', fontSize: 9, interval: 'auto' },
        axisLine: { lineStyle: { color: '#242b3d' } },
        axisTick: { show: false },
      },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#1e2433', type: 'dashed' } }, axisLabel: { color: '#6e7681', fontSize: 9 } },
      series: [
        { name: '严重', type: 'bar', stack: 't', data: critical, itemStyle: { color: '#f85149', borderRadius: [2, 2, 0, 0] }, barWidth: '55%' },
        { name: '高危', type: 'bar', stack: 't', data: high, itemStyle: { color: '#d4a72c' } },
        { name: '中危', type: 'bar', stack: 't', data: medium, itemStyle: { color: '#58a6ff' } },
        { name: '低危', type: 'bar', stack: 't', data: low, itemStyle: { color: '#6e7681', borderRadius: [0, 0, 2, 2] } },
      ]
    })
  }

  if (pieChartRef.value) {
    pieChart?.dispose()
    pieChart = echarts.init(pieChartRef.value)
    // 优先使用后端返回的 severity_dist 全量分布，没有则用 stats 字段
    const dist = stats.value.severity_dist || {}
    const c = dist.critical || 0
    const h = dist.high || 0
    const m = dist.medium || 0
    const l = dist.low || 0
    const pieData = []
    if (c) pieData.push({ name: '严重', value: c, itemStyle: { color: '#f85149' } })
    if (h) pieData.push({ name: '高危', value: h, itemStyle: { color: '#d4a72c' } })
    if (m) pieData.push({ name: '中危', value: m, itemStyle: { color: '#58a6ff' } })
    if (l) pieData.push({ name: '低危', value: l, itemStyle: { color: '#6e7681' } })
    if (pieData.length === 0) pieData.push({ name: '暂无数据', value: 1, itemStyle: { color: '#2d3548' } })
    pieChart.setOption({
      tooltip: { trigger: 'item', backgroundColor: '#1a1f2e', borderColor: '#2d3548', textStyle: { color: '#e0e4ea' }, formatter: '{b}: {c} 条 ({d}%)' },
      series: [{
        type: 'pie', radius: ['45%', '70%'], center: ['50%', '48%'],
        avoidLabelOverlap: true, itemStyle: { borderRadius: 4, borderColor: '#0f1219', borderWidth: 2 },
        label: { show: pieData.length > 1, formatter: '{b}\n{d}%', fontSize: 10, color: '#c8cdd5', lineHeight: 14 },
        emphasis: { label: { fontSize: 12, fontWeight: 'bold' } },
        data: pieData,
      }]
    })
  }
}

// ===== WebSocket =====
let ws = null
let trendRefreshTimer = null
function connectWS() {
  const token = localStorage.getItem('ir_token')
  if (!token) return
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${proto}//${location.host}/api/ws/alerts?token=${token}`)
  ws.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data)
      if (d.type === 'new_alert') {
        alerts.value.unshift(d.alert)
        if (alerts.value.length > 50) alerts.value.pop()
      }
    } catch (_) {}
  }
  ws.onclose = () => setTimeout(connectWS, 5000)
}

// ===== 生命周期 =====
async function fetchAll() {
  loading.value = true
  await Promise.all([fetchStats(), fetchAlerts(), fetchHosts(), fetchCaseHosts()])
  await nextTick()
  setTimeout(() => {
    try {
      fetchAlertTrend()
    } catch (_) {}
    renderCharts(null)
  }, 150)
  loading.value = false
}

async function fetchAlertTrend() {
  try {
    const res = await getAlertTrend(168)  // 7 天
    const trendData = res.data || []
    if (trendData.length) {
      eventRate.value = (trendData.reduce((s, h) => s + (h.total || 0), 0) / trendData.length).toFixed(1) + '/h'
      eventPeak.value = Math.max(...trendData.map(h => h.total || 0)) + '/h'
    }
    await nextTick()
    renderCharts(trendData)
  } catch (e) { console.error(e) }
}

onMounted(async () => {
  await fetchAll()
  connectWS()
  trendRefreshTimer = setInterval(fetchAlertTrend, 180000)
})

onUnmounted(() => {
  trendChart?.dispose()
  pieChart?.dispose()
  ws?.close()
  if (trendRefreshTimer) clearInterval(trendRefreshTimer)
})
</script>

<style scoped>
.unified-alert { padding: 16px 20px; min-height: calc(100vh - 100px); }

/* ===== 顶栏 ===== */
.top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.top-left { display: flex; align-items: baseline; gap: 8px; }
.top-left h2 { font-size: 20px; font-weight: 600; }
.top-sub { font-size: 12px; color: #8b929a; }
.top-right { display: flex; align-items: center; gap: 10px; }
.status-badge { font-size: 12px; color: #6e7681; }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.dot.online { background: #2da44e; box-shadow: 0 0 5px #2da44e66; }
.stat-online { color: #2da44e; font-weight: 600; }

/* ===== 统计卡片 ===== */
.stats-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 14px; }
.stat-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 13px 15px; transition: .2s; }
.stat-card:hover { border-color: #d1d5db; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
.s-label { font-size: 11px; color: #6b7280; margin-bottom: 3px; }
.s-value { font-size: 24px; font-weight: 700; letter-spacing: -.3px; }
.stat-card.critical .s-value { color: #dc2626; }
.stat-card.high .s-value { color: #d97706; }
.stat-card.green .s-value { color: #16a34a; }
.stat-card.blue .s-value { color: #2563eb; }
.s-sub { font-size: 11px; color: #9ca3af; margin-top: 3px; }

/* ===== 图表 + 主机 ===== */
.mid-section { display: grid; grid-template-columns: 1.4fr 1fr 0.8fr; gap: 10px; margin-bottom: 14px; }
.mid-panel { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; }
.p-head { font-size: 13px; font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.p-badge { font-size: 10px; color: #9ca3af; font-weight: 400; }
.chart-box { width: 100%; height: 180px; }

.host-scroll { max-height: 180px; overflow-y: auto; }
.h-item { display: flex; align-items: center; gap: 6px; padding: 5px 6px; border-radius: 4px; cursor: pointer; font-size: 12px; transition: .15s; }
.h-item:hover { background: #f3f4f6; }
.h-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.h-dot.on { background: #16a34a; box-shadow: 0 0 3px #16a34a55; }
.h-dot.off { background: #9ca3af; }
.h-name { flex: 1; color: #374151; }
.h-ip { font-size: 10px; color: #9ca3af; }
.h-badge { font-size: 10px; background: #fee2e2; color: #dc2626; padding: 0 6px; border-radius: 8px; font-weight: 600; }

/* ===== 筛选栏 ===== */
.filter-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 14px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }
.filter-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; align-items: center; }

/* ===== 表格 ===== */
.cell-time { font-size: 12px; color: #6b7280; white-space: nowrap; }
.cell-title { font-size: 13px; color: #1f2937; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-detail { font-size: 11px; color: #9ca3af; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-rule { font-size: 12px; color: #6b7280; }
.cell-host { font-size: 12px; color: #6b7280; }

.page-wrap { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; }
.page-info { font-size: 12px; color: #9ca3af; }

/* ===== 详情抽屉 ===== */
.d-section { margin-bottom: 4px; }
.d-lbl { font-size: 12px; color: #6b7280; display: block; margin-bottom: 4px; }
.d-val { font-size: 14px; color: #1f2937; }
.d-sub { font-size: 12px; color: #6b7280; margin-top: 2px; line-height: 1.6; }

.empty { text-align: center; padding: 20px; color: #9ca3af; font-size: 12px; }
</style>
