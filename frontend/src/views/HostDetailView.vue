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
          <ProfileCard :profile="profile" />
        </el-tab-pane>
        <el-tab-pane label="进程树" name="tree">
          <ProcessTreeChart
            :tree-data="processTree"
            :abnormal-pids="abnormalPidsForTree"
            @node-click="handleNodeClick"
          />
        </el-tab-pane>
        <el-tab-pane label="异常进程" name="processes">
          <ProcessStatsCards :data="abnormalProcesses" />
          <AbnormalProcessTable
            :data="abnormalProcesses"
            @view-detail="handleViewDetail"
            style="margin-top: 16px"
          />
        </el-tab-pane>
        <el-tab-pane label="可疑外连" name="connections">
          <SuspiciousConnTable :data="suspiciousConnections" />
        </el-tab-pane>
        <el-tab-pane label="持久化痕迹" name="persistence">
          <PersistenceTable :data="persistenceItems" />
        </el-tab-pane>
        <el-tab-pane label="可疑启动项" name="startup">
          <SuspiciousStartupTable :data="startupItems" />
        </el-tab-pane>
        <el-tab-pane label="IOC 命中" name="ioc">
          <IocTable :data="iocHits" />
        </el-tab-pane>
        <el-tab-pane label="时间线" name="timeline">
          <TimelineChart :events="timelineEvents" />
        </el-tab-pane>
        <el-tab-pane label="用户账户" name="users">
          <UsersTable :data="users" />
        </el-tab-pane>
        <el-tab-pane label="系统服务" name="services">
          <ServicesTable :data="services" />
        </el-tab-pane>
        <el-tab-pane label="USB 记录" name="usb">
          <UsbTable :data="usb" />
        </el-tab-pane>
        <el-tab-pane label="远程工具" name="remote_control">
          <RemoteControlTable :data="remoteControl" />
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
import PersistenceTable from '@/components/PersistenceTable.vue'
import SuspiciousStartupTable from '@/components/SuspiciousStartupTable.vue'
import IocTable from '@/components/IocTable.vue'
import TimelineChart from '@/components/TimelineChart.vue'
import UsersTable from '@/components/UsersTable.vue'
import ServicesTable from '@/components/ServicesTable.vue'
import UsbTable from '@/components/UsbTable.vue'
import RemoteControlTable from '@/components/RemoteControlTable.vue'
import HostImportDialog from '@/components/HostImportDialog.vue'
import AgentDownloadDialog from '@/components/AgentDownloadDialog.vue'
import AiAnalysisDialog from '@/components/AiAnalysisDialog.vue'
import ProcessTreeChart from '@/components/ProcessTreeChart.vue'
import ProcessDetailPanel from '@/components/ProcessDetailPanel.vue'
import ProcessStatsCards from '@/components/ProcessStatsCards.vue'
import { getAiConfig } from '@/api/ai'

const route = useRoute()
const hostId = route.params.id

const host = ref(null)
const analysis = ref(null)
const profile = ref(null)
const loading = ref(false)
const analyzing = ref(false)
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

// 新增：进程树相关数据
const processTree = ref({})
const abnormalPidsForTree = ref([])
const selectedProcess = ref(null)
const detailPanelVisible = ref(false)

const importDialogRef = ref(null)
const agentDialogRef = ref(null)
const aiDialogRef = ref(null)
const aiEnabled = ref(null) // null=未加载, true=开启, false=关闭

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
    timelineEvents.value = tlRes.data

    // 提取异常 PID 列表用于进程树
    abnormalPidsForTree.value = abnormalProcesses.value.map(p => p.pid)
  } catch (error) {
    // handled by axios interceptor
  }

  // Phase 2: Process tree data
  try {
    const treeRes = await analysisApi.getProcessTree(hostId)
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

async function loadAiStatus() {
  try {
    const res = await getAiConfig()
    aiEnabled.value = res.data?.enabled === 1
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

function onImportSuccess() {
  loadHost()
}

/** 进程树节点点击事件 */
function handleNodeClick(nodeData) {
  selectedProcess.value = nodeData
  // 如果节点是异常进程，尝试从 abnormalProcesses 中获取更完整的信息
  if (nodeData.is_abnormal) {
    const matchedProc = abnormalProcesses.value.find(p => p.pid === nodeData.pid)
    if (matchedProc) {
      selectedProcess.value = matchedProc
    }
  }
  detailPanelVisible.value = true
}

/** 异常进程表格查看详情事件 */
function handleViewDetail(row) {
  selectedProcess.value = row
  detailPanelVisible.value = true
}

function handleTabChange() {
  // Tab 切换时数据已预加载
}

function statusType(status) {
  const map = { pending: 'info', imported: 'warning', analyzed: 'success' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { pending: '待采集', imported: '已导入', analyzed: '已分析' }
  return map[status] || status
}
</script>
