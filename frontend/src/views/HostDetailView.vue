<template>
  <div class="page-container">
    <!-- 主机信息 -->
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">主机详情</h2>
        <div>
          <el-button type="success" @click="agentDialogRef?.show()">下载 Agent</el-button>
          <el-button type="warning" @click="importDialogRef?.show()">导入 JSON</el-button>
          <el-button type="primary" :loading="analyzing" @click="handleAnalyze">分析</el-button>
          <el-button
            v-if="aiEnabled !== null"
            type="warning"
            :disabled="!aiEnabled"
            @click="handleAiAnalyze"
          >
            <el-icon><Cpu /></el-icon> AI 分析
          </el-button>
          <el-button @click="$router.push(`/hosts/${hostId}/report`)">查看报告</el-button>
          <el-button @click="$router.back()">返回</el-button>
        </div>
      </div>
      <el-descriptions :column="3" border v-loading="loading">
        <el-descriptions-item label="主机名">{{ host?.hostname }}</el-descriptions-item>
        <el-descriptions-item label="IP 地址">{{ host?.ip_address || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="系统类型">{{ host?.os_type || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="系统版本">{{ host?.os_version || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusType(host?.status)" size="small">{{ statusLabel(host?.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="风险等级">
          <RiskBadge v-if="analysis" :level="analysis.risk_level" />
          <span v-else>未分析</span>
        </el-descriptions-item>
        <el-descriptions-item label="Agent 版本">{{ host?.agent_version || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="采集时间">{{ host?.collection_time || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="风险分数">
          <span v-if="analysis">{{ analysis.risk_score }} / 100</span>
          <span v-else>N/A</span>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 分析摘要 -->
    <div v-if="analysis" class="card-box">
      <h3 class="mb-10">分析摘要</h3>
      <el-alert :type="alertType" :closable="false">
        {{ analysis.summary }}
      </el-alert>
    </div>

    <!-- Tab 页签 -->
    <div class="card-box">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="主机画像" name="profile">
          <div class="tab-toolbar">
            <span class="tab-hint">主机画像概览</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('profile')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <ProfileCard :profile="profile" />
        </el-tab-pane>
        <el-tab-pane label="进程树" name="tree">
          <div class="tab-toolbar">
            <span class="tab-hint">进程树视图</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('process_list')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <ProcessTreeView
            v-if="activeTab === 'tree'"
            :tree-data="processTree"
            :abnormal-pids="abnormalPidsForTree"
          />
        </el-tab-pane>
        <el-tab-pane label="异常进程" name="processes">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ abnormalProcesses.length }} 条异常进程</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('abnormal_processes')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <ProcessStatsCards :data="abnormalProcesses" />
          <AbnormalProcessTable
            :data="abnormalProcesses"
            @view-detail="handleViewDetail"
            style="margin-top: 16px"
          />
        </el-tab-pane>
        <el-tab-pane label="可疑外连" name="connections">
          <div class="flex-between mb-10">
            <span class="tab-hint">共 {{ suspiciousConnections.length }} 条可疑外连</span>
            <div class="flex-center" style="gap: 8px">
              <el-button
                type="warning"
                :disabled="!aiEnabled || host?.status === 'pending'"
                @click="handleModuleAiAnalyze('connections')"
              >
                🤖 AI 分析
              </el-button>
              <el-button
                type="primary"
                :loading="enriching"
                @click="handleEnrichConns"
              >
                一键威胁情报检测
              </el-button>
            </div>
          </div>
          <SuspiciousConnTable :data="suspiciousConnections" />
        </el-tab-pane>
        <el-tab-pane label="网络连接" name="network">
          <NetworkConnectionTable :host-id="Number(hostId)" :data="networkConnections" @refresh="loadAllResults" />
        </el-tab-pane>
        <el-tab-pane label="文件哈希" name="filehash">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ fileHashes.length }} 条文件哈希</span>
          </div>
          <FileHashTable :data="fileHashes" />
        </el-tab-pane>
        <el-tab-pane label="持久化痕迹" name="persistence">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ persistenceItems.length }} 条持久化痕迹</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('persistence')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <PersistenceTable :data="persistenceItems" :host-id="Number(hostId)" />
        </el-tab-pane>
        <el-tab-pane label="可疑启动项" name="startup">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ startupItems.length }} 条可疑启动项</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('startup')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <SuspiciousStartupTable :data="startupItems" />
        </el-tab-pane>
        <el-tab-pane label="IOC 命中" name="ioc">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ iocHits.length }} 条IOC命中</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('ioc')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <IocTable :data="iocHits" />
        </el-tab-pane>
        <el-tab-pane label="时间线" name="timeline">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ timelineEvents.length }} 条时间线事件</span>
            <div class="flex-center" style="gap: 8px">
              <el-button
                type="warning"
                size="small"
                :disabled="!aiEnabled || host?.status === 'pending'"
                @click="handleModuleAiAnalyze('timeline')"
              >
                🤖 AI 分析
              </el-button>
              <el-button size="small" @click="showCompare = true">对比模式</el-button>
              <el-button size="small" @click="handleExportCsv">导出 CSV</el-button>
              <el-button size="small" @click="handleExportPdf">导出 PDF</el-button>
              <el-button size="small" type="danger" @click="warRoomActive = true">作战视图</el-button>
            </div>
          </div>
          <SummaryStatsBar :host-id="hostId" :stats="timelineStats" @stats-loaded="handleTimelineStatsLoaded" />
          <TimelineFilterBar v-if="activeTab === 'timeline'" :host-id="hostId" @filter-change="handleTimelineFilter" />
          <TimelineChart
            v-if="activeTab === 'timeline'"
            :events="filteredTimelineEvents"
            :stats="timelineStats"
            :adaptive-mode="true"
            :show-sla-line="true"
          />
          <KillChainView v-if="activeTab === 'timeline'" :events="timelineEvents" />
          <EventTable
            :events="filteredTimelineEvents"
            :loading="timelineLoading"
            @row-click="handleTimelineRowClick"
          >
            <template #toolbar>
              <el-button size="small" @click="handleExportCsv">导出 CSV</el-button>
              <el-button size="small" @click="handleExportPdf">导出 PDF</el-button>
            </template>
          </EventTable>
          <EventDetailDrawer
            :event="selectedEvent"
            :visible="drawerVisible"
            :audit-logs="eventAuditLogs"
            @close="drawerVisible = false"
            @status-updated="handleEventStatusUpdate"
          />
          <!-- 对比弹窗 -->
          <el-dialog v-model="showCompare" title="多主机时间线对比" width="90%" top="5vh" destroy-on-close>
            <TimelineCompare :available-hosts="compareHosts" />
          </el-dialog>
          <!-- 作战视图模式 -->
          <WarRoomMode
            v-if="warRoomActive"
            :events="timelineEvents"
            :host-id="Number(hostId)"
            :active="warRoomActive"
            @close="warRoomActive = false"
          />
          <!-- 攻击链 DAG -->
          <AttackChainDag
            v-if="aiReportAttackChain"
            :attack-chain="aiReportAttackChain"
          />
        </el-tab-pane>
        <el-tab-pane label="用户账户" name="users">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ users.length }} 个用户账户</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('users')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <UsersTable :data="users" />
        </el-tab-pane>
        <el-tab-pane label="系统服务" name="services">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ services.length }} 个系统服务</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('services')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <ServicesTable :data="services" />
        </el-tab-pane>
        <el-tab-pane label="USB 记录" name="usb">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ usb.length }} 条USB记录</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('usb')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <UsbTable :data="usb" />
        </el-tab-pane>
        <el-tab-pane label="远程工具" name="remote_control">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ remoteControl.length }} 条远程工具记录</span>
            <el-button
              type="warning"
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('remote_control')"
            >
              🤖 AI 分析
            </el-button>
          </div>
          <RemoteControlTable :data="remoteControl" />
        </el-tab-pane>
        <el-tab-pane label="知识库" name="knowledge">
          <HostKnowledgeTab :host-id="hostId" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 进程详情面板 -->
    <ProcessDetailPanel
      :visible="detailPanelVisible"
      :process-info="selectedProcess"
      @update:visible="detailPanelVisible = $event"
    />

    <HostImportDialog ref="importDialogRef" :host-id="Number(hostId)" @success="onImportSuccess" />
    <AgentDownloadDialog ref="agentDialogRef" />
    <AiAnalysisDialog ref="aiDialogRef" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import hostsApi from '@/api/hosts'
