<template>
  <div class="event-detail-view">
    <!-- 加载状态 -->
    <div class="edv-body" v-if="loading">
      <div class="edv-loading">加载中…</div>
    </div>

    <!-- 错误状态 -->
    <div class="edv-body" v-else-if="error">
      <div class="edv-error">加载失败: {{ error }}</div>
    </div>

    <!-- 正常内容 -->
    <template v-else-if="eventData">
      <TopNavigation
        :event="eventData"
        :case-info="caseInfo"
        @back="goBack"
        @view-case="goToCase"
      >
        <template #actions>
          <button
            class="edv-copy-raw-id"
            :class="{ 'is-disabled': !isRawEventId }"
            type="button"
            :title="isRawEventId ? '复制 32 位原始事件ID（用于分诊/触发器调试）' : '当前事件非安全事件源，无原始 event_id'"
            @click="copyRawEventId"
          >
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
              <rect x="3.5" y="3.5" width="7" height="7" rx="1.3" stroke="currentColor" stroke-width="1.3" />
              <path d="M5.5 3.5V2.5a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-1" stroke="currentColor" stroke-width="1.3" />
            </svg>
            复制原始事件ID
          </button>
        </template>
      </TopNavigation>
      <DecisionBar
        :event="eventData"
        :risk-score="riskScore"
        @update-status="handleUpdateStatus"
        @deep-investigation="handleDeepInvestigation"
      />
      <ThreeColumnLayout>
        <template #left>
          <AttackChainTimeline
            :timeline-events="store.timelineEvents"
            :current-event-id="eventId"
            :current-stage="eventData.attack_stage"
            :loading="store.timelineLoading"
            :error="store.timelineError"
            @select-event="handleSelectEvent"
            @toggle-stage="handleToggleStage"
            @retry="handleTimelineRetry"
          />
        </template>
        <template #center>
          <EventSummaryCard
            :event="eventData"
            :frequency="eventData.frequency"
            @filter-by-host="handleFilterByHost"
          />
          <MatchedRulesList
            :rules="matchedRules"
          />
          <!-- 进程链 -->
          <ProcessTree
            :tree="store.processTree"
            :current-pid="store.currentProcessPid"
            :loading="store.processTreeLoading"
          />
          <EvidenceViewer
            :evidence-views="evidenceViews"
            :event-type="eventData.event_type"
            :process-subject="processSubject"
            :network-subject="networkSubject"
            :persistence-target="persistenceTarget"
          />
          <!-- 关联事件 -->
          <RelatedEventsList
            :related-ids="store.relatedEvents"
            @view-event="handleViewRelatedEvent"
          />
        </template>
        <template #right>
          <AiVerdictPanel
            :ai-verdict="aiVerdict"
            :ai-analysis="eventData.ai_analysis || ''"
          />
          <IocIndicators
            :iocs="eventData.iocs || {}"
          />
          <!-- P1: 关联告警 -->
          <RelatedAlerts
            v-if="relatedAlerts && relatedAlerts.length"
            :alerts="relatedAlerts"
          />
          <RemediationSuggestions
            :severity="eventData.severity"
          />
          <HostOverview
            :host-stats="store.hostStats"
            :hostname="eventData.hostname || ''"
          />
          <DispositionPanel
            :dispositions="store.dispositions"
            :event-id="eventId"
            @add-disposition="handleAddDisposition"
          />
        </template>
      </ThreeColumnLayout>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAnalysisStore } from '@/stores/analysis'
import { getEventDetail, getEventDisplay as fetchDisplayApi } from '@/api/events'

// 子组件
import ThreeColumnLayout from '@/components/analysis/ThreeColumnLayout.vue'
import TopNavigation from '@/components/analysis/TopNavigation.vue'
import DecisionBar from '@/components/analysis/DecisionBar.vue'
import AttackChainTimeline from '@/components/analysis/AttackChainTimeline.vue'
import EventSummaryCard from '@/components/analysis/EventSummaryCard.vue'
import MatchedRulesList from '@/components/analysis/MatchedRulesList.vue'
import ProcessTree from '@/components/analysis/ProcessTree.vue'
import EvidenceViewer from '@/components/analysis/EvidenceViewer.vue'
import RelatedEventsList from '@/components/analysis/RelatedEventsList.vue'
import AiVerdictPanel from '@/components/analysis/AiVerdictPanel.vue'
import IocIndicators from '@/components/analysis/IocIndicators.vue'
import RelatedAlerts from '@/components/analysis/RelatedAlerts.vue'
import RemediationSuggestions from '@/components/analysis/RemediationSuggestions.vue'
import HostOverview from '@/components/analysis/HostOverview.vue'
import DispositionPanel from '@/components/analysis/DispositionPanel.vue'

