<template>
  <div class="event-detail-view">
    <!-- 顶部导航 -->
    <div class="edv-topbar">
      <button class="btn btn-back" @click="goBack">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9 3L5 7L9 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        返回分析中心
      </button>
      <span class="edv-title" v-if="eventId">事件详情 · {{ eventId.substring(0, 16) }}…</span>
    </div>

    <div class="edv-body" v-if="loading">
      <div class="edv-loading">加载中…</div>
    </div>

    <div class="edv-body" v-else-if="eventData">
      <!-- 决策条 -->
      <div class="edv-decision">
        <span class="severity-badge" :class="'badge-' + (eventData.severity || 'info')">{{ eventData.severity }}</span>
        <span class="edv-risk" :style="{ color: riskScoreColor(riskScore) }">{{ riskScore }}</span>
        <span v-if="eventData.category" class="edv-cat-tag">{{ categoryLabel }}</span>
        <span v-if="eventData.attack_stage" class="edv-stage-tag">{{ stageLabel(eventData.attack_stage) }}</span>
        <span class="edv-status-tag" :class="'st-' + (eventData.status || 'pending')">{{ statusLabel(eventData.status) }}</span>
        <span class="edv-host">{{ eventData.hostname || ('主机#' + eventData.host_id) }}</span>
      </div>

      <!-- AI 研判区块（全屏详情页专用） -->
      <div class="edv-ai-section" v-if="isAiEvent || eventData.ai_verdict">
        <div class="edv-ai-header">
          <span v-if="isAiEvent">🤖 AI 优先推荐 · 详细研判</span>
          <span v-else-if="aiVerdictLabel === 'suspicious'">🟡 AI 待复核</span>
          <span v-else-if="aiVerdictLabel === 'false_positive'">⚪ AI 误报</span>
          <span v-else>🤖 AI 研判</span>
        </div>
        <div class="edv-ai-body">
          <div class="edv-ai-grid">
            <div class="edv-ai-item">
              <span class="edv-ai-label">置信度</span>
              <span class="edv-ai-val" :class="{ 'high-c': aiConfidence >= 80, 'mid-c': aiConfidence >= 60 && aiConfidence < 80 }">{{ aiConfidence }}%</span>
            </div>
            <div class="edv-ai-item" v-if="aiTcode">
              <span class="edv-ai-label">MITRE 技术</span>
              <span class="edv-ai-val tcode">{{ aiTcode }}</span>
            </div>
            <div class="edv-ai-item" v-if="aiAttackType">
              <span class="edv-ai-label">攻击类型</span>
              <span class="edv-ai-val">{{ aiAttackType }}</span>
            </div>
            <div class="edv-ai-item" v-if="aiAction">
              <span class="edv-ai-label">建议动作</span>
              <span class="edv-ai-val action-tag" :class="'act-' + aiAction">{{ aiActionLabel }}</span>
            </div>
            <div class="edv-ai-item" v-if="aiReason">
              <span class="edv-ai-label">研判理由</span>
              <span class="edv-ai-val">{{ aiReason }}</span>
            </div>
          </div>
          <div class="edv-ai-analysis-text" v-if="eventData.ai_analysis">
            <span class="edv-ai-label">AI 分析原文</span>
            <div class="edv-ai-raw">{{ eventData.ai_analysis }}</div>
          </div>
          <div class="edv-ai-original" v-if="isAiEvent && eventData.summary">
            <span class="edv-ai-label">原始事件摘要</span>
            <div class="edv-ai-raw">{{ eventData.summary }}</div>
          </div>
        </div>
      </div>

      <!-- 两列布局 -->
      <div class="edv-grid">
        <!-- 左列：必填字段 -->
        <div class="edv-col">
          <div class="edv-card">
            <div class="edv-card-title">必填字段 ({{ required.length }})</div>
            <div class="edv-field-grid">
              <div v-for="f in required" :key="f.key" class="edv-field">
                <span class="ef-label">{{ f.label }}</span>
                <span class="ef-value">{{ fieldDisplay(f) }}</span>
              </div>
            </div>
          </div>

          <!-- 命中规则 -->
          <div class="edv-card" v-if="matchedRules.length">
            <div class="edv-card-title">命中规则 ({{ matchedRules.length }})</div>
            <div v-for="(r, i) in matchedRules" :key="i" class="edv-rule-item">
              <span class="er-name">{{ r.rule_name || r.rule_id || ('规则#' + (i+1)) }}</span>
              <span class="er-sev" :class="'er-sev-' + (r.severity || 'info')">{{ r.severity }}</span>
              <span v-if="r.description" class="er-desc">{{ r.description }}</span>
              <span v-if="r.confidence" class="er-conf">置信度 {{ r.confidence }}</span>
            </div>
          </div>
        </div>

        <!-- 右列：辅助 + 证据 -->
        <div class="edv-col">
          <!-- 证据双视图 -->
          <div class="edv-card" v-if="evidenceViews">
            <div class="edv-card-title">
              证据详情
              <button class="ev-toggle" @click="toggleEvidence">
                {{ evMode === 'normalized' ? '切换原始数据 →' : '← 切换范式化视图' }}
              </button>
            </div>
            <div v-if="evMode === 'normalized'" class="edv-json">
              <pre>{{ formatJson(evidenceViews.normalized) }}</pre>
            </div>
            <div v-else class="edv-json">
              <div class="ev-raw-src">来源: {{ evidenceViews.raw_source }}</div>
              <pre>{{ formatJson(evidenceViews.raw) }}</pre>
            </div>
          </div>

          <!-- 辅助字段（仅当有值才显示） -->
          <div class="edv-card" v-if="hasContent(processSubject)">
            <div class="edv-card-title">进程主体</div>
            <div class="edv-field-grid">
              <div v-for="(val, key) in processSubject" :key="key" class="edv-field" v-if="val && val !== '—'">
                <span class="ef-label">{{ key }}</span>
                <span class="ef-value">{{ val }}</span>
              </div>
            </div>
          </div>
          <div class="edv-card" v-if="hasContent(networkSubject)">
            <div class="edv-card-title">网络主体</div>
            <div class="edv-field-grid">
              <div v-for="(val, key) in networkSubject" :key="key" class="edv-field" v-if="val && val !== '—'">
                <span class="ef-label">{{ key }}</span>
                <span class="ef-value">{{ val }}</span>
              </div>
            </div>
          </div>
          <div class="edv-card" v-if="hasContent({ target: persistenceTarget })">
            <div class="edv-card-title">持久化落点</div>
            <div class="edv-value">{{ persistenceTarget }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="edv-body" v-else-if="!loading && error">
      <div class="edv-error">加载失败: {{ error }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getEventDisplay as fetchDisplay } from '@/api/events'

const route = useRoute()
const router = useRouter()
const eventId = route.params.id

const eventData = ref(null)
const projection = ref(null)
const loading = ref(true)
const error = ref('')
const evMode = ref('normalized')

onMounted(async () => {
  try {
    const res = await fetchDisplay(eventId)
    const d = res.data
    eventData.value = d.event || d
    projection.value = d.projection || d
  } catch (e) {
    error.value = e.message || '请求失败'
  } finally {
    loading.value = false
  }
})

const required = computed(() => projection.value?.required || [])
const auxiliary = computed(() => projection.value?.auxiliary || [])
const evidenceViews = computed(() => projection.value?.evidence_views || null)

const matchedRules = computed(() => {
  const f = required.value.find(r => r.key === 'matched_rules')
  return f?.value || []
})

const riskScore = computed(() => {
  const f = required.value.find(r => r.key === 'risk_score')
  return f?.value || 0
})

function categoryLabel() {
  const labels = { process: '进程', network: '网络', persistence: '持久化', startup: '启动项', behavior: '行为', ioc: '情报', credential: '凭据', discovery: '发现', execution: '执行', lateral: '横向', c2: 'C2', impact: '影响' }
  return labels[eventData.value?.category] || eventData.value?.category || ''
}

function statusLabel(s) {
  const labels = { pending: '待处理', triaging: '分诊中', investigating: '调查中', resolved: '已解决', rejected: '已误报' }
  return labels[s] || s
}
function stageLabel(s) {
  const labels = { initial_access: '初始访问', execution: '执行', persistence: '持久化', privilege_escalation: '提权', defense_evasion: '防御规避', credential_access: '凭据访问', discovery: '发现', lateral_movement: '横向移动', collection: '收集', command_and_control: 'C2', exfiltration: '外泄', impact: '影响', unknown: '未知' }
  return labels[s] || s
}
function riskScoreColor(s) {
  if (s >= 70) return '#dc2626'
  if (s >= 50) return '#d97706'
  if (s >= 30) return '#2563eb'
  return '#a3a3a3'
}

// AI 研判数据
const isAiEvent = computed(() => eventData.value?.event_type === 'ai_recommended')

// 解析 evidence（可能是 JSON 字符串）
function parseEvidence(evi) {
  if (!evi) return {}
  if (typeof evi === 'object') return evi
  try { return JSON.parse(evi) } catch { return {} }
}

const aiVerdict = computed(() => {
  if (!eventData.value) return null
  // 优先从 evidence._ai_verdict 解析
  const evi = parseEvidence(eventData.value.evidence)
  if (evi._ai_verdict) {
    if (typeof evi._ai_verdict === 'string') {
      try { return JSON.parse(evi._ai_verdict) } catch { return evi._ai_verdict }
    }
    return evi._ai_verdict
  }
  // 其次从 event.ai_verdict 列读取
  if (eventData.value.ai_verdict) {
    if (typeof eventData.value.ai_verdict === 'string') {
      try { return JSON.parse(eventData.value.ai_verdict) } catch { return eventData.value.ai_verdict }
    }
    return eventData.value.ai_verdict
  }
  return null
})
const aiVerdictLabel = computed(() => aiVerdict.value?.label || '')
const aiConfidence = computed(() => aiVerdict.value?.confidence || 0)
const aiTcode = computed(() => aiVerdict.value?.t_code || eventData.value?.t_code || '')
const aiAttackType = computed(() => aiVerdict.value?.attack_type || '')
const aiAction = computed(() => aiVerdict.value?.action || '')
const aiReason = computed(() => aiVerdict.value?.reason || '')
const aiActionLabel = computed(() => ({
  isolate: '隔离主机', kill_process: '结束进程', block_ip: '封锁IP', review: '人工复核'
}[aiAction.value] || aiAction.value))

const processSubject = computed(() => {
  const f = auxiliary.value.find(a => a.key === 'process_subject')
  return f?.value || null
})
const networkSubject = computed(() => {
  const f = auxiliary.value.find(a => a.key === 'network_subject')
  return f?.value || null
})
const persistenceTarget = computed(() => {
  const f = auxiliary.value.find(a => a.key === 'persistence_target')
  return f?.value || null
})

function fieldDisplay(f) {
  if (!f || f.value === null || f.value === undefined || f.value === '') return '—'
  if (typeof f.value === 'object') return formatJson(f.value)
  return String(f.value)
}

function hasContent(obj) {
  if (!obj) return false
  if (typeof obj !== 'object') return !!obj
  return Object.values(obj).some(v => v && v !== '—')
}

function formatJson(obj) {
  if (!obj) return '{}'
  try { return JSON.stringify(obj, null, 2) }
  catch { return String(obj) }
}

function toggleEvidence() {
  evMode.value = evMode.value === 'normalized' ? 'raw' : 'normalized'
}

function goBack() {
  router.push('/analysis-center')
}
</script>

<style scoped>
.event-detail-view {
  height: calc(100vh - 52px);
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-subtle);
  overflow: hidden;
}
.edv-topbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 20px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}
.btn-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  cursor: pointer;
}
.edv-title { font-size: 13px; font-weight: 500; color: var(--color-fg-subtle); }
.edv-body { flex: 1; overflow-y: auto; padding: 20px; }
.edv-loading, .edv-error { font-size: 14px; color: var(--color-fg-subtle); text-align: center; padding: 40px; }

