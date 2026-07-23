<template>
  <div class="agent-run-view">
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
            type="primary"
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
        <el-link type="primary" @click="router.push('/agent-management')" style="margin-left: 8px;">
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
            <el-tag size="small" effect="plain">{{ stageLabel(row.stage) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" min-width="120">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" size="small" effect="light">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" min-width="90">
          <template #default="{ row }">
            <el-tag :type="priorityTag(row.priority)" size="small" effect="dark">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="confidence" label="置信度" min-width="90">
          <template #default="{ row }">
            <span :class="confidenceClass(row.confidence)">{{ formatConfidence(row.confidence) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="170" show-overflow-tooltip />
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Cpu, VideoPlay, Refresh, Stamp, List, Connection } from '@element-plus/icons-vue'
import { useAgentOrchestrationStore } from '@/stores/agents'
import HitlApprovalPanel from '@/components/agents/HitlApprovalPanel.vue'

const route = useRoute()
const router = useRouter()
const store = useAgentOrchestrationStore()

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
  router.push(`/agent-orchestration/${row.run_id}`)
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

function statusTag(status) {
  return (
    {
      pending: 'info',
      running: 'primary',
      waiting_hitl: 'warning',
      completed: 'success',
      failed: 'danger',
      cancelled: 'info',
    }[status] || 'info'
  )
}

function priorityTag(priority) {
  return (
    {
      P0: 'danger',
      P1: 'warning',
      P2: 'primary',
      P3: 'info',
    }[priority] || 'info'
  )
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
  border-radius: 12px;
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
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

.conf-high {
  color: var(--color-success-fg, #16a34a);
  font-weight: 600;
}

.conf-mid {
  color: var(--color-accent-fg);
}

.conf-low {
  color: var(--color-fg-muted);
}
</style>