import analysisApi from '@/api/analysis'
import RiskBadge from '@/components/RiskBadge.vue'
import ProfileCard from '@/components/ProfileCard.vue'
import AbnormalProcessTable from '@/components/AbnormalProcessTable.vue'
import SuspiciousConnTable from '@/components/SuspiciousConnTable.vue'
import NetworkConnectionTable from '@/components/NetworkConnectionTable.vue'
import FileHashTable from '@/components/FileHashTable.vue'
import PersistenceTable from '@/components/PersistenceTable.vue'
import SuspiciousStartupTable from '@/components/SuspiciousStartupTable.vue'
import IocTable from '@/components/IocTable.vue'
import TimelineChart from '@/components/TimelineChart.vue'
import SummaryStatsBar from '@/components/SummaryStatsBar.vue'
import TimelineFilterBar from '@/components/timeline/TimelineFilterBar.vue'
import EventTable from '@/components/timeline/EventTable.vue'
import EventDetailDrawer from '@/components/timeline/EventDetailDrawer.vue'
import KillChainView from '@/components/timeline/KillChainView.vue'
import TimelineCompare from '@/components/timeline/TimelineCompare.vue'
import WarRoomMode from '@/components/timeline/WarRoomMode.vue'
import AttackChainDag from '@/components/timeline/AttackChainDag.vue'
import UsersTable from '@/components/UsersTable.vue'
import ServicesTable from '@/components/ServicesTable.vue'
import UsbTable from '@/components/UsbTable.vue'
import RemoteControlTable from '@/components/RemoteControlTable.vue'
import HostImportDialog from '@/components/HostImportDialog.vue'
import AgentDownloadDialog from '@/components/AgentDownloadDialog.vue'
import AiAnalysisDialog from '@/components/AiAnalysisDialog.vue'
import ProcessTreeChart from '@/components/ProcessTreeChart.vue'
import ProcessTreeView from '@/components/ProcessTreeView.vue'
import ProcessDetailPanel from '@/components/ProcessDetailPanel.vue'
import ProcessStatsCards from '@/components/ProcessStatsCards.vue'
import HostKnowledgeTab from '@/components/HostKnowledgeTab.vue'
import { getAiConfig } from '@/api/ai'

