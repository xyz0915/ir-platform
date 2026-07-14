<template>
  <div class="log-page">
    <!-- ===== 顶栏 ===== -->
    <div class="top-bar">
      <h2>🛡️ 日志分析中心</h2>
      <div class="top-actions">
        <el-button size="small" :loading="loading" @click="fetchAll">↻ 刷新</el-button>
      </div>
    </div>

    <!-- ===== KPI ===== -->
    <div class="kpi-row">
      <div class="kpi"><div class="k-label">📦 总日志</div><div class="k-val blue">{{ stats.total }}</div></div>
      <div class="kpi"><div class="k-label">🚨 严重</div><div class="k-val critical">{{ stats.by_severity?.critical || 0 }}</div></div>
      <div class="kpi"><div class="k-label">🟡 高危+中危</div><div class="k-val high">{{ (stats.by_severity?.high||0) + (stats.by_severity?.medium||0) }}</div></div>
      <div class="kpi"><div class="k-label">🔑 登录成功</div><div class="k-val medium">{{ byTypeMatch('logon') }}</div></div>
      <div class="kpi"><div class="k-label">⚙️ 服务状态</div><div class="k-val blue">{{ byTypeMatch('service') }}</div></div>
      <div class="kpi"><div class="k-label">🎯 高危标签</div><div class="k-val critical">{{ alertTags }}</div></div>
    </div>

    <!-- ===== 视图切换 + 图表 ===== -->
    <div class="chart-section">
      <div class="view-tabs">
        <span v-for="v in views" :key="v.key" :class="['v-tab', { active: activeView === v.key }]" @click="switchView(v.key)">{{ v.label }}</span>
      </div>
      <div class="chart-row">
        <div class="chart-box">
          <div class="c-head">⏱ 事件时间线 <span class="c-badge">缩放拖拽 | 聚合</span></div>
          <div ref="timelineRef" class="c-body" />
        </div>
        <div class="chart-box">
          <div class="c-head">🧩 类型分布 <span class="c-badge">TOP 10</span></div>
          <div ref="pieRef" class="c-body" />
        </div>
      </div>
    </div>

    <!-- ===== 筛选栏 ===== -->
    <div class="filter-bar">
      <el-select v-model="f.eventType" placeholder="事件类型" clearable size="small" style="width:120px" @change="search">
        <el-option label="全部" value="" />
        <el-option v-for="(label, key) in typeOptions" :key="key" :label="label" :value="key" />
      </el-select>
      <el-select v-model="f.severity" placeholder="严重度" clearable size="small" style="width:90px" @change="search">
        <el-option label="严重" value="critical" />
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <el-input v-model="f.sourceIp" placeholder="来源 IP" size="small" style="width:110px" clearable @keyup.enter="search" />
      <el-input v-model="f.userName" placeholder="用户名" size="small" style="width:100px" clearable @keyup.enter="search" />
      <el-input v-model="f.processName" placeholder="进程名" size="small" style="width:100px" clearable @keyup.enter="search" />
      <el-input v-model="f.keyword" placeholder="🔍 全文搜索" size="small" style="width:140px" clearable @keyup.enter="search" />
      <el-date-picker v-model="f.dateRange" type="datetimerange" size="small" style="width:220px"
        range-separator="至" :shortcuts="dateShortcuts" @change="search" />
      <el-button size="small" type="primary" @click="search">搜索</el-button>
      <el-button size="small" @click="resetFilters">重置</el-button>
      <div style="margin-left:4px" class="quick-tags">
        <el-tag v-for="t in quickFilters" :key="t.key" :type="t.type" size="small" effect="plain"
          style="cursor:pointer;margin:0 2px" @click="applyQuick(t)">{{ t.label }}</el-tag>
      </div>
    </div>

    <!-- ===== 日志表格 ===== -->
    <div class="table-wrap">
      <el-table :data="items" v-loading="loading" stripe border size="small" :max-height="500"
        @row-click="openDetail" style="width:100%">
        <el-table-column label="时间" width="140">
          <template #default="{row}"><span class="t-time">{{ row.timestamp ? row.timestamp.slice(0,19).replace('T',' ') : (row.created_at ? row.created_at.slice(11,19) : '-') }}</span></template>
        </el-table-column>
        <el-table-column label="严重度" width="80">
          <template #default="{row}">
            <el-tag :type="sevType(row.severity)" size="small" effect="dark" style="display:block;text-align:center">{{ sevLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="ID" width="60">
          <template #default="{row}"><span class="pivot" @click.stop="pivot('event_id', row.event_id)">{{ row.event_id || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="主机" min-width="120">
          <template #default="{row}"><span class="pivot" @click.stop="pivot('hostname', row.hostname)">{{ row.hostname || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="来源 IP" min-width="100">
          <template #default="{row}"><span class="pivot" @click.stop="pivot('source_ip', row.source_ip)">{{ row.source_ip || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="用户" min-width="100">
          <template #default="{row}"><span class="pivot" @click.stop="pivot('user_name', row.user_name)">{{ row.user_name || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="进程" min-width="160">
          <template #default="{row}"><span class="pivot" @click.stop="pivot('process_name', row.process_name)">{{ row.process_name || '-' }}</span></template>
        </el-table-column>
        <el-table-column label="描述" min-width="240">
          <template #default="{row}">
            <div class="t-desc">{{ row.command_line || row.description || (row.process_name||'') + '@' + (row.hostname||'') }}</div>
            <div v-if="row.tags" class="t-tags">
              <el-tag v-for="t in (row.tags||'').split(',').filter(Boolean).slice(0,2)" :key="t" size="small" :type="tagType(t)" effect="plain" style="margin-right:2px">{{ t }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="标签" width="120">
          <template #default="{row}">
            <div v-if="row.mitre_attack" class="t-mitre">MITRE: <a :href="'https://attack.mitre.org/techniques/'+row.mitre_attack.replace('.','/')" target="_blank" @click.stop>{{ row.mitre_attack }}</a></div>
            <el-tag v-for="t in (row.tags||'').split(',').filter(Boolean).slice(0,2)" :key="'tag2-'+t" size="small" :type="tagType(t)" effect="plain">{{ t }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="page-foot">
        <span>共 {{ total }} 条·显示 {{ items.length }} 条</span>
        <el-pagination v-model:current-page="page" :page-size="50" :total="total" layout="prev,pager,next" small background @current-change="search" />
      </div>
    </div>

    <!-- ===== 详情抽屉 ===== -->
    <el-drawer v-model="drawer" :title="'🔍 ' + (detail?.event_label || '日志详情')" size="420px">
      <template v-if="detail">
        <div class="d-section"><span class="d-lbl">严重度</span><el-tag :type="sevType(detail.severity)" effect="dark">{{ detail.severity }}</el-tag></div>
        <el-divider />
        <div class="d-section"><span class="d-lbl">时间</span><div class="d-val">{{ detail.timestamp }}</div></div>
        <el-divider />
        <div class="d-section"><span class="d-lbl">主机</span><div class="d-val pivot" @click="jumpHost(detail)">{{ detail.hostname }}</div></div>
        <el-divider />
        <div class="d-section">
          <div class="d-lbl">事件</div>
          <div class="d-val">{{ detail.event_label }}</div>
          <div class="d-sub" v-if="detail.mitre_attack">MITRE ATT&CK: <a :href="'https://attack.mitre.org/techniques/'+detail.mitre_attack.replace('.','/')" target="_blank">{{ detail.mitre_attack }}</a></div>
        </div>
        <el-divider />
        <div class="d-section" v-if="detail.source_ip"><span class="d-lbl">来源 IP</span><div class="d-val pivot" @click="pivot('source_ip', detail.source_ip)">{{ detail.source_ip }}</div></div>
        <div class="d-section" v-if="detail.user_name"><span class="d-lbl">用户</span><div class="d-val pivot" @click="pivot('user_name', detail.user_name)">{{ detail.user_name }}</div></div>
        <div class="d-section" v-if="detail.process_name"><span class="d-lbl">进程</span><div class="d-val">{{ detail.process_name }}{{ detail.process_pid ? ' (PID '+detail.process_pid+')' : '' }}</div></div>
        <div class="d-section" v-if="detail.logon_session"><span class="d-lbl">会话 ID</span><div class="d-val pivot" @click="openSession(detail.logon_session)">{{ detail.logon_session }}</div></div>
        <el-divider />
        <div class="d-section" v-if="detail.command_line">
          <span class="d-lbl">命令行</span>
          <pre class="d-pre">{{ detail.command_line }}</pre>
        </div>
        <div class="d-section" v-if="detail.description && detail.description !== detail.command_line">
          <span class="d-lbl">描述</span>
          <pre class="d-pre">{{ detail.description }}</pre>
        </div>
        <el-divider />
        <div class="d-section" v-if="detail.tags">
          <span class="d-lbl">🏷️ 安全标签</span>
          <div style="display:flex;gap:4px;flex-wrap:wrap">
            <el-tag v-for="t in (detail.tags||'').split(',')" :key="t" size="small" type="warning">{{ t }}</el-tag>
          </div>
        </div>
        <el-divider />
        <div class="d-actions">
          <el-button size="small" @click="pivot('user_name', detail.user_name)" :disabled="!detail.user_name">👤 查看该用户</el-button>
          <el-button size="small" @click="pivot('source_ip', detail.source_ip)" :disabled="!detail.source_ip">🌐 查看该 IP</el-button>
          <el-button size="small" @click="jumpHost(detail)">🖥 跳转主机</el-button>
          <el-button size="small" @click="openSession(detail.logon_session)" :disabled="!detail.logon_session" type="primary">🔗 重建会话</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { searchLogsV1, getLogSummary, getLogTimeline, getBruteForce, logPivot } from '@/api/logs'

const router = useRouter()
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const stats = ref({ total: 0, by_severity: {}, by_type: {} })
const drawer = ref(false)
const detail = ref(null)
const activeView = ref('overview')
const alertTags = ref('-')

const views = [
  { key: 'overview', label: '📈 概览' },
  { key: 'brute', label: '🔑 暴破分析' },
  { key: 'lateral', label: '🔄 横向移动' },
  { key: 'process', label: '🌳 进程溯源' },
  { key: 'threat', label: '🚨 威胁告警' },
]

const f = reactive({ eventType: '', severity: '', sourceIp: '', userName: '', processName: '', keyword: '', dateRange: null })
const typeOptions = { process_creation: '进程创建', failed_logon: '登录失败', successful_logon: '登录成功', admin_logon: '管理员登录', service_installed: '服务安装', scheduled_task_created: '计划任务', audit_log_cleared: '审计清除', user_created: '用户创建' }

const quickFilters = [
  { key: 'audit_clear', label: '🚨 审计清除', type: 'danger', params: { eventType: 'audit_log_cleared' } },
  { key: 'ps_encoded', label: '⚡ PS编码', type: 'warning', params: { keyword: 'powershell -enc' } },
  { key: 'bruteforce', label: '🔑 暴破', type: 'warning', params: { eventType: 'failed_logon' } },
  { key: 'service', label: '📦 服务安装', type: '', params: { eventType: 'service_installed' } },
  { key: 'credential', label: '🎯 凭据窃取', type: 'danger', params: { keyword: 'mimikatz' } },
]

const dateShortcuts = [
  { text: '近 1 小时', value: () => [new Date(Date.now() - 3600000), new Date()] },
  { text: '近 24 小时', value: () => [new Date(Date.now() - 86400000), new Date()] },
  { text: '近 7 天', value: () => [new Date(Date.now() - 604800000), new Date()] },
]

function sevType(s) { return { critical: 'danger', high: 'warning', medium: 'primary', low: 'info' }[s] || 'info' }
function sevLabel(s) { return { critical: '严重', high: '高危', medium: '中危', low: '低危', info: '信息' }[s] || s || '信息' }
function byTypeMatch(keyword) {
  const byType = stats.value.by_type || {}
  let total = 0
  for (const [k, v] of Object.entries(byType)) {
    if (k.includes(keyword) || k.includes(keyword.toLowerCase())) total += v
  }
  return total
}
function tagType(t) {
  if (/mimikatz|credential|procdump|sekurlsa/.test(t)) return 'danger'
  if (/powershell|certutil|wevtutil/.test(t)) return 'warning'
  if (/psexec|wmic|winrm/.test(t)) return 'warning'
  return 'info'
}

// ===== 数据 =====
async function fetchStats() {
  try {
    const res = await getLogSummary()
    stats.value = res.data || { total: 0, by_severity: {}, by_type: {} }
    // 高危标签取 severity 中的 critical+high 总数
    const sev = stats.value.by_severity || {}
    alertTags.value = (sev.critical || 0) + (sev.high || 0)
  } catch (e) { console.error(e) }
}

async function search() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: 50 }
    if (f.eventType) params.event_type = f.eventType
    if (f.severity) params.severity = f.severity
    if (f.sourceIp) params.source_ip = f.sourceIp
    if (f.userName) params.user_name = f.userName
    if (f.processName) params.process_name = f.processName
    if (f.keyword) params.keyword = f.keyword
    if (f.dateRange) { params.date_from = f.dateRange[0].toISOString(); params.date_to = f.dateRange[1].toISOString() }
    const res = await searchLogsV1(params)
    items.value = res.data?.items || []
    total.value = res.data?.total || 0
  } finally { loading.value = false }
}

async function fetchTimeline() {
  try {
    const res = await getLogTimeline({ interval: 'hour' })
    const data = res.data || []
    if (data.length === 0) {
      // 后端如果还是空，构造 24h 展示数据
      const now = new Date()
      const fake = []
      for (let i = 23; i >= 0; i--) {
        const d = new Date(now - i * 3600000)
        fake.push({
          label: String(d.getHours()).padStart(2,'0')+':00',
          critical: 0, high: 0, medium: 0, total: 0
        })
      }
      await nextTick()
      renderTimeline(fake)
    } else {
      await nextTick()
      renderTimeline(data)
    }
  } catch (e) { console.error(e) }
}

// ===== 视图切换 =====
async function switchView(key) {
  activeView.value = key
  page.value = 1
  if (key === 'overview') await search()
  else if (key === 'brute') {
    const res = await getBruteForce()
    items.value = (res.data || []).map(b => ({
      id: b.source_ip, timestamp: b.first_seen, event_label: '🔑 暴破攻击',
      event_type: 'brute_force', event_id: 4625, severity: 'high',
      hostname: '', source_ip: b.source_ip, user_name: b.target_users?.[0] || '',
      process_name: '', description: `${b.attempts} 次尝试`,
      command_line: `来源: ${b.source_ip} · ${b.attempts} 次 · ${b.first_seen} ~ ${b.last_seen}`,
    }))
    total.value = items.value.length
  } else if (key === 'threat') {
    f.severity = 'critical,high'
    await search()
    f.severity = ''
  } else {
    await search()
  }
}

// ===== Pivot =====
async function pivot(field, value) {
  if (!value) return
  if (field === 'hostname') { f.sourceIp = ''; f.userName = ''; f.keyword = value; search(); return }
  if (field === 'event_id') { f.keyword = `event_id=${value}`; search(); return }
  if (field === 'source_ip') f.sourceIp = value
  else if (field === 'user_name') f.userName = value
  else if (field === 'process_name') f.processName = value
  search()
}

function applyQuick(t) {
  Object.assign(f, t.params)
  search()
}

function resetFilters() {
  f.eventType = ''; f.severity = ''; f.sourceIp = ''; f.userName = ''; f.processName = ''; f.keyword = ''; f.dateRange = null
  search()
}

function openDetail(row) { detail.value = row; drawer.value = true }
function jumpHost(row) { if (row.host_id) router.push(`/hosts/${row.host_id}`) }
function openSession(sessionId) { if (sessionId) { f.keyword = `session:${sessionId}`; search(); drawer.value = false } }

// ===== Charts =====
const timelineRef = ref(null), pieRef = ref(null)
let timelineChart = null, pieChart = null

function renderTimeline(data) {
  if (!timelineRef.value) return
  timelineChart?.dispose()
  timelineChart = echarts.init(timelineRef.value)
  const labels = data.map(d => d.label)
  const critical = data.map(d => d.critical || 0)
  const high = data.map(d => d.high || 0)
  const medium = data.map(d => d.medium || 0)
  timelineChart.setOption({
    tooltip: { trigger: 'axis', backgroundColor: '#1a1f2e', borderColor: '#2d3548', textStyle: { color: '#e0e4ea' } },
    grid: { left: 32, right: 8, top: 6, bottom: 26 },
    xAxis: { type: 'category', data: labels, axisLabel: { color: '#6e7681', fontSize: 9 }, axisLine: { lineStyle: { color: '#242b3d' } } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#1e2433', type: 'dashed' } }, axisLabel: { color: '#6e7681', fontSize: 9 } },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, start: 0, end: 100 }],
    series: [
      { name: '严重', type: 'bar', stack: 't', data: critical, itemStyle: { color: '#f85149', borderRadius: [2,2,0,0] }, barWidth: '60%' },
      { name: '高危', type: 'bar', stack: 't', data: high, itemStyle: { color: '#d4a72c' } },
      { name: '中危', type: 'bar', stack: 't', data: medium, itemStyle: { color: '#58a6ff', borderRadius: [0,0,2,2] } },
    ]
  })
}

function renderPie() {
  if (!pieRef.value) return
  pieChart?.dispose()
  pieChart = echarts.init(pieRef.value)
  const byType = stats.value.by_type || {}
  const entries = Object.entries(byType).sort((a,b) => b[1] - a[1]).slice(0, 10)
  const colors = ['#f85149','#d4a72c','#58a6ff','#2da44e','#6e7681','#f0883e','#a371f7','#8b929a','#3d475e','#1f6feb']
  pieChart.setOption({
    tooltip: { trigger: 'item', backgroundColor: '#1a1f2e', borderColor: '#2d3548', textStyle: { color: '#e0e4ea' }, formatter: '{b}: {c} 条 ({d}%)' },
    series: [{
      type: 'pie', radius: ['45%','68%'], center: ['50%','48%'],
      itemStyle: { borderRadius: 3, borderColor: '#0f1219', borderWidth: 2 },
      label: { show: true, formatter: '{b}', fontSize: 9, color: '#c8cdd5' },
      data: entries.length ? entries.map(([k, v], i) => ({
        name: typeOptions[k] || k, value: v, itemStyle: { color: colors[i % colors.length] }
      })) : [{ name: '暂无数据', value: 1, itemStyle: { color: '#6e7681' } }],
    }]
  })
}

async function fetchAll() {
  loading.value = true
  await Promise.all([fetchStats(), search(), fetchTimeline()])
  await nextTick()
  setTimeout(() => {
    renderPie()
  }, 100)
  loading.value = false
}

onMounted(fetchAll)
onUnmounted(() => { timelineChart?.dispose(); pieChart?.dispose() })
</script>

<style scoped>
.log-page { padding: 16px 20px; min-height: calc(100vh - 100px); }
.top-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.top-bar h2 { font-size: 20px; font-weight: 600; margin: 0; }
.top-actions { display: flex; gap: 8px; }

/* KPI */
.kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; margin-bottom: 12px; }
.kpi { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; }
.k-label { font-size: 11px; color: #6b7280; }
.k-val { font-size: 22px; font-weight: 700; }
.k-val.critical { color: #dc2626; }
.k-val.high { color: #d97706; }
.k-val.blue { color: #2563eb; }

/* View tabs + charts */
.chart-section { margin-bottom: 10px; }
.view-tabs { display: flex; gap: 2px; background: #f3f4f6; border-radius: 8px; padding: 3px; width: fit-content; margin-bottom: 8px; }
.v-tab { padding: 4px 12px; border-radius: 5px; cursor: pointer; font-size: 12px; color: #6b7280; }
.v-tab.active { background: #fff; color: #1f2937; font-weight: 600; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.chart-row { display: grid; grid-template-columns: 2fr 1fr; gap: 8px; }
.chart-box { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; }
.c-head { font-size: 12px; font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
.c-badge { font-size: 10px; color: #9ca3af; font-weight: 400; }
.c-body { width: 100%; height: 100px; }

/* Filter */
.filter-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.filter-bar :deep(.el-select), .filter-bar :deep(.el-input) { margin: 0; }
.quick-tags { display: flex; flex-wrap: wrap; gap: 2px; }

/* Table */
.table-wrap { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
.pivot { color: #2563eb; cursor: pointer; font-weight: 500; }
.pivot:hover { text-decoration: underline; }
.t-time { font-size: 12px; color: #6b7280; }
.t-desc { font-size: 12px; color: #374151; line-height: 1.4; word-break: break-all; }
.t-tags { margin-top: 2px; }
.t-mitre { font-size: 10px; color: #6b7280; margin-bottom: 2px; }
.t-mitre a { color: #2563eb; text-decoration: none; }
.t-mitre a:hover { text-decoration: underline; }
.sev-text { font-size: 10px; color: #6b7280; margin-left: 2px; }
.sev-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.sev-dot.critical { background: #dc2626; }
.sev-dot.high { background: #d97706; }
.sev-dot.medium { background: #3b82f6; }
.sev-dot.low { background: #9ca3af; }
.page-foot { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; }

/* Drawer */
.d-lbl { font-size: 11px; color: #6b7280; margin-bottom: 2px; }
.d-val { font-size: 14px; color: #1f2937; }
.d-sub { font-size: 12px; color: #6b7280; margin-top: 2px; }
.d-pre { background: #f9fafb; padding: 8px; border-radius: 4px; font-size: 12px; white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow-y: auto; margin: 4px 0 0; }
.d-actions { display: flex; flex-direction: column; gap: 6px; }
</style>
