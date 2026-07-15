<template>
  <div class="event-detail-panel">
    <!-- 标题栏 -->
    <div class="detail-header">
      <div class="header-left">
        <span class="severity-badge" :class="'badge-' + (event.severity || 'info')">
          {{ event.severity }}
        </span>
        <span class="event-id" :title="event.id">
          {{ event.id ? event.id.substring(0, 12) + '...' : '' }}
        </span>
      </div>
      <button class="close-btn" @click="$emit('close')">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </button>
    </div>

    <!-- 基本信息 -->
    <div class="detail-section">
      <div class="section-title">基本信息</div>
      <div class="detail-row">
        <span class="detail-label">时间</span>
        <span class="detail-value">{{ formatTime(event.timestamp) }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">类型</span>
        <span class="detail-value">{{ eventTypeLabel(event.event_type) }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">主机</span>
        <span class="detail-value">{{ event.hostname || ('#主机' + event.host_id) }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">采集器</span>
        <span class="detail-value">{{ event.source_collector || '—' }}</span>
      </div>
      <!-- 父进程 -->
      <div class="detail-row" v-if="event.evidence?.parent_name">
        <span class="detail-label">父进程</span>
        <span class="detail-value">{{ event.evidence.parent_name }} (PPID: {{ event.evidence.ppid || '?' }})</span>
      </div>
      <!-- 文件哈希 -->
      <div class="detail-row" v-if="event.evidence?.sha256">
        <span class="detail-label">文件哈希</span>
        <span class="detail-value">
          <div class="hash-with-actions">
            <span class="hash-val">{{ event.evidence.sha256.substring(0, 16) }}...</span>
            <button class="hash-act-btn" @click.stop="copyHash(event.evidence.sha256)">复制</button>
            <button class="hash-act-btn" @click.stop="openVT(event.evidence.sha256)">VT</button>
          </div>
        </span>
      </div>
      <!-- 签名状态 -->
      <div class="detail-row" v-if="event.evidence?.is_signed !== undefined">
        <span class="detail-label">签名状态</span>
        <span class="detail-value">
          <span v-if="event.evidence.is_signed" style="background:var(--color-success-subtle);padding:0 6px;border-radius:3px;color:var(--color-success-fg)">已签名</span>
          <span v-else style="background:var(--color-danger-subtle);padding:0 6px;border-radius:3px;color:var(--color-danger-fg)">未签名</span>
        </span>
      </div>
      <div class="detail-row" v-if="event.case_id">
        <span class="detail-label">案件</span>
        <span class="detail-value">{{ event.case_name || ('案件#' + event.case_id) }}</span>
      </div>
      <div class="detail-row" v-if="event.import_id">
        <span class="detail-label">日志 ID</span>
        <span class="detail-value">{{ event.import_id }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">攻击链</span>
        <span class="detail-value">{{ event.attack_chain_id || '—' }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">ATT&CK</span>
        <span class="detail-value">
          {{ event.attack_stage ? stageLabel(event.attack_stage) : '—' }}
        </span>
      </div>
      <div class="detail-row">
        <span class="detail-label">负责人</span>
        <span class="detail-value">{{ event.assignee || '未指派' }}</span>
      </div>
    </div>

    <!-- 风险评分 -->
    <div class="detail-section" v-if="riskScore > 0">
      <div class="section-title">风险评分</div>
      <div class="risk-score-wrap">
        <div class="rs-big" :style="{ color: riskScoreColor(riskScore) }">{{ riskScore }}</div>
        <div class="rs-breakdown">
          <div class="rs-item"><span>严重度</span><span>+{{ severityWeight }}</span></div>
          <div class="rs-item"><span>命中规则 ({{ matchedRuleCount }})</span><span>+{{ ruleScore }}</span></div>
          <div class="rs-item"><span>IOC 命中</span><span>+{{ iocScore }}</span></div>
        </div>
      </div>
    </div>

    <!-- 匹配规则 -->
    <div class="detail-section" v-if="event.rule_name || event.matched_rules">
      <div class="section-title">匹配规则</div>
      <div v-if="event.rule_name" class="rule-item">
        <span class="detail-value">{{ event.rule_name }}</span>
      </div>
      <div v-if="event.matched_rules && event.matched_rules.length > 0">
        <div v-for="(rule, i) in event.matched_rules" :key="i" class="rule-item">
          <span class="detail-value">{{ rule.name || rule.rule_id || ('规则 #' + (i + 1)) }}</span>
          <span v-if="rule.description" class="rule-desc">{{ rule.description }}</span>
        </div>
      </div>
      <div v-else class="rule-none">无匹配规则（基于模型推断）</div>
    </div>

    <!-- 原始命令 -->
    <div class="detail-section" v-if="event.evidence?.command_line || event.evidence?.process_cmdline">
      <div class="section-title">原始命令</div>
      <div class="cmd-block">
        <code class="cmd-code">{{ event.evidence.command_line || event.evidence.process_cmdline }}</code>
      </div>
    </div>

    <!-- 处置操作 -->
    <div class="detail-section">
      <div class="action-buttons">
        <button
          v-if="event.status === 'pending'"
          class="btn btn-primary"
          @click="onStatusChange('triaging')"
        >
          开始分诊
        </button>
        <button
          v-if="event.status === 'triaging'"
          class="btn btn-warning"
          @click="onStatusChange('investigating')"
        >
          进入调查
        </button>
        <button
          v-if="event.status === 'investigating'"
          class="btn btn-success"
          @click="onStatusChange('resolved')"
        >
          标记解决
        </button>
        <button
          v-if="event.status !== 'rejected' && event.status !== 'resolved'"
          class="btn btn-danger"
          @click="onStatusChange('rejected')"
        >
          标记误报
        </button>
        <button
          v-if="event.status === 'resolved'"
          class="btn btn-warning"
          @click="onStatusChange('investigating')"
        >
          重新开案
        </button>
      </div>
    </div>

    <!-- 主机概览 -->
    <div class="detail-section" v-if="store.hostStats">
      <div class="section-title">主机概览 — {{ event.hostname }}</div>
      <div class="host-stat-grid">
        <div class="host-stat"><div class="host-stat-val">{{ store.hostStats.total_24h }}</div><div class="host-stat-lbl">24h 事件</div></div>
        <div class="host-stat"><div class="host-stat-val" style="color:var(--color-risk-high)">{{ store.hostStats.matched_24h }}</div><div class="host-stat-lbl">规则命中</div></div>
        <div class="host-stat"><div class="host-stat-val" style="color:var(--color-risk-critical)">{{ store.hostStats.active_alerts }}</div><div class="host-stat-lbl">活跃告警</div></div>
      </div>
      <div v-if="store.hostStats.last_disposition" style="margin-top:8px;font-size:11px;color:var(--color-fg-subtle)">
        上次处置: {{ store.hostStats.last_disposition.at }} · {{ store.hostStats.last_disposition.operator }} — "{{ store.hostStats.last_disposition.comment }}"
      </div>
    </div>

    <!-- 时间线上下文 -->
    <div class="detail-section" v-if="store.eventContext.length">
      <div class="section-title">时间线上下文 · 前后 5 分钟</div>
      <div v-for="evt in store.eventContext" :key="evt.id" class="tl-item" :class="{ 'tl-current': evt.id === event.id }">
        <div class="tl-time">{{ formatTime(evt.timestamp) }}</div>
        <div class="tl-line">
          <div class="tl-dot" :class="dotColorClass(evt.severity)"></div>
          <div class="tl-line-conn"></div>
        </div>
        <div class="tl-body">
          <strong :style="{ color: sevTextColor(evt.severity) }">{{ eventTypeLabel(evt.event_type) }}</strong>
          <span class="tl-summary">{{ evt.summary || '' }}</span>
        </div>
      </div>
    </div>

    <!-- 影响范围 -->
    <div class="detail-section" v-if="store.impactScope">
      <div class="section-title">影响范围</div>
      <div class="impact-grid">
        <div class="impact-item" v-for="(val, key) in store.impactScope" :key="key">
          <div class="impact-icon">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.3"/>
              <path d="M8 4V9M8 11V12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </div>
          <div><div class="impact-num">{{ val }}</div><div class="impact-lbl">{{ impactLabel(key) }}</div></div>
        </div>
      </div>
    </div>

    <!-- 处置记录 -->
    <div class="detail-section">
      <div class="section-title">处置记录</div>
      <div v-if="store.dispositions.length" class="disp-list">
        <div v-for="d in store.dispositions" :key="d.id" class="disp-item">
          <span class="disp-time">{{ d.created_at }}</span>
          <div>
            <span class="disp-actor">{{ d.operator }}</span>
            <span class="disp-action">{{ actionLabel(d.action) }}</span>
            <div v-if="d.comment" class="disp-comment">"{{ d.comment }}"</div>
          </div>
        </div>
      </div>
      <div v-else style="font-size:12px;color:var(--color-fg-light);padding:4px 0">暂无处置记录</div>
      <div class="disp-input-wrap">
        <input v-model="dispComment" class="disp-input" placeholder="添加处置备注...">
        <button class="btn btn-sm btn-primary" @click="onAddDisposition">发送</button>
      </div>
    </div>

    <!-- 原始证据 + 结构化视图 -->
    <div class="detail-section">
      <div class="section-title">原始证据 · 结构化视图</div>
      <div v-for="(val, key) in structuredEvidence" :key="key" class="ev-row">
        <span class="ev-key">{{ key }}</span>
        <span class="ev-val">{{ val }}</span>
      </div>
    </div>

    <div class="detail-section">
      <div class="section-title">完整原始证据</div>
      <div class="json-viewer">
        <pre class="json-content">{{ formatJson(event.evidence) }}</pre>
      </div>
    </div>

    <!-- IOC 匹配 -->
    <div class="detail-section" v-if="event.ioc_matches && event.ioc_matches.length > 0">
      <div class="section-title">IOC 匹配 ({{ event.ioc_matches.length }})</div>
      <div class="ioc-list">
        <span
          v-for="ioc in event.ioc_matches"
          :key="ioc"
          class="ioc-tag"
        >
          {{ ioc }}
        </span>
      </div>
    </div>

    <!-- 处置建议 -->
    <div class="detail-section">
      <div class="section-title">处置建议</div>
      <div class="suggestion-text">
        <template v-if="event.severity === 'critical' || event.severity === 'high'">
          建议立即隔离受感染主机，终止可疑进程，并收集完整的取证数据。
        </template>
        <template v-else-if="event.severity === 'medium'">
          建议确认进程/网络行为是否为正常业务操作，可查询历史基线。
        </template>
        <template v-else>
          信息性事件，可归档记录，无需立即处置。
        </template>
      </div>
    </div>

    <!-- 关联事件 -->
    <div class="detail-section" v-if="event.related_events && event.related_events.length > 0">
      <div class="section-title">关联事件 ({{ event.related_events.length }})</div>
      <div class="related-list">
        <button
          v-for="rid in event.related_events"
          :key="rid"
          class="btn btn-link"
          @click="onViewRelated(rid)"
        >
          {{ rid.substring(0, 12) + '...' }}
        </button>
      </div>
    </div>

    <!-- 关联数据 -->
    <div class="detail-section" v-if="event.host_id">
      <div class="section-title">关联数据</div>
      <div class="action-buttons">
        <button class="btn btn-primary" @click="viewLog">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="margin-right: 4px;">
            <circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.3"/>
            <path d="M9.5 9.5L13 13" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
          </svg>
          查看原始日志
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'

const props = defineProps({
  event: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'update-status', 'assign', 'view-related'])

const store = useAnalysisStore()
const dispComment = ref('')

const SEV_COLORS = {
  critical: '#dc2626', high: '#dc2626', medium: '#d97706',
  low: '#2563eb', info: '#a3a3a3',
}
const STAGE_LABELS = {
  initial_access: '初始访问', execution: '执行', persistence: '持久化',
  privilege_escalation: '提权', defense_evasion: '防御规避',
  credential_access: '凭据访问', discovery: '发现',
  lateral_movement: '横向移动', collection: '收集',
  command_and_control: 'C2', exfiltration: '外泄',
  impact: '影响', unknown: '未知',
}
const EVENT_TYPE_LABELS = {
  process_start: '进程启动', process_terminate: '进程退出',
  network_outbound: '出站连接', network_listen: '端口监听',
  registry_modify: '注册表写入', registry_delete: '注册表删除',
  file_create: '文件创建', file_modify: '文件修改',
  persistence_register: '持久化注册', wmi_subscribe: 'WMI订阅',
  behavior_alert: '行为告警', ioc_match: 'IOC命中',
  user_login: '用户登录', user_logout: '用户登出',
  dns_query: 'DNS查询', module_load: '模块加载',
  scheduled_task: '计划任务', service_operation: '服务操作',
  pipe_connect: '管道连接', driver_load: '驱动加载',
}
const ACTION_LABELS = {
  isolate: '隔离主机', kill_process: '结束进程', block_ip: '封锁IP',
  add_rule: '添加规则', escalate: '上报', ignore: '忽略',
  review: '复核',
}

// ── 风险评分 computed ──
function calcRiskScore(ev) {
  if (!ev) return 0
  let s = { critical: 80, high: 60, medium: 40, low: 20, info: 5 }[ev.severity] || 5
  if (ev.matched_rules?.length) s += Math.min(ev.matched_rules.length * 5, 25)
  if (ev.ioc_matches?.length) s += Math.min(ev.ioc_matches.length * 15, 30)
  return Math.max(0, Math.min(100, s))
}

const riskScore = computed(() => calcRiskScore(props.event))
const severityWeight = computed(() => {
  return { critical: 80, high: 60, medium: 40, low: 20, info: 5 }[props.event?.severity] || 5
})
const matchedRuleCount = computed(() => props.event?.matched_rules?.length || 0)
const ruleScore = computed(() => Math.min((props.event?.matched_rules?.length || 0) * 5, 25))
const iocScore = computed(() => Math.min((props.event?.ioc_matches?.length || 0) * 15, 30))

function riskScoreColor(score) {
  if (score >= 70) return 'var(--color-risk-critical)'
  if (score >= 50) return 'var(--color-risk-medium)'
  if (score >= 30) return 'var(--color-risk-low)'
  return 'var(--color-fg-subtle)'
}

// ── 结构化证据 ──
const structuredEvidence = computed(() => {
  const ev = props.event?.evidence || {}
  const keys = Object.keys(ev).slice(0, 8)
  const result = {}
  keys.forEach(k => {
    const val = ev[k]
    result[k] = typeof val === 'object' ? JSON.stringify(val) : String(val)
  })
  return result
})

function sevColor(s) { return SEV_COLORS[s] || '#a3a3a3' }
function stageLabel(s) { return STAGE_LABELS[s] || s }
function eventTypeLabel(t) { return EVENT_TYPE_LABELS[t] || t }
function actionLabel(a) { return ACTION_LABELS[a] || a }

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatJson(obj) {
  if (!obj) return '{}'
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function dotColorClass(severity) {
  return 'sev-' + (severity || 'info')
}

function sevTextColor(severity) {
  return SEV_COLORS[severity] || '#a3a3a3'
}

function impactLabel(key) {
  const labels = {
    hosts: '受影响主机', processes: '受影响进程', users: '受影响用户',
    ips: '关联IP', files: '关联文件',
  }
  return labels[key] || key
}

function copyHash(hash) {
  navigator.clipboard?.writeText(hash).then(() => {
    // 复制成功
  }).catch(() => {
    // fallback
  })
}

function openVT(hash) {
  window.open(`https://www.virustotal.com/gui/file/${hash}`, '_blank')
}

function onStatusChange(status) {
  emit('update-status', { id: props.event.id, status })
}

function onViewRelated(relatedId) {
  emit('view-related', [relatedId])
}

function viewLog() {
  const caseId = props.event.case_id || ''
  const hostId = props.event.host_id || ''
  const query = props.event.hostname || `host_id:${hostId}`
  window.open(`/log-search?case_id=${caseId}&host_id=${hostId}&keyword=${encodeURIComponent(query)}`, '_blank')
}

async function onAddDisposition() {
  if (!dispComment.value.trim()) return
  await store.addDispositionForEvent(props.event.id, {
    action: 'review',
    operator: '',
    comment: dispComment.value,
  })
  dispComment.value = ''
}
</script>

<style scoped>
.event-detail-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  font-size: 13px;
  font-weight: 400;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.severity-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  font-weight: 500;
}

.severity-badge.badge-critical,
.severity-badge.badge-high {
  background: var(--color-danger-fg, #dc2626);
}

.severity-badge.badge-medium {
  background: var(--color-warning-fg, #d97706);
}

.severity-badge.badge-low {
  background: var(--color-accent-fg, #2563eb);
}

.severity-badge.badge-info {
  background: var(--color-fg-subtle, #888888);
}

.event-id {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  font-family: 'Courier New', monospace;
}

.close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle, #888888);
  cursor: pointer;
  border-radius: var(--r-btn, 6px);
  transition: all 0.15s;
}

.close-btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-default, #111111);
}

/* ===== Section ===== */
.detail-section {
  padding: 12px 16px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
}

.section-title {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle, #888888);
  margin-bottom: 12px;
}

/* ===== Detail Row ===== */
.detail-row {
  display: flex;
  margin-bottom: 8px;
  align-items: flex-start;
}

.detail-row:last-child {
  margin-bottom: 0;
}

.detail-label {
  width: 64px;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  line-height: 1.5;
}

.detail-value {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  flex: 1;
  word-break: break-all;
  line-height: 1.5;
}

/* ===== Hash Actions ===== */
.hash-with-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.hash-val {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.hash-act-btn {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 500;
  border-radius: 3px;
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-subtle);
  color: var(--color-accent-fg);
  cursor: pointer;
  line-height: 1.4;
  transition: all 0.15s;
}
.hash-act-btn:hover {
  background: var(--color-accent-subtle);
}

/* ===== Risk Score ===== */
.risk-score-wrap {
  display: flex;
  align-items: center;
  gap: 16px;
}
.rs-big {
  font-size: 32px;
  font-weight: 600;
  line-height: 1;
  min-width: 48px;
}
.rs-breakdown {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.rs-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.rs-item span:last-child {
  font-weight: 500;
  color: var(--color-fg-default);
}

/* ===== Action Buttons ===== */
.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* ===== Buttons ===== */
.btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.4;
}

.btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
}

.btn-primary {
  background: var(--color-accent-fg, #2563eb);
  color: #ffffff;
  border-color: var(--color-accent-fg, #2563eb);
}

.btn-primary:hover {
  opacity: 0.9;
  background: var(--color-accent-fg, #2563eb);
}

.btn-success {
  background: var(--color-success-fg, #16a34a);
  color: #ffffff;
  border-color: var(--color-success-fg, #16a34a);
}

.btn-success:hover {
  opacity: 0.9;
  background: var(--color-success-fg, #16a34a);
}

.btn-warning {
  background: var(--color-warning-fg, #d97706);
  color: #ffffff;
  border-color: var(--color-warning-fg, #d97706);
}

.btn-warning:hover {
  opacity: 0.9;
  background: var(--color-warning-fg, #d97706);
}

.btn-danger {
  background: transparent;
  color: var(--color-danger-fg, #dc2626);
  border-color: var(--color-danger-fg, #dc2626);
}

.btn-danger:hover {
  background: var(--color-danger-subtle, #fef2f2);
}

.btn-link {
  border: none;
  background: transparent;
  color: var(--color-accent-fg, #2563eb);
  padding: 4px 0;
  font-size: 12px;
  cursor: pointer;
  display: block;
  text-align: left;
}

.btn-link:hover {
  text-decoration: underline;
}

.btn-sm {
  padding: 4px 10px;
  font-size: 11px;
}

/* ===== Host Stats ===== */
.host-stat-grid {
  display: flex;
  gap: 12px;
}
.host-stat {
  flex: 1;
  text-align: center;
  padding: 8px;
  background: var(--color-canvas-inset);
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default);
}
.host-stat-val {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
}
.host-stat-lbl {
  font-size: 10px;
  color: var(--color-fg-subtle);
  margin-top: 2px;
}

/* ===== Timeline ===== */
.tl-item {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
  padding: 4px 0;
}
.tl-current {
  background: var(--color-accent-subtle);
  border-radius: 4px;
  padding: 4px 4px;
  margin-left: -4px;
}
.tl-time {
  width: 56px;
  flex-shrink: 0;
  font-size: 10px;
  font-family: 'Courier New', monospace;
  color: var(--color-fg-subtle);
  padding-top: 2px;
}
.tl-line {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 10px;
  flex-shrink: 0;
}
.tl-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tl-dot.sev-critical,
.tl-dot.sev-high {
  background: var(--color-risk-critical);
}
.tl-dot.sev-medium {
  background: var(--color-risk-medium);
}
.tl-dot.sev-low {
  background: var(--color-risk-low);
}
.tl-dot.sev-info {
  background: var(--color-fg-light);
}
.tl-line-conn {
  width: 1px;
  flex: 1;
  background: var(--color-border-default);
  min-height: 12px;
}
.tl-body {
  flex: 1;
  font-size: 11px;
  line-height: 1.5;
}
.tl-summary {
  margin-left: 4px;
  color: var(--color-fg-subtle);
}

/* ===== Impact ===== */
.impact-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.impact-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--color-canvas-inset);
  padding: 8px 12px;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default);
}
.impact-icon {
  color: var(--color-fg-subtle);
  display: flex;
  align-items: center;
}
.impact-num {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.2;
}
.impact-lbl {
  font-size: 10px;
  color: var(--color-fg-subtle);
}

/* ===== Disposition ===== */
.disp-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.disp-item {
  display: flex;
  gap: 8px;
  font-size: 12px;
}
.disp-time {
  font-size: 10px;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
  white-space: nowrap;
  padding-top: 1px;
}
.disp-actor {
  font-weight: 500;
  margin-right: 8px;
}
.disp-action {
  color: var(--color-fg-subtle);
}
.disp-comment {
  font-size: 11px;
  color: var(--color-fg-light);
  margin-top: 2px;
  font-style: italic;
}
.disp-input-wrap {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.disp-input {
  flex: 1;
  padding: 4px 8px;
  font-size: 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn, 6px);
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
  outline: none;
}
.disp-input:focus {
  border-color: var(--color-accent-fg);
}

/* ===== Structured Evidence ===== */
.ev-row {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  font-size: 11px;
  line-height: 1.6;
}
.ev-key {
  width: 80px;
  flex-shrink: 0;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ev-val {
  flex: 1;
  color: var(--color-fg-default);
  word-break: break-all;
}

/* ===== JSON Viewer ===== */
.json-viewer {
  background: var(--color-canvas-inset, #f5f5f5);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  max-height: 200px;
  overflow: auto;
}

.json-content {
  margin: 0;
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 400;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-fg-default, #111111);
}

/* ===== IOC Tags ===== */
.ioc-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ioc-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 400;
  border-radius: 4px;
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-danger-fg, #dc2626);
  border: 0.5px solid rgba(220, 38, 38, 0.2);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suggestion-text {
  color: var(--color-fg-muted, #555555);
  line-height: 1.6;
  font-size: 13px;
  font-weight: 400;
}

.related-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rule-item {
  padding: 8px 12px;
  background: var(--color-canvas-inset, #f5f5f5);
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  margin-bottom: 4px;
}

.rule-desc {
  display: block;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  margin-top: 4px;
}

.rule-none {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
}

/* ===== Command Code Block ===== */
.cmd-block {
  background: #1e1e1e;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  padding: 12px;
  overflow-x: auto;
}

.cmd-code {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  font-weight: 400;
  color: #e5e5e5;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}
</style>