const route = useRoute()
const hostId = route.params.id

const host = ref(null)
const analysis = ref(null)
const profile = ref(null)
const loading = ref(false)
const analyzing = ref(false)
const enriching = ref(false)
const activeTab = ref('profile')

const abnormalProcesses = ref([])
const suspiciousConnections = ref([])
const persistenceItems = ref([])
const startupItems = ref([])
const iocHits = ref([])
const timelineEvents = ref([])
const users = ref([])
const services = ref([])
const usb = ref([])
const remoteControl = ref([])
const networkConnections = ref([])
const fileHashes = ref([])
const wmiSubscriptions = ref([])
const registryKeys = ref([])

const timelineStats = ref(null)
const timelineLoading = ref(false)
const filteredTimelineEvents = ref([])
const selectedEvent = ref(null)
const drawerVisible = ref(false)
const eventAuditLogs = ref([])
const filterParams = ref({})
const showCompare = ref(false)
const warRoomActive = ref(false)

// 新增：进程树相关数据
const processTree = ref({})
const abnormalPidsForTree = ref([])
const selectedProcess = ref(null)
const detailPanelVisible = ref(false)

const importDialogRef = ref(null)
const agentDialogRef = ref(null)
const aiDialogRef = ref(null)
const aiEnabled = ref(null) // null=未加载, true=开启, false=关闭