const route = useRoute()
const router = useRouter()
const store = useAnalysisStore()

const eventId = computed(() => route.params.id)

// 判断当前路由 id 是否为 32 位 hex 原始安全事件 ID。
// 复合 id（如 cm:suspicious_startup_items:160）来自非 security_events 源，
// 其详情数据中不存在可用于分诊/触发器调试的 32-hex event_id。
const isRawEventId = computed(() => /^[0-9a-f]{32}$/.test(String(eventId.value || '')))

const eventData = ref(null)
const projection = ref(null)
const loading = ref(true)
const error = ref('')

// ── 错误弹出去重标记：防止 404 事件详情和展示两个端点重复弹通知 ──
let hasShownEventNotFound = false

// ── AI 研判解析 ──
function parseEvidence(evi) {
  if (!evi) return {}
  if (typeof evi === 'object') return evi
  try { return JSON.parse(evi) } catch { return {} }
}

const aiVerdict = computed(() => {
  if (!eventData.value) return null
  const evi = parseEvidence(eventData.value.evidence)
  if (evi._ai_verdict) {
    if (typeof evi._ai_verdict === 'string') {
      try { return JSON.parse(evi._ai_verdict) } catch { return evi._ai_verdict }
    }
    return evi._ai_verdict
  }
  if (eventData.value.ai_verdict) {
    if (typeof eventData.value.ai_verdict === 'string') {
      try { return JSON.parse(eventData.value.ai_verdict) } catch { return eventData.value.ai_verdict }
    }
    return eventData.value.ai_verdict
  }
  return null
})

// ── 证据双视图 ──
const evidenceViews = computed(() => {
  if (!projection.value) return null
  // display API 返回 { event: {...}, projection: { evidence_views: {...} } }
  return projection.value?.projection?.evidence_views || projection.value?.evidence_views || null
})

// 自适应主体
const auxiliary = computed(() => {
  const aux = projection.value?.projection?.auxiliary
  return Array.isArray(aux) ? aux : []
})

const processSubject = computed(() => {
  const et = (eventData.value?.event_type || '')
  if (!et.startsWith('process') && et !== 'ioc_match') return null
  const f = auxiliary.value.find(f => f.key === 'process_subject')
  return f?.value || null
})

const networkSubject = computed(() => {
  const et = (eventData.value?.event_type || '')
  if (!et.startsWith('network') && et !== 'dns_query') return null
  const f = auxiliary.value.find(f => f.key === 'network_subject')
  return f?.value || null
})

const persistenceTarget = computed(() => {
  const et = (eventData.value?.event_type || '')
  if (!['persistence_register','registry_modify','registry_delete','scheduled_task','service_operation','wmi_subscribe'].includes(et)) return null
  const aux = auxiliary.value.find(f => f.key === 'persistence_target')
  return aux?.value || null
})

// ── 风险评分 ──
const riskScore = computed(() => {
  if (!eventData.value) return 0
  const required = Array.isArray(projection.value?.projection?.required)
    ? projection.value.projection.required
    : Array.isArray(projection.value?.required)
    ? projection.value.required
    : []
  const f = required.find(r => r.key === 'risk_score')
  return f?.value || 0
})

// ── 匹配规则 ──
const matchedRules = computed(() => {
  if (!eventData.value) return []
  return eventData.value.matched_rules || []
})

// ── 关联告警（P1，数据不可用时为空） ──
const relatedAlerts = computed(() => {
  return eventData.value?.related_alerts || []
})

// ── 案件信息 ──
const caseInfo = computed(() => {
  if (!eventData.value) return null
  return {
    case_id: eventData.value.case_id,
    case_name: eventData.value.case_name,
    case_number: eventData.value.case_number,
  }
})

