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
          <el-button :loading="store.loading" @click="refreshAll">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>
      <div class="toolbar-hint">
        闭环顺序：分诊(Triage) → 调查(Investigation) → 处置(Responder，触发 HITL) → 报告(Reporter)。
        处置动作默认零自主，需管理员在 HITL 面板批准后执行。
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

    <!-- ===== 运行详情抽屉 ===== -->
    <el-drawer
      v-model="detailVisible"
      :title="detailTitle"
      size="52%"
      direction="rtl"
    >
      <div v-if="currentRun" class="detail">
        <el-descriptions :column="2" border size="small" class="detail-meta">
          <el-descriptions-item label="Run ID">
            <span class="mono">{{ currentRun.run?.run_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(currentRun.run?.status)" size="small" effect="light">
              {{ statusLabel(currentRun.run?.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="优先级">
            <el-tag :type="priorityTag(currentRun.run?.priority)" size="small" effect="dark">
              {{ currentRun.run?.priority }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="置信度">
            {{ formatConfidence(currentRun.run?.confidence) }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="detail-steps-title">
          <el-icon><Connection /></el-icon> 阶段步骤（证据可溯源）
        </div>

        <div class="steps">
          <div
            v-for="(step, idx) in currentRun.steps"
            :key="step.id || idx"
            class="step"
          >
            <div class="step-head">
              <span class="step-index">{{ idx + 1 }}</span>
              <span class="step-agent">{{ step.agent }}</span>
              <el-tag size="small" effect="plain" class="step-stage">{{ stageLabel(step.stage) }}</el-tag>
              <el-tag :type="step.status === 'success' ? 'success' : 'danger'" size="small" effect="light">
                {{ step.status === 'success' ? '成功' : '失败' }}
              </el-tag>
              <span class="step-confidence">置信度 {{ formatConfidence(step.confidence) }}</span>
            </div>

            <pre class="step-output">{{ stepOutput(step) }}</pre>

            <div v-if="stepEvidence(step).length" class="step-evidence">
              <div class="evidence-label">证据 evidence</div>
              <el-tag
                v-for="(ev, ei) in stepEvidence(step)"
                :key="ei"
                size="small"
                effect="light"
                class="evidence-tag"
              >
                {{ ev.type }}: {{ ev.ref }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>
      <el-empty v-else description="加载中…" />
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Cpu, VideoPlay, Refresh, Stamp, List, Connection } from '@element-plus/icons-vue'
import { useAgentOrchestrationStore } from '@/stores/agents'
import HitlApprovalPanel from '@/components/agents/HitlApprovalPanel.vue'

const route = useRoute()
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

// ===== 详情抽屉 =====
const detailVisible = ref(false)
const currentRun = computed(() => store.currentRun)

const detailTitle = computed(() => {
  const r = currentRun.value?.run
  return r ? `运行详情 · ${r.run_id}` : '运行详情'
})

// ===== 生命周期 =====
onMounted(() => {
  refreshAll()
  // 若通过 HITL 面板跳转带 runId，自动打开详情
  const q = route.query.runId
  if (q) {
    store.fetchRunDetail(q)
    detailVisible.value = true
  }
})

watch(
  () => route.query.runId,
  (q) => {
    if (q) {
      store.fetchRunDetail(q)
      detailVisible.value = true
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

function onRowClick(row) {
  store.fetchRunDetail(row.run_id)
  detailVisible.value = true
}

function onPageChange(p) {
  page.value = p
  refreshRuns()
}

function onApprovalResolved() {
  // 审批后刷新列表与详情
  refreshRuns()
  if (currentRun.value?.run?.run_id) {
    store.fetchRunDetail(currentRun.value.run.run_id)
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

function stepOutput(step) {
  try {
    const out = typeof step.output_json === 'string' ? JSON.parse(step.output_json) : step.output_json
    return out?.output || step.output_json || ''
  } catch {
    return step.output_json || ''
  }
}

function stepEvidence(step) {
  try {
    const ev = typeof step.evidence_json === 'string' ? JSON.parse(step.evidence_json) : step.evidence_json
    return Array.isArray(ev) ? ev : []
  } catch {
    return []
  }
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

.detail-meta {
  margin-bottom: 16px;
}

.detail-steps-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-fg-default);
  margin-bottom: 10px;
}

.steps {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step {
  border: 1px solid var(--color-border-default);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--color-canvas-subtle);
}

.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-accent-fg);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}

.step-agent {
  font-weight: 600;
  color: var(--color-fg-default);
  font-size: 13px;
}

.step-confidence {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-fg-muted);
}

.step-output {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-fg-default);
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 0;
  max-height: 320px;
  overflow: auto;
}

.step-evidence {
  margin-top: 8px;
}

.evidence-label {
  font-size: 12px;
  color: var(--color-fg-muted);
  margin-bottom: 6px;
}

.evidence-tag {
  margin: 0 6px 6px 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
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