// ── 模块 AI 分析映射 ──
const MODULE_TAB_MAP = {
  profile: 'profile',
  tree: 'process_list',
  processes: 'abnormal_processes',
  connections: 'connections',
  persistence: 'persistence',
  startup: 'startup',
  ioc: 'ioc',
  timeline: 'timeline',
  users: 'users',
  services: 'services',
  usb: 'usb',
  remote_control: 'remote_control',
}

const TAB_DATA_LABEL = {
  profile: '',
  tree: '',
  processes: '条异常进程',
  connections: '条可疑外连',
  persistence: '条持久化痕迹',
  startup: '条可疑启动项',
  ioc: '条IOC命中',
  timeline: '条时间线事件',
  users: '个用户账户',
  services: '个系统服务',
  usb: '条USB记录',
  remote_control: '条远程工具记录',
  network: '条网络连接',
  filehash: '条文件哈希',
  knowledge: '',
}

const alertType = computed(() => {
  const map = {
    critical: 'error',
    high: 'error',
    medium: 'warning',
    low: 'info',
    info: 'info'
  }
  return map[analysis.value?.risk_level] || 'info'
})

onMounted(() => {
  loadHost()
  loadAnalysis()
  loadAiStatus()
})

async function loadHost() {
  loading.value = true
  try {
    const res = await hostsApi.get(hostId)
    host.value = res.data
  } catch (error) {
    // handled
  } finally {
    loading.value = false
  }
}

async function loadAnalysis() {
  try {
    const res = await analysisApi.getAnalysis(hostId)
    analysis.value = res.data
    if (res.data) {
      loadProfile()
      loadAllResults()
    }
  } catch (error) {
    // handled
  }
}

async function loadProfile() {
  try {
    const res = await analysisApi.getProfile(hostId)
    profile.value = res.data
  } catch (error) {
    // handled
  }
}

async function loadAllResults() {
  // Phase 1: Core analysis results — all must succeed
  try {
    const [procRes, connRes, persRes, startupRes, iocRes, tlRes] = await Promise.all([
      analysisApi.getAbnormalProcesses(hostId),
      analysisApi.getSuspiciousConnections(hostId),
      analysisApi.getPersistence(hostId),
      analysisApi.getStartupItems(hostId),
      analysisApi.getIocHits(hostId),
      analysisApi.getTimeline(hostId)
    ])
    abnormalProcesses.value = procRes.data
    suspiciousConnections.value = connRes.data
    persistenceItems.value = persRes.data
    startupItems.value = startupRes.data
    iocHits.value = iocRes.data
    timelineEvents.value = tlRes.data || []
    filteredTimelineEvents.value = tlRes.data || []

    // 提取异常 PID 列表用于进程树
    abnormalPidsForTree.value = abnormalProcesses.value.map(p => p.pid)
  } catch (error) {
    // handled by axios interceptor
  }

  // Phase 2: Process tree data（请求增强字段 enrich=1，向后兼容旧组件/旧 API）
  try {
    const treeRes = await analysisApi.getProcessTree(hostId, { enrich: 1 })
    processTree.value = treeRes.data
  } catch (error) {
    processTree.value = {}
    ElMessage.error('进程树数据加载失败')
  }

  // Phase 3: Collection data tabs — tolerate 404, show empty lists on failure
  try { users.value = (await analysisApi.getUsers(hostId)).data } catch (e) { users.value = [] }
  try { services.value = (await analysisApi.getServices(hostId)).data } catch (e) { services.value = [] }
  try { usb.value = (await analysisApi.getUsb(hostId)).data } catch (e) { usb.value = [] }
  try { remoteControl.value = (await analysisApi.getRemoteControl(hostId)).data } catch (e) { remoteControl.value = [] }

  // Phase 4: New data collection tabs (P1-2, P1-3, P1-5, P1-6)
  await Promise.allSettled([
    analysisApi.getNetworkConnections(hostId).then(r => { networkConnections.value = r.data || [] }).catch(() => { networkConnections.value = [] }),
    analysisApi.getFileHashes(hostId).then(r => { fileHashes.value = r.data || [] }).catch(() => { fileHashes.value = [] }),
    analysisApi.getWmiSubscriptions(hostId).then(r => { wmiSubscriptions.value = r.data || [] }).catch(() => { wmiSubscriptions.value = [] }),
    analysisApi.getRegistryKeys(hostId).then(r => { registryKeys.value = r.data || [] }).catch(() => { registryKeys.value = [] }),
  ])

}