// ── 三阶段数据加载 ──
async function loadAllPhases() {
  const id = eventId.value
  if (!id) return

  loading.value = true
  error.value = ''
  hasShownEventNotFound = false

  try {
    // 阶段一：核心数据（并发）
    const [detailRes, displayRes] = await Promise.allSettled([
      getEventDetail(id),
      fetchDisplayApi(id),
    ])

    if (detailRes.status === 'fulfilled') {
      eventData.value = detailRes.value.data
      // 展示投影为可选增强：即使失败也不阻断页面渲染
      if (displayRes.status === 'fulfilled') {
        projection.value = displayRes.value.data
      }
    } else {
      // 事件不存在——detail 和 display 可能都返回 404，但 Notification 已在 axios
      // 拦截器中统一处理（去重后只弹一次"事件不存在或已被删除"）。
      // 这里仅设置页面内联错误文案，不再重复弹窗。
      error.value = '事件不存在或已被删除'
      loading.value = false
      return
    }

    // 获取时间线（不阻塞细节增强）
    store.fetchTimeline().catch(() => {})

    // 阶段二：增强数据（并发，不阻塞渲染，错误已在 axios 拦截器处理）
    store.fetchEventDetailEnhanced(id).catch(() => {})

    // 阶段三：延后数据（P1）
    store.fetchProcessTree(id).catch(() => {})
    store.fetchRelatedEvents(id).catch(() => {})

  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAllPhases()
})

// 路由参数变化时重新加载
watch(() => route.params.id, () => {
  loadAllPhases()
})

// ── 交互方法 ──
function goBack() {
  router.push('/analysis-center')
}

function goToCase(caseId) {
  router.push({ path: '/analysis-center', query: { case_id: caseId } })
}

// ── 复制原始事件 ID（32 位 hex） ──
// 仅当 eventId 为 32 位 hex 时才复制；复合 id 提示无原始 event_id，绝不复制。
async function copyRawEventId() {
  const id = String(eventId.value || '')
  if (!/^[0-9a-f]{32}$/.test(id)) {
    ElMessage.warning('当前事件非安全事件源，无原始 event_id')
    return
  }

  const ok = await copyText(id)
  if (ok) {
    ElMessage.success('已复制原始事件ID：' + id)
  } else {
    ElMessage.error('复制失败，请手动复制：' + id)
  }
}

// 复制文本：优先 Clipboard API，失败则回退到临时 textarea + execCommand
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 继续走回退方案
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const success = document.execCommand('copy')
    document.body.removeChild(ta)
    return success
  } catch {
    return false
  }
}

async function handleUpdateStatus(status) {
  try {
    await store.updateStatus(eventId.value, status)
    // 刷新事件数据
    const res = await getEventDetail(eventId.value)
    eventData.value = res.data
  } catch (e) {
    console.error('状态更新失败', e)
  }
}

function handleDeepInvestigation() {
  const query = { eventId: eventId.value }
  if (caseInfo.value?.case_id) query.caseId = caseInfo.value.case_id
  router.push({ path: '/agent-orchestration/runs', query })
}

function handleSelectEvent(selectedId) {
  router.push(`/analysis-center/event/${selectedId}`)
}

function handleToggleStage(stage) {
  // 左栏阶段折叠/展开由 AttackChainTimeline 内部管理
}

function handleTimelineRetry() {
  store.fetchTimeline()
}

function handleFilterByHost(hostId) {
  store.ruleFilters.hostId = hostId
  store.ruleFilters.page = 1
  router.push('/analysis-center')
}

function handleViewRelatedEvent(relatedId) {
  router.push(`/analysis-center/event/${relatedId}`)
}

async function handleAddDisposition(comment) {
  if (!comment.trim()) return
  await store.addDispositionForEvent(eventId.value, {
    action: 'review',
    operator: '',
    comment: comment.trim(),
  })
}
</script>

<style scoped>
/* ── 响应式布局 ── */
@media (max-width: 1100px) {
  .event-detail-view { height: unset; min-height: calc(100vh - 52px); }
  .edv-body { flex-direction: column; align-items: stretch; overflow-y: auto; }
}
.event-detail-view {
  height: calc(100vh - 52px);
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-subtle);
  overflow: hidden;
}
.edv-body {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.edv-loading, .edv-error {
  font-size: 14px;
  color: var(--color-fg-subtle);
  text-align: center;
  padding: 40px;
}
.edv-copy-raw-id {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  margin-left: 8px;
  font-size: 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  cursor: pointer;
  white-space: nowrap;
  font-family: inherit;
}
.edv-copy-raw-id:hover {
  background: var(--color-canvas-inset);
}
.edv-copy-raw-id.is-disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.edv-copy-raw-id.is-disabled:hover {
  background: var(--color-canvas-default);
}
</style>
