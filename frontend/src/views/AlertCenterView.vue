<template>
  <div class="alert-center">
    <div class="page-header">
      <h2>🚨 实时告警</h2>
      <div class="header-actions">
        <el-button size="small" @click="fetchData" :loading="loading">↻ 刷新</el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="12" class="stats-row">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card critical">
          <div class="stat-label">待处理告警</div>
          <div class="stat-value">{{ stats.open }}</div>
          <div class="stat-sub">严重 <strong style="color:#cf222e;">{{ stats.critical }}</strong> 条</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card high">
          <div class="stat-label">今日新增</div>
          <div class="stat-value">{{ stats.today }}</div>
          <div class="stat-sub">近 1h <strong id="hourlyNew">-</strong> 条</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card medium">
          <div class="stat-label">告警总数</div>
          <div class="stat-value">{{ stats.total }}</div>
          <div class="stat-sub">已处理 <strong>{{ stats.total - stats.open }}</strong> 条</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card low">
          <div class="stat-label">主机在线</div>
          <div class="stat-value">{{ onlineCount }}</div>
          <div class="stat-sub">总计 {{ totalHosts }} 台</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 筛选工具栏 -->
    <el-card shadow="never" class="filter-bar">
      <div class="filter-row">
        <el-select v-model="filterSeverity" placeholder="严重度" clearable size="small" style="width:100px" @change="fetchData">
          <el-option label="严重" value="critical" />
          <el-option label="高危" value="high" />
          <el-option label="中危" value="medium" />
          <el-option label="低危" value="low" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="状态" clearable size="small" style="width:100px" @change="fetchData">
          <el-option label="未处理" value="open" />
          <el-option label="已确认" value="acknowledged" />
          <el-option label="已解决" value="resolved" />
          <el-option label="已忽略" value="dismissed" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          size="small"
          style="width:260px"
          :shortcuts="dateShortcuts"
          @change="fetchData"
        />
        <el-cascader
          v-model="caseHostValue"
          :options="caseHostOptions"
          :props="{ expandTrigger: 'hover', label: 'label', value: 'value', children: 'children' }"
          placeholder="案件 → 主机"
          clearable
          size="small"
          style="width:200px"
          @change="onCaseHostChange"
        />
        <el-input
          v-model="searchKeyword"
          placeholder="搜索告警标题/详情/进程"
          size="small"
          style="width:180px"
          clearable
          @keyup.enter="fetchData"
          @clear="fetchData"
        />
        <el-button size="small" type="primary" @click="fetchData">搜索</el-button>
        <el-button size="small" @click="resetAllFilters" :disabled="!hasAnyFilter">重置</el-button>
        <div style="flex:1" />
        <el-button size="small" type="primary" plain @click="batchAck" :disabled="selected.length === 0">✅ 批量确认</el-button>
        <el-button size="small" type="success" plain @click="batchResolve" :disabled="selected.length === 0">✅ 批量解决</el-button>
      </div>
      <!-- 已选条件标签 -->
      <div v-if="hasAnyFilter" class="filter-tags">
        <el-tag v-if="filterSeverity" closable size="small" @close="filterSeverity='';fetchData()">
          严重度: {{ sevLabel(filterSeverity) }}
        </el-tag>
        <el-tag v-if="filterStatus" closable size="small" @close="filterStatus='';fetchData()">
          状态: {{ statusLabel(filterStatus) }}
        </el-tag>
        <el-tag v-if="dateRange" closable size="small" @close="dateRange=null;fetchData()">
          日期: {{ formatDateRange(dateRange) }}
        </el-tag>
        <el-tag v-if="caseHostLabel" closable size="small" @close="caseHostValue=[];caseHostLabel='';fetchData()">
          范围: {{ caseHostLabel }}
        </el-tag>
        <el-tag v-if="searchKeyword" closable size="small" @close="searchKeyword='';fetchData()">
          搜索: {{ searchKeyword }}
        </el-tag>
        <el-button size="small" text type="primary" @click="resetAllFilters">清除全部</el-button>
      </div>
    </el-card>

    <!-- 告警表格 -->
    <el-table :data="alerts" v-loading="loading" stripe border
              @selection-change="onSelectionChange" style="margin-top:12px;">
      <el-table-column type="selection" width="40" />
      <el-table-column label="严重度" width="80">
        <template #default="{ row }">
          <el-tag :type="sevType(row.severity)" size="small" effect="plain">
            {{ sevLabel(row.severity) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="告警内容" min-width="200">
        <template #default="{ row }">
          <div class="alert-title">{{ row.title }}</div>
          <div class="alert-detail">{{ row.detail || '' }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="source_process" label="进程" width="100" />
      <el-table-column prop="rule_name" label="规则" width="140" />
      <el-table-column prop="count" label="次数" width="60" align="center" />
      <el-table-column label="时间" width="160">
        <template #default="{ row }">
          <span style="font-size:12px;color:#6b7280;">{{ formatTime(row.last_seen_at || row.first_seen_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="viewDetail(row)">详情</el-button>
          <el-button v-if="row.status==='open'" link type="warning" size="small" @click="handleAck(row)">确认</el-button>
          <el-button v-if="row.status!=='resolved'" link type="success" size="small" @click="handleResolve(row)">解决</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div style="display:flex;justify-content:center;margin-top:16px;">
      <el-pagination v-model:current-page="page" :page-size="100" :total="stats.total"
                     layout="prev, pager, next, total" background small />
    </div>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="'🔍 ' + (detailAlert?.title || '告警详情')" size="480px">
      <template v-if="detailAlert">
        <div class="detail-section">
          <div class="d-label">严重度</div>
          <el-tag :type="sevType(detailAlert.severity)" effect="dark">{{ sevLabel(detailAlert.severity) }}</el-tag>
        </div>
        <el-divider />
        <div class="detail-section">
          <div class="d-label">告警描述</div>
          <div class="d-value">{{ detailAlert.title }}</div>
          <div class="d-detail">{{ detailAlert.detail || '无详细信息' }}</div>
        </div>
        <el-divider />
        <div class="detail-section">
          <div class="d-label">触发进程</div>
          <div class="d-value">{{ detailAlert.source_process || 'N/A' }}</div>
          <div class="d-detail">PID: {{ detailAlert.source_pid || 'N/A' }}</div>
        </div>
        <el-divider />
        <div class="detail-section">
          <div class="d-label">命中规则</div>
          <div class="d-value">{{ detailAlert.rule_name }}</div>
        </div>
        <el-divider />
        <div class="detail-section">
          <div class="d-label">时间信息</div>
          <div class="d-detail">首次: {{ detailAlert.first_seen_at }}</div>
          <div class="d-detail">最近: {{ detailAlert.last_seen_at }}</div>
          <div class="d-detail">聚合次数: {{ detailAlert.count }}</div>
        </div>
        <el-divider />
        <div class="detail-section">
          <div class="d-label">状态</div>
          <el-tag :type="statusType(detailAlert.status)" size="small">{{ statusLabel(detailAlert.status) }}</el-tag>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getAlerts, getAlertStats, acknowledgeAlert, resolveAlert, dismissAlert
} from '@/api/alerts'
import { getHostsStatus, getCasesWithHosts } from '@/api/alerts'

const alerts = ref([])
const stats = ref({ total: 0, open: 0, critical: 0, today: 0 })
const loading = ref(false)
const page = ref(1)
const selected = ref([])
const drawerVisible = ref(false)
const detailAlert = ref(null)
const onlineCount = ref(0)
const totalHosts = ref(0)

const filterSeverity = ref('')
const filterStatus = ref('')
const filterHost = ref('')
const hostOptions = ref([])
const dateRange = ref(null)
const caseHostValue = ref([])
const caseHostLabel = ref('')
const caseHostOptions = ref([])
const searchKeyword = ref('')

const dateShortcuts = [
  { text: '最近 1 小时', value: () => [new Date(Date.now() - 3600000), new Date()] },
  { text: '最近 24 小时', value: () => [new Date(Date.now() - 86400000), new Date()] },
  { text: '最近 7 天', value: () => [new Date(Date.now() - 604800000), new Date()] },
  { text: '最近 30 天', value: () => [new Date(Date.now() - 2592000000), new Date()] },
  { text: '今天', value: () => { const d = new Date(); d.setHours(0,0,0,0); return [d, new Date()] } },
]

const hasAnyFilter = computed(() =>
  filterSeverity.value || filterStatus.value || dateRange.value ||
  caseHostValue.value.length > 0 || searchKeyword.value
)

function formatDateRange(range) {
  if (!range) return ''
  const d1 = range[0], d2 = range[1]
  const fmt = (d) => `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`
  return `${fmt(d1)} - ${fmt(d2)}`
}

function resetAllFilters() {
  filterSeverity.value = ''
  filterStatus.value = ''
  dateRange.value = null
  caseHostValue.value = []
  caseHostLabel.value = ''
  searchKeyword.value = ''
  fetchData()
}

function onCaseHostChange(val) {
  if (val.length === 0) {
    caseHostLabel.value = ''
    filterHost.value = ''
  } else if (val.length === 1) {
    caseHostLabel.value = `案件 #${val[0]}`
    filterHost.value = ''
  } else if (val.length === 2) {
    caseHostLabel.value = `主机 #${val[1]}`
    filterHost.value = val[1]
  }
  fetchData()
}

function sevType(s) {
  return { critical: 'danger', high: 'warning', medium: 'primary', low: 'info' }[s] || 'info'
}
function sevLabel(s) {
  return { critical: '严重', high: '高危', medium: '中危', low: '低危' }[s] || s
}
function statusType(s) {
  return { open: 'danger', acknowledged: 'warning', resolved: 'success', dismissed: 'info' }[s] || 'info'
}
function statusLabel(s) {
  return { open: '未处理', acknowledged: '已确认', resolved: '已解决', dismissed: '已忽略' }[s] || s
}
function formatTime(iso) {
  if (!iso) return ''
  // SQLite datetime('now') 存储 UTC，加上 Z 标识避免浏览器按本地时区解析
  const utc = iso.includes('T') ? iso : iso.replace(' ', 'T')
  const d = new Date(utc.endsWith('Z') ? utc : utc + 'Z')
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前'
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前'
  // 超过 24 小时显示具体日期时间（已转本地时区）
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function fetchData() {
  loading.value = true
  try {
    const params = { limit: 100 }
    if (filterSeverity.value) params.severity = filterSeverity.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterHost.value) params.host_id = filterHost.value
    if (dateRange.value) {
      params.date_from = dateRange.value[0].toISOString()
      params.date_to = dateRange.value[1].toISOString()
    }
    if (caseHostValue.value.length === 1) {
      params.case_id = caseHostValue.value[0]
    } else if (caseHostValue.value.length === 2) {
      params.host_id = caseHostValue.value[1]
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    const res = await getAlerts(params)
    alerts.value = res.data || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const params = {}
    if (filterSeverity.value) params.severity = filterSeverity.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterHost.value) params.host_id = filterHost.value
    if (dateRange.value) {
      params.date_from = dateRange.value[0].toISOString()
      params.date_to = dateRange.value[1].toISOString()
    }
    if (caseHostValue.value.length === 1) {
      params.case_id = caseHostValue.value[0]
    } else if (caseHostValue.value.length === 2) {
      params.host_id = caseHostValue.value[1]
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    const res = await getAlertStats(params)
    stats.value = res.data || {}
  } catch (e) { console.error(e) }
}

async function fetchHosts() {
  try {
    const [res1, res2] = await Promise.all([
      getHostsStatus(),
      getCasesWithHosts(),
    ])
    const hosts = res1.data || []
    onlineCount.value = hosts.filter(h => h.status === 'online').length
    totalHosts.value = hosts.length
    caseHostOptions.value = res2.data || []
  } catch (e) { console.error(e) }
}

function onSelectionChange(rows) {
  selected.value = rows
}

async function handleAck(row) {
  const ok = await acknowledgeAlert(row.id)
  if (ok) { row.status = 'acknowledged'; ElMessage.success('已确认') }
}
async function handleResolve(row) {
  const ok = await resolveAlert(row.id)
  if (ok) { row.status = 'resolved'; ElMessage.success('已解决') }
}
async function batchAck() {
  for (const row of selected.value) {
    if (row.status === 'open') await acknowledgeAlert(row.id)
  }
  ElMessage.success(`已确认 ${selected.value.length} 条`)
  fetchData()
}
async function batchResolve() {
  for (const row of selected.value) {
    if (row.status !== 'resolved') await resolveAlert(row.id)
  }
  ElMessage.success(`已解决 ${selected.value.length} 条`)
  fetchData()
}

function viewDetail(row) {
  detailAlert.value = row
  drawerVisible.value = true
}

let ws = null
function connectWebSocket() {
  const token = localStorage.getItem('ir_token')
  if (!token) return
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${proto}//${location.host}/api/ws/alerts?token=${token}`)
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'new_alert') {
        alerts.value.unshift(data.alert)
        stats.value.open++
        stats.value.total++
        if (data.alert.severity === 'critical') stats.value.critical++
        ElMessage({
          message: `🔴 [${sevLabel(data.alert.severity)}] ${data.alert.title}`,
          type: data.alert.severity === 'critical' ? 'error' : 'warning',
          duration: 4000,
        })
      }
    } catch (e) { console.error('WS message error:', e) }
  }
  ws.onclose = () => { setTimeout(connectWebSocket, 5000) }
}

onMounted(() => {
  fetchData()
  fetchStats()
  fetchHosts()
  connectWebSocket()
})

onUnmounted(() => {
  if (ws) ws.close()
})
</script>

<style scoped>
.alert-center { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { font-size: 20px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; }

.stats-row { margin-bottom: 16px; }
.stat-card { border-left: 3px solid #9ca3af; }
.stat-card.critical { border-left-color: #cf222e; }
.stat-card.high { border-left-color: #d4a72c; }
.stat-card.medium { border-left-color: #0969da; }
.stat-card.low { border-left-color: #656d76; }
.stat-label { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
.stat-value { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; }
.stat-sub { font-size: 11px; color: #9ca3af; margin-top: 4px; }

.filter-bar { margin-bottom: 0; }
.filter-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.filter-tags { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 8px; padding-top: 8px; border-top: 1px solid #f3f4f6; }

.alert-title { font-weight: 500; color: #1f2937; }
.alert-detail { font-size: 11px; color: #9ca3af; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 300px; }

.detail-section { margin-bottom: 8px; }
.d-label { font-size: 11px; color: #9ca3af; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.3px; }
.d-value { font-size: 14px; color: #1f2937; }
.d-detail { font-size: 12px; color: #6b7280; margin-top: 4px; line-height: 1.6; }
</style>