async function handleAnalyze() {
  if (host.value?.status === 'pending') {
    ElMessage.warning('请先导入采集数据')
    return
  }
  analyzing.value = true
  try {
    await analysisApi.analyze(hostId)
    ElMessage.success('分析完成')
    await loadHost()
    await loadAnalysis()
  } catch (error) {
    // handled
  } finally {
    analyzing.value = false
  }
}

async function reloadConnections() {
  try {
    const res = await analysisApi.getSuspiciousConnections(hostId)
    suspiciousConnections.value = res.data || []
  } catch (error) {
    // handled by axios interceptor
  }
}

async function handleEnrichConns() {
  enriching.value = true
  try {
    const res = await analysisApi.enrichSuspiciousConnections(hostId)
    const s = res.data || {}
    const parts = [`检测公网 IP ${s.public || 0} 个`]
    if (s.malicious) parts.push(`恶意 ${s.malicious}`)
    if (s.suspicious) parts.push(`可疑 ${s.suspicious}`)
    if (s.skipped_private) parts.push(`私网跳过 ${s.skipped_private}`)
    if (s.errors && s.errors.length) parts.push(`失败 ${s.errors.length}`)
    ElMessage.success('威胁情报检测完成：' + parts.join('，'))
    // 刷新列表以展示最新威胁情报标签
    await reloadConnections()
    if (activeTab.value !== 'connections') {
      activeTab.value = 'connections'
    }
  } catch (error) {
    // handled by axios interceptor
  } finally {
    enriching.value = false
  }
}

async function loadAiStatus() {
  try {
    const res = await getAiConfig()
    aiEnabled.value = res.data?.config?.enabled === 1
  } catch (error) {
    aiEnabled.value = null
  }
}

function handleAiAnalyze() {
  if (aiEnabled.value === null || aiEnabled.value === false) {
    ElMessage.warning('AI 分析功能未开启，请先在配置页面开启')
    return
  }
  if (host.value?.status === 'pending') {
    ElMessage.warning('请先导入采集数据')
    return
  }
  aiDialogRef.value?.show(Number(hostId))
}

/** 获取 tab 的数据计数 */
function getTabDataCount(tabName) {
  const map = {
    profile: null,
    tree: null,
    processes: abnormalProcesses.value?.length,
    connections: suspiciousConnections.value?.length,
    persistence: persistenceItems.value?.length,
    startup: startupItems.value?.length,
    ioc: iocHits.value?.length,
    timeline: timelineEvents.value?.length,
    users: users.value?.length,
    services: services.value?.length,
    usb: usb.value?.length,
    remote_control: remoteControl.value?.length,
    network: networkConnections.value?.length,
    filehash: fileHashes.value?.length,
  }
  return map[tabName] ?? null
}

/** 模块 AI 分析 */
function handleModuleAiAnalyze(moduleType) {
  if (aiEnabled.value === null || aiEnabled.value === false) {
    ElMessage.warning('AI 分析功能未开启，请先在配置页面开启')
    return
  }
  if (host.value?.status === 'pending') {
    ElMessage.warning('请先导入采集数据')
    return
  }
  aiDialogRef.value?.show(Number(hostId), host.value?.hostname || '', 'module', moduleType)
}

function onImportSuccess() {
  loadHost()
}

/** 异常进程表格查看详情事件（进程树改用 ProcessTreeView 内部详情面板，不再联动此处） */
function handleViewDetail(row) {
  selectedProcess.value = row
  detailPanelVisible.value = true
}

