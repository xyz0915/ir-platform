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

    <!-- 原始证据 -->
    <div class="detail-section">
      <div class="section-title">原始证据</div>
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
const props = defineProps({
  event: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'update-status', 'assign', 'view-related'])

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

function sevColor(s) { return SEV_COLORS[s] || '#a3a3a3' }
function stageLabel(s) { return STAGE_LABELS[s] || s }
function eventTypeLabel(t) { return EVENT_TYPE_LABELS[t] || t }

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