/* 决策条 */
.edv-decision {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  margin-bottom: 16px;
}
.severity-badge { padding: 2px 10px; border-radius: 4px; color: #fff; font-size: 12px; font-weight: 500; }
.badge-critical, .badge-high { background: #dc2626; }
.badge-medium { background: #d97706; }
.badge-low { background: #2563eb; }
.badge-info { background: #a3a3a3; }
.edv-risk { font-size: 18px; font-weight: 600; min-width: 30px; }
.edv-cat-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: var(--color-canvas-inset); color: var(--color-fg-subtle); }
.edv-stage-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: var(--color-accent-subtle); color: var(--color-accent-fg); }
.edv-status-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; }
.st-pending { background: var(--color-accent-subtle); color: var(--color-accent-fg); }
.st-triaging, .st-investigating { background: #fef3c7; color: #d97706; }
.st-resolved { background: #dcfce7; color: #16a34a; }
.st-rejected { background: #fef2f2; color: #dc2626; }
.edv-host { font-size: 12px; color: var(--color-fg-subtle); margin-left: auto; }

/* 两列网格 */
.edv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.edv-col { display: flex; flex-direction: column; gap: 16px; }

/* AI 研判区块 */
.edv-ai-section {
  margin: 0 0 16px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  overflow: hidden;
}
.edv-ai-header {
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 500;
  border-bottom: 0.5px solid var(--color-border-default);
  background: rgba(22, 163, 74, 0.04);
}
.edv-ai-body {
  padding: 12px 16px;
}
.edv-ai-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.edv-ai-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.edv-ai-label {
  font-size: 11px;
  color: var(--color-fg-subtle, #888);
}
.edv-ai-val {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-fg-default);
}
.edv-ai-val.high-c { color: #dc2626; }
.edv-ai-val.mid-c { color: #d97706; }
.edv-ai-val.tcode {
  font-family: monospace;
  background: rgba(147, 51, 234, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-block;
  color: #7c3aed;
}
.edv-ai-val.action-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}
.edv-ai-val.action-tag.act-isolate { background: rgba(220,38,38,0.1); color: #dc2626; }
.edv-ai-val.action-tag.act-kill_process { background: rgba(220,38,38,0.1); color: #dc2626; }
.edv-ai-val.action-tag.act-block_ip { background: rgba(217,119,6,0.1); color: #d97706; }
.edv-ai-val.action-tag.act-review { background: rgba(37,99,235,0.1); color: #2563eb; }
.edv-ai-analysis-text, .edv-ai-original {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 0.5px solid var(--color-border-default);
}
.edv-ai-raw {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-fg-default);
  white-space: pre-wrap;
  word-break: break-all;
}

/* 卡片 */
.edv-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 16px;
}
.edv-card-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* 字段网格 */
.edv-field-grid { display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; font-size: 13px; }
.edv-field { display: contents; }
.ef-label { color: var(--color-fg-subtle); font-size: 11px; white-space: nowrap; padding-top: 2px; }
.ef-value { color: var(--color-fg-default); word-break: break-all; }

.edv-value { font-size: 13px; color: var(--color-fg-default); }

/* 规则列表 */
.edv-rule-item { padding: 8px 10px; background: var(--color-canvas-inset); border-radius: 6px; margin-bottom: 6px; font-size: 12px; }
.er-name { font-weight: 500; }
.er-sev { font-size: 10px; margin-left: 6px; padding: 1px 5px; border-radius: 3px; }
.er-sev-high, .er-sev-critical { background: rgba(220,38,38,0.1); color: #dc2626; }
.er-sev-medium { background: rgba(217,119,6,0.1); color: #d97706; }
.er-sev-low { background: rgba(37,99,235,0.1); color: #2563eb; }
.er-desc { display: block; font-size: 11px; color: var(--color-fg-light); margin-top: 2px; }
.er-conf { display: block; font-size: 10px; color: var(--color-fg-light); margin-top: 2px; }

/* 证据切换 */
.ev-toggle { font-size: 10px; padding: 2px 8px; border: 0.5px solid var(--color-border-default); border-radius: 4px; background: var(--color-canvas-subtle); color: var(--color-accent-fg); cursor: pointer; }
.ev-raw-src { font-size: 10px; color: var(--color-fg-light); margin-bottom: 6px; }

/* JSON 显示 */
.edv-json {
  background: var(--color-canvas-inset);
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  max-height: 400px;
  overflow: auto;
}
.edv-json pre {
  margin: 0;
  padding: 10px;
  font-size: 11px;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-fg-default);
}

/* 响应式 */
@media (max-width: 900px) {
  .edv-grid { grid-template-columns: 1fr; }
}
</style>