function handleTabChange(_tabName) {
  // v-if 已确保组件仅在 Tab 可见时挂载，ECharts 在 onMounted 中初始化即可获得正确容器尺寸
  // TimelineChart: echarts.init + window.resize listener
  // ProcessTreeChart: vue-echarts autoresize (ResizeObserver)
  // 无需在此处触发 window.resize
}

function handleTimelineStatsLoaded(statsData) {
  timelineStats.value = statsData
}

// ── 时间线过滤 ──
async function handleTimelineFilter(params) {
  filterParams.value = params
  timelineLoading.value = true
  try {
    const apiParams = {}
    if (params.start) apiParams.start = params.start
    if (params.end) apiParams.end = params.end
    if (params.eventTypes && params.eventTypes.length > 0) {
      apiParams.event_types = params.eventTypes.join(',')
    }
    if (params.severities && params.severities.length > 0) {
      apiParams.severity = params.severities.join(',')
    }
    const res = await analysisApi.getTimeline(hostId, apiParams)
    filteredTimelineEvents.value = res.data || []
  } catch (e) {
    filteredTimelineEvents.value = timelineEvents.value
  } finally {
    timelineLoading.value = false
  }
}

// ── 表格行点击 ──
function handleTimelineRowClick(event) {
  selectedEvent.value = event
  drawerVisible.value = true
  eventAuditLogs.value = []
}

// ── 事件状态更新 ──
async function handleEventStatusUpdate({ eventId, status, resolution }) {
  try {
    await analysisApi.updateTimelineEvent(eventId, { status, resolution, operator: 'admin' })
    ElMessage.success('状态更新成功')
    drawerVisible.value = false
    // 刷新数据
    await loadAllResults()
  } catch (e) {
    ElMessage.error('状态更新失败')
  }
}

// ── 导出 CSV ──
function handleExportCsv() {
  const params = new URLSearchParams()
  if (filterParams.value.start) params.append('start', filterParams.value.start)
  if (filterParams.value.end) params.append('end', filterParams.value.end)
  if (filterParams.value.eventTypes?.length) params.append('event_types', filterParams.value.eventTypes.join(','))
  if (filterParams.value.severities?.length) params.append('severity', filterParams.value.severities.join(','))
  const url = `${import.meta.env.VITE_API_BASE || ''}/api/analysis/timeline/${hostId}/export/csv?${params.toString()}`
  window.open(url, '_blank')
}

// ── 导出 PDF ──
async function handleExportPdf() {
  try {
    const params = new URLSearchParams()
    if (filterParams.value.start) params.append('start', filterParams.value.start)
    if (filterParams.value.end) params.append('end', filterParams.value.end)
    const url = `${import.meta.env.VITE_API_BASE || ''}/api/analysis/timeline/${hostId}/export/pdf?${params.toString()}`
    const response = await fetch(url, { headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } })
    const blob = await response.blob()
    const downloadUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = `timeline_${hostId}.pdf`
    a.click()
    URL.revokeObjectURL(downloadUrl)
  } catch (e) {
    ElMessage.error('PDF 导出失败')
  }
}

// 对比主机列表（同一 case 下的主机）
const compareHosts = computed(() => {
  if (host.value) {
    return [{ id: Number(hostId), hostname: host.value.hostname }]
  }
  return []
})

// AI 报告中的 attack_chain（用于 AttackChainDag）
const aiReportAttackChain = computed(() => {
  return null // 从 AI 分析报告中获取，T04 完善
})

function statusType(status) {
  const map = { pending: 'info', imported: 'warning', analyzed: 'success' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { pending: '待采集', imported: '已导入', analyzed: '已分析' }
  return map[status] || status
}
</script>

<style scoped>
/* ── Tab 工具栏 ── */
.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--color-canvas-subtle);
  border-radius: 6px;
  border: 1px solid var(--color-border-default);
}
.tab-hint {
  font-size: 13px;
  color: var(--color-fg-muted);
}
.flex-center {
  display: flex;
  align-items: center;
}
.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
