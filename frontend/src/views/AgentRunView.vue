<template>
  <div class="agent-run-view">
    <el-tabs v-model="activeTab" class="run-tabs">
      <!-- ===== 运行 ===== -->
      <el-tab-pane label="运行" name="run">
        <!-- 顶部 banner：将使用的默认流程 + 命中规则（P1-1） -->
        <el-card v-if="banner" class="banner-card" shadow="never" :class="`banner-${banner.type}`">
          <div class="banner-row">
            <el-icon class="banner-icon"><InfoFilled /></el-icon>
            <div class="banner-text">
              <div class="banner-title">{{ banner.title }}</div>
              <div class="banner-sub">{{ banner.sub }}</div>
            </div>
            <div class="banner-actions">
              <el-select
                v-model="defaultStore.manualPresetId"
                placeholder="手动选择其它 pipeline"
                clearable
                size="small"
                style="width: 220px"
              >
                <el-option
                  v-for="p in presets"
                  :key="p.id"
                  :label="p.name"
                  :value="p.id"
                />
              </el-select>
              <el-link class="nav-link" @click="activeTab = 'default'">查看默认规则管理</el-link>
            </div>
          </div>
        </el-card>
        <div v-else-if="eventId" class="banner-placeholder">正在解析默认流程…</div>

    <!-- ===== 顶部操作区 ===== -->
    <el-card class="toolbar-card" shadow="never">
      <div class="toolbar">
        <div class="toolbar-title">
          <el-icon :size="18"><Cpu /></el-icon>
          <span>新建智能体编排闭环</span>
        </div>
        <div class="toolbar-form">
          <el-input
            v-model="eventId"
            class="field"
            placeholder="事件 ID（单个，如 SE-1001）"
            clearable
          />
          <el-input
            v-model="eventIdsText"
            class="field field-wide"
            placeholder="批量事件 ID（逗号分隔，可选）"
            clearable
          />
          <el-input
            v-model="caseId"
            class="field field-narrow"
            placeholder="案件 ID（可选）"
            clearable
          />
          <el-button
            class="btn-dark"
            :loading="store.submitting"
            @click="onStartRun"
          >
            <el-icon><VideoPlay /></el-icon>
            启动闭环
          </el-button>
          <el-button @click="onOpenAgentMgmt">
            <el-icon><Connection /></el-icon>
            选择智能体
          </el-button>
          <el-button :loading="store.loading" @click="refreshAll">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>
      <div class="toolbar-hint">
        闭环顺序：分诊(Triage) → 调查(Investigation) → 处置(Responder，触发 HITL) → 报告(Reporter)。
        处置动作默认零自主，需管理员在 HITL 面板批准后执行。
        <el-link class="nav-link" @click="router.push('/agent-management')" style="margin-left: 8px;">
          自定义智能体组合 →
        </el-link>
      </div>
    </el-card>

    <!-- ===== HITL 待审批 ===== -->
    <el-card class="block-card" shadow="never">
      <template #header>
        <div class="block-header">
          <span><el-icon><Stamp /></el-icon> 人在回路 · 待审批处置</span>
        </div>
      </template>
      <HitlApprovalPanel @resolved="onApprovalResolved" />
    </el-card>

    <!-- ===== 运行列表 ===== -->
    <el-card class="block-card" shadow="never">
      <template #header>
        <div class="block-header">
          <span><el-icon><List /></el-icon> 编排运行记录</span>
          <div class="block-filter">
            <el-select v-model="statusFilter" placeholder="状态" clearable @change="refreshRuns" style="width: 140px">
              <el-option label="全部" value="" />
              <el-option label="等待 HITL" value="waiting_hitl" />
              <el-option label="已完成" value="completed" />
              <el-option label="运行中" value="running" />
              <el-option label="失败" value="failed" />
              <el-option label="挂起" value="pending" />
            </el-select>
            <el-select v-model="priorityFilter" placeholder="优先级" clearable @change="refreshRuns" style="width: 120px">
              <el-option label="全部" value="" />
              <el-option label="P0" value="P0" />
              <el-option label="P1" value="P1" />
              <el-option label="P2" value="P2" />
              <el-option label="P3" value="P3" />
            </el-select>
          </div>
        </div>
      </template>

      <el-table
        :data="store.runs"
        v-loading="store.loading"
        empty-text="暂无运行记录"
        @row-click="onRowClick"
        class="runs-table"
      >
        <el-table-column prop="run_id" label="Run ID" min-width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.run_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="event_id" label="事件 ID" min-width="120" show-overflow-tooltip />
        <el-table-column prop="stage" label="阶段" min-width="110">
          <template #default="{ row }">
            <span class="stage-cell">{{ stageLabel(row.stage) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" min-width="120">
          <template #default="{ row }">
            <span class="run-status">
              <span class="rs-dot" :class="`rs-${row.status}`" />
              {{ statusLabel(row.status) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" min-width="90">
          <template #default="{ row }">
            <span class="priority-cell mono">{{ row.priority || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="confidence" label="置信度" min-width="90">
          <template #default="{ row }">
            <span :class="confidenceClass(row.confidence)">{{ formatConfidence(row.confidence) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="time-cell">{{ relativeTime(row.created_at) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          background
          layout="prev, pager, next, total"
          :total="store.total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </el-card>
      </el-tab-pane>

      <!-- ===== 默认流程 ===== -->
      <el-tab-pane label="默认流程" name="default">
        <DefaultPipelineManagePanel />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Cpu, VideoPlay, Refresh, Stamp, List, Connection, InfoFilled } from '@element-plus/icons-vue'
import { useAgentOrchestrationStore } from '@/stores/agents'
import { useDefaultPipelineStore } from '@/stores/defaultPipeline'
import HitlApprovalPanel from '@/components/agents/HitlApprovalPanel.vue'
import DefaultPipelineManagePanel from '@/components/agents/DefaultPipelineManagePanel.vue'
import agentApi from '@/api/agent'

const route = useRoute()
const router = useRouter()
const store = useAgentOrchestrationStore()
const defaultStore = useDefaultPipelineStore()

// 预置模板列表：供手动覆盖选择（P1-3）
const presets = ref([])
// 当前页签：运行 / 默认流程（P1-1，同一页内切换，无子路由）
const activeTab = ref('run')

// ===== 顶部 banner：将使用的默认流程（来自 resolve 预览，P1-1） =====
const banner = computed(() => {
  const p = defaultStore.resolvePreview
  if (!p) return null
  const matchLabel = {
    scene: '场景规则匹配',
    global: '全局默认',
    hardcoded: '内置默认（未配置规则）',
  }[p.match_type] || p.match_type || '未知'
  return {
    type: p.match_type === 'hardcoded' ? 'warning' : 'success',
    title: p.preset_name
      ? `将使用的默认流程：${p.preset_name}`
      : '将使用内置默认流程（分诊→调查→处置→报告）',
    sub:
      `匹配方式：${matchLabel}` +
      (p.rule_id ? `（规则 #${p.rule_id}）` : '') +
      (p.preset_name ? ` · 智能体：${(p.agent_names || []).join(' → ')}` : ''),
  }
})

// ===== 新建表单 =====
const eventId = ref('')
const eventIdsText = ref('')
const caseId = ref('')

// ===== 列表过滤 / 分页 =====
const statusFilter = ref('')
const priorityFilter = ref('')
const page = ref(1)
const pageSize = ref(20)

// ===== 生命周期 =====
onMounted(() => {
  // 从 URL 查询参数自动填充事件 ID 和案件 ID（来自分析中心跳转）
  if (route.query.eventId) {
    eventId.value = route.query.eventId
  }
  if (route.query.caseId) {
    caseId.value = String(route.query.caseId)
  }
  // 预置模板列表：供手动覆盖选择（P1-3）
  loadPresets()
  // 携带 eventId 进入时，解析默认流程以展示 banner（P1-1）
  if (eventId.value) {
    defaultStore.resolve(eventId.value)
  }
  refreshAll()
  // 若通过 HITL 面板跳转带 runId，自动跳转详情页
  const q = route.query.runId
  if (q) {
    router.push(`/agent-orchestration/${q}`)
  }
})

watch(
  () => route.query.runId,
  (q) => {
    if (q) {
      router.push(`/agent-orchestration/${q}`)
    }
  }
)

// 事件 ID 变化时，重新解析默认流程预览（清空则重置 banner 与手动覆盖，P1-1/P1-3）
watch(eventId, (val) => {
  if (val && val.trim()) {
    defaultStore.resolve(val.trim())
  } else {
    defaultStore.resolvePreview = null
    defaultStore.setManualPreset(null)
  }
})

// ===== 动作 =====
async function refreshRuns() {
  await store.fetchRuns({
    status: statusFilter.value || undefined,
    priority: priorityFilter.value || undefined,
    page: page.value,
    page_size: pageSize.value,
  })
}

async function refreshAll() {
  await refreshRuns()
}

/** 拉取预置模板列表，供运行页「手动覆盖选择」使用（P1-3）。 */
async function loadPresets() {
  try {
    const res = await agentApi.pipeline.getPresets()
    const data = res?.data ?? res
    presets.value = Array.isArray(data) ? data : data?.presets ?? []
  } catch (e) {
    presets.value = []
  }
}

async function onStartRun() {
  const payload = {}
  if (eventId.value.trim()) payload.event_id = eventId.value.trim()
  const ids = eventIdsText.value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  if (ids.length) payload.event_ids = ids
  if (caseId.value.trim()) {
    const n = Number(caseId.value.trim())
    if (!Number.isNaN(n)) payload.case_id = n
  }
  // P1-3：手动覆盖的 pipeline（清空 manualPresetId 则回退默认匹配）
  if (defaultStore.manualPresetId) {
    payload.preset_id = defaultStore.manualPresetId
  }
  if (!payload.event_id && !payload.event_ids?.length) {
    ElMessage.warning('请至少填写事件 ID 或批量事件 ID')
    return
  }
  try {
    const outcome = await store.startRun(payload)
    ElMessage.success(`已启动闭环：${outcome?.run_id || ''}（${statusLabel(outcome?.status)}）`)
    eventId.value = ''
    eventIdsText.value = ''
    caseId.value = ''
    await refreshRuns()
    // 若立即进入 waiting_hitl，提示去审批
    if (outcome?.status === 'waiting_hitl') {
      ElMessage.info('处置阶段已触发 HITL，请管理员在上方「待审批处置」面板决议')
    }
  } catch (e) {
    // 错误已由 axios 拦截器提示
  }
}

function onOpenAgentMgmt() {
  router.push('/agent-management')
}

function onRowClick(row) {
  router.push(`/agent-orchestration/runs/${row.run_id}`)
}

function onPageChange(p) {
  page.value = p
  refreshRuns()
}

function onApprovalResolved() {
  // 审批后刷新列表
  refreshRuns()
  if (store.currentRun?.run?.run_id) {
    store.fetchRunDetail(store.currentRun.run.run_id)
  }
}

// ===== 展示辅助 =====
function stageLabel(stage) {
  return (
    {
      triage: '分诊',
      investigation: '调查',
      response: '处置',
      report: '报告',
    }[stage] || stage || '-'
  )
}

function statusLabel(status) {
  return (
    {
      pending: '挂起',
      running: '运行中',
      waiting_hitl: '等待 HITL',
      completed: '已完成',
      failed: '失败',
      cancelled: '已取消',
    }[status] || status || '-'
  )
}

/** 相对时间：刚刚 / X 分钟前 / X 小时前 / X 天前 */
function relativeTime(iso) {
  if (!iso) return '—'
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return iso
  const diffMs = Date.now() - t.getTime()
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return '刚刚'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  return `${day} 天前`
}

function formatConfidence(v) {
  const n = Number(v)
  if (Number.isNaN(n)) return '-'
  return `${Math.round(n * 100)}%`
}

function confidenceClass(v) {
  const n = Number(v)
  if (Number.isNaN(n)) return ''
  if (n >= 0.7) return 'conf-high'
  if (n >= 0.4) return 'conf-mid'
  return 'conf-low'
}
</script>

<style scoped>
.agent-run-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}

.toolbar-card,
.block-card {
  border-radius: 10px;
  border: 1px solid var(--color-border-default);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.toolbar-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.toolbar-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex: 1;
}

.field {
  width: 200px;
}

.field-wide {
  width: 260px;
}

.field-narrow {
  width: 140px;
}

.toolbar-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--color-fg-muted);
  line-height: 1.6;
}

.block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.block-header .el-icon {
  margin-right: 6px;
  vertical-align: -2px;
}

.block-filter {
  display: flex;
  gap: 8px;
}

.runs-table {
  cursor: pointer;
  border-radius: 10px;
  --el-table-border-color: var(--color-border-default);
  --el-table-header-bg-color: var(--color-canvas-subtle);
  --el-table-header-text-color: #6b7280;
  --el-table-row-hover-bg-color: var(--color-canvas-subtle);
}
.runs-table :deep(th.el-table__cell) {
  font-size: 12px;
  font-weight: 500;
  padding: 8px 10px;
  height: 36px;
}
.runs-table :deep(td.el-table__cell) {
  padding: 8px 10px;
  font-size: 12px;
  color: var(--color-fg-default);
  height: 38px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

/* 状态：单色圆点 + 文字（成功绿 / 运行中灰 / 失败红克制 / 其余灰） */
.run-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-fg-default);
}
.rs-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.rs-completed { background: #16a34a; }
.rs-running { background: #4b5563; }
.rs-failed { background: #dc2626; }
.rs-waiting_hitl { background: #d97706; }
.rs-pending, .rs-cancelled, .rs-expired { background: #9ca3af; }

/* 阶段：中性灰字，去 tag */
.stage-cell {
  font-size: 12px;
  color: var(--color-fg-muted);
}

/* 优先级：近黑等宽，去彩色 tag */
.priority-cell {
  font-size: 12px;
  color: #111827;
  font-weight: 500;
}

.time-cell {
  font-size: 12px;
  color: var(--color-fg-subtle);
}

.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.conf-high {
  color: #16a34a;
  font-weight: 600;
}

.conf-mid {
  color: #4b5563;
}

.conf-low {
  color: var(--color-fg-muted);
}

/* 主按钮：黑底白字，hover 近黑加深 */
.btn-dark {
  --el-button-bg-color: #111827;
  --el-button-border-color: #111827;
  --el-button-text-color: #fff;
  --el-button-hover-bg-color: #1f2937;
  --el-button-hover-border-color: #1f2937;
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: #1f2937;
  --el-button-active-border-color: #1f2937;
  --el-button-active-text-color: #fff;
}

/* 链接：近黑，hover 加深，去蓝色 */
.nav-link {
  --el-link-text-color: #111827;
  --el-link-hover-text-color: #4b5563;
  font-size: 12px;
}

/* ===== 默认流程 banner（P1-1） ===== */
.run-tabs {
  width: 100%;
}

.banner-card {
  border-radius: 10px;
}

.banner-card.banner-success {
  background: var(--color-success-subtle, #ecfdf5);
  border-color: var(--color-success-emphasis, #6ee7b7);
}

.banner-card.banner-warning {
  background: var(--color-attention-subtle, #fffbeb);
  border-color: var(--color-attention-emphasis, #fcd34d);
}

.banner-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.banner-icon {
  font-size: 20px;
  color: #111827;
}

.banner-text {
  flex: 1;
  min-width: 220px;
}

.banner-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.banner-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--color-fg-muted);
  line-height: 1.5;
}

.banner-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.banner-placeholder {
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--color-canvas-subtle, #f6f8fa);
  color: var(--color-fg-muted);
  font-size: 13px;
}
</style>
