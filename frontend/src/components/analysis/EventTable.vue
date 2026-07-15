<template>
  <div class="event-table-wrapper">
    <el-table
      :data="events"
      style="width: 100%"
      :max-height="tableHeight"
      :highlight-current-row="true"
      stripe
      size="small"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
      @sort-change="onSortChange"
    >
      <!-- 多选列 -->
      <el-table-column type="selection" width="40" fixed>
        <template #default="{ row }">
          <span class="checkbox" :class="{ checked: props.selectedIds?.includes(row.id) }" @click.stop />
        </template>
      </el-table-column>

      <!-- 严重等级 -->
      <el-table-column label="等级" width="80" sortable="custom" prop="severity">
        <template #default="{ row }">
          <div class="severity-cell">
            <span class="severity-bar" :style="{ backgroundColor: sevColor(row.severity) }" />
            <span class="severity-badge" :class="'badge-' + (row.severity || 'info')">{{ row.severity }}</span>
          </div>
        </template>
      </el-table-column>

      <!-- 风险分 -->
      <el-table-column label="风险" width="72" sortable="custom" prop="risk_score">
        <template #default="{ row }">
          <div class="rs">
            <span class="rs-val" :style="{ color: riskScoreColor(row._risk_score || 0) }">{{ row._risk_score || '-' }}</span>
            <div class="rs-bar">
              <div class="rs-fill" :style="{ width: (row._risk_score || 0) + '%', background: riskScoreColor(row._risk_score || 0) }"></div>
            </div>
          </div>
        </template>
      </el-table-column>

      <!-- 时间戳 -->
      <el-table-column label="时间" width="170" sortable="custom" prop="timestamp">
        <template #default="{ row }">
          {{ formatTime(row.timestamp) }}
        </template>
      </el-table-column>

      <!-- 事件类型 -->
      <el-table-column label="事件类型" width="120" sortable="custom" prop="event_type">
        <template #default="{ row }">
          <span class="event-type-badge">{{ eventTypeLabel(row.event_type) }}</span>
        </template>
      </el-table-column>

      <!-- 主机 -->
      <el-table-column label="主机" width="140" sortable="custom" prop="host_id">
        <template #default="{ row }">
          <span class="host-name">{{ row.hostname || ('#主机' + row.host_id) }}</span>
          <span v-if="row.ip_address" class="host-ip">({{ row.ip_address }})</span>
        </template>
      </el-table-column>

      <!-- 案件名称 -->
      <el-table-column label="案件" width="120" prop="case_name">
        <template #default="{ row }">
          <span :title="'案件ID: ' + row.case_id" class="case-name-text">{{ row.case_name || ('案件#' + row.case_id) }}</span>
        </template>
      </el-table-column>

      <!-- 摘要 -->
      <el-table-column label="摘要" min-width="200">
        <template #default="{ row }">
          <span class="event-summary">{{ buildSummary(row) }}</span>
        </template>
      </el-table-column>

      <!-- ATT&CK 阶段 -->
      <el-table-column label="ATT&CK 阶段" width="120" sortable="custom" prop="attack_stage">
        <template #default="{ row }">
          <span
            v-if="row.attack_stage"
            class="stage-tag"
          >
            {{ stageLabel(row.attack_stage) }}
          </span>
          <span v-else class="stage-none">—</span>
        </template>
      </el-table-column>

      <!-- IOC 命中 -->
      <el-table-column label="IOC" width="70">
        <template #default="{ row }">
          <span
            v-if="row.ioc_matches && row.ioc_matches.length > 0"
            class="ioc-badge"
          >
            {{ row.ioc_matches.length }}
          </span>
          <span v-else class="ioc-none">—</span>
        </template>
      </el-table-column>

      <!-- 状态 -->
      <el-table-column label="状态" width="100" sortable="custom" prop="status">
        <template #default="{ row }">
          <span class="status-tag" :class="'status-' + row.status">
            {{ statusLabel(row.status) }}
          </span>
        </template>
      </el-table-column>

      <!-- 规则匹配 -->
      <el-table-column label="规则匹配" width="180">
        <template #default="{ row }">
          <div class="c-rt">
            <template v-if="row.matched_rules && row.matched_rules.length">
              <span
                v-for="rule in row.matched_rules.slice(0, 2)"
                :key="rule.rule_id"
                class="rtag"
                :class="'sev-' + (rule.severity || 'info')"
                :title="rule.rule_name + ' (置信度: ' + Math.round((rule.confidence || 0) * 100) + '%)'"
              >
                {{ rule.rule_name }}
                <span class="conf">{{ Math.round((rule.confidence || 0) * 100) }}%</span>
              </span>
              <span v-if="row.matched_rules.length > 2" class="rtag more">
                +{{ row.matched_rules.length - 2 }}
              </span>
            </template>
            <span v-else class="unmatched-badge">未匹配</span>
          </div>
        </template>
      </el-table-column>

      <!-- 负责人 -->
      <el-table-column label="负责人" width="100" sortable="custom" prop="assignee">
        <template #default="{ row }">
          <span v-if="row.assignee" class="assignee-name">{{ row.assignee }}</span>
          <span v-else class="assignee-none">未指派</span>
        </template>
      </el-table-column>

      <!-- 行操作 -->
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <div class="row-actions">
            <button
              v-if="row.status === 'pending'"
              class="action-btn"
              @click.stop="onAction(row.id, 'triaging')"
            >
              分诊
            </button>
            <button
              v-if="row.status === 'triaging'"
              class="action-btn"
              @click.stop="onAction(row.id, 'investigating')"
            >
              调查
            </button>
            <button
              v-if="row.status === 'investigating'"
              class="action-btn action-success"
              @click.stop="onAction(row.id, 'resolved')"
            >
              解决
            </button>
            <button
              v-if="row.status !== 'rejected' && row.status !== 'resolved'"
              class="action-btn action-danger"
              @click.stop="onAction(row.id, 'rejected')"
            >
              误报
            </button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="table-footer">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="currentPageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        small
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  events: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  pagination: { type: Object, default: () => ({ page: 1, pageSize: 50 }) },
  selectedIds: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'select-event',
  'selection-change',
  'page-change',
  'sort-change',
  'update-status',
])

const tableHeight = computed(() => 'calc(100vh - 280px)')
const currentPage = ref(props.pagination.page)
const currentPageSize = ref(props.pagination.pageSize)

// 颜色映射
const SEV_COLORS = {
  critical: '#dc2626', high: '#dc2626', medium: '#d97706',
  low: '#2563eb', info: '#a3a3a3',
}
const STATUS_COLORS = {
  pending: '#a3a3a3', triaging: '#2563eb', investigating: '#d97706',
  resolved: '#16a34a', rejected: '#dc2626',
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
const STATUS_LABELS = {
  pending: '待处理', triaging: '分诊中', investigating: '调查中',
  resolved: '已解决', rejected: '已误报',
}

function sevColor(s) { return SEV_COLORS[s] || '#a3a3a3' }
function statusColor(s) { return STATUS_COLORS[s] || '#a3a3a3' }
function stageLabel(s) { return STAGE_LABELS[s] || s }
function eventTypeLabel(t) { return EVENT_TYPE_LABELS[t] || t }
function statusLabel(s) { return STATUS_LABELS[s] || s }

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function riskScoreColor(score) {
  if (score >= 70) return 'var(--color-risk-critical)'
  if (score >= 50) return 'var(--color-risk-medium)'
  if (score >= 30) return 'var(--color-risk-low)'
  return 'var(--color-fg-subtle)'
}

function calcRiskScore(row) {
  if (row._risk_score !== undefined) return
  let s = { critical: 80, high: 60, medium: 40, low: 20, info: 5 }[row.severity] || 5
  if (row.matched_rules?.length) s += Math.min(row.matched_rules.length * 5, 25)
  if (row.ioc_matches?.length) s += Math.min(row.ioc_matches.length * 15, 30)
  row._risk_score = Math.max(0, Math.min(100, s))
}

watch(() => props.events, (events) => {
  if (events?.length) {
    events.forEach(calcRiskScore)
  }
}, { immediate: true })

function highlightPath(path) {
  if (!path) return ''
  const upper = path.toUpperCase()
  if (upper.includes('TEMP') || upper.includes('APPDATA')) {
    return `<span class="path-critical">${escapeHtml(path)}</span>`
  }
  if (upper.includes('SYSTEM32') || upper.includes('SYSWOW64') || upper.includes('STARTUP')) {
    return `<span class="path-sensitive">${escapeHtml(path)}</span>`
  }
  return escapeHtml(path)
}

function escapeHtml(str) {
  const div = document.createElement('div')
  div.appendChild(document.createTextNode(str))
  return div.innerHTML
}

function buildSummary(row) {
  const ev = row.evidence || {}
  switch (row.event_type) {
    case 'process_start':
    case 'process_terminate': {
      let s = `${ev.process_name || '?'} (PID: ${ev.pid || '?'})`
      if (ev.parent_name) {
        s += ` <span class="pp-info"><span class="pp-sep">←</span> ${ev.parent_name}</span>`
      }
      if (!ev.ppid && row.event_type === 'process_start') {
        s += ` <span class="pp-orphan">孤儿进程</span>`
      }
      return s
    }
    case 'network_outbound':
      return `<span class="net-dir outbound"><svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 1L6 9M6 9L3 6M6 9L9 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span> ${ev.remote_address || '?'}:${ev.remote_port || '?'} <span class="pp-info">→ ${ev.process_name || '?'}</span>`
    case 'network_listen':
      return `<span class="net-dir inbound"><svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 11V3M6 3L3 6M6 3L9 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span> ${ev.local_address || '?'}:${ev.local_port || '?'} <span class="pp-info">● ${ev.process_name || '?'}</span>`
    case 'dns_query':
      return `<span class="net-dir dns"><svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="4" stroke="currentColor" stroke-width="1.3"/><path d="M6 2V10M2 6H10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg></span> ${ev.query || '?'}`
    case 'file_create':
    case 'file_modify':
      return highlightPath(ev.file_name || ev.file_path || '?')
    case 'registry_modify':
    case 'registry_delete':
      return highlightPath(ev.key_path || '?')
    case 'ioc_match':
      return `IOC: ${(row.ioc_matches || []).join(', ') || '?'}`
    case 'behavior_alert':
      return `${ev.rule_name || ev.reason || '?'}`
    case 'user_login':
    case 'user_logout':
      return `${ev.user_name || '?'} 从 ${ev.source_ip || '?'}`
    default:
      return `${row.event_type} on host #${row.host_id}`
  }
}

function onRowClick(row) {
  emit('select-event', row)
}

function onSelectionChange(selection) {
  emit('selection-change', selection.map(s => s.id))
}

function onSortChange({ prop, order }) {
  if (!prop) return
  emit('sort-change', prop, order === 'ascending' ? 'asc' : 'desc')
}

function onPageChange(page) {
  currentPage.value = page
  emit('page-change', page, currentPageSize.value)
}

function onPageSizeChange(size) {
  currentPageSize.value = size
  emit('page-change', 1, size)
}

function onAction(id, status) {
  emit('update-status', { id, status, comment: '' })
}
</script>

<style scoped>
.event-table-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* 覆盖 el-table 样式 */
.event-table-wrapper :deep(.el-table) {
  --el-table-border-color: transparent;
  --el-table-header-bg-color: var(--color-canvas-subtle, #fafafa);
  --el-table-tr-bg-color: var(--color-canvas-default, #ffffff);
  --el-table-row-hover-bg-color: var(--color-canvas-inset, #f5f5f5);
  --el-table-striped-row-bg-color: var(--color-canvas-subtle, #fafafa);
  --el-table-header-text-color: var(--color-fg-subtle, #888888);
  --el-table-text-color: var(--color-fg-default, #111111);
  font-size: 13px;
  font-weight: 400;
  border: none;
}

.event-table-wrapper :deep(.el-table th.el-table__cell) {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle, #888888);
  background: var(--color-canvas-subtle, #fafafa);
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  padding: 8px 0;
}

.event-table-wrapper :deep(.el-table td.el-table__cell) {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  padding: 6px 0;
}

.event-table-wrapper :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: var(--color-canvas-subtle, #fafafa);
}

.event-table-wrapper :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: var(--color-canvas-inset, #f5f5f5);
}

/* 左侧严重度色条行 */
.event-table-wrapper :deep(.el-table__row) {
  border-left: 3px solid transparent;
}

/* 严重度列 */
.severity-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.severity-bar {
  width: 3px;
  height: 16px;
  border-radius: 2px;
  flex-shrink: 0;
}

/* 严重度 badge */
.severity-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 400;
  border-radius: 4px;
  line-height: 1.4;
}

.badge-critical {
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-risk-critical, #dc2626);
  border: 0.5px solid rgba(220, 38, 38, 0.2);
}

.badge-high {
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-risk-critical, #dc2626);
  border: 0.5px solid rgba(220, 38, 38, 0.2);
}

.badge-medium {
  background: var(--color-warning-subtle, #fffbeb);
  color: var(--color-risk-medium, #d97706);
  border: 0.5px solid rgba(217, 119, 6, 0.2);
}

.badge-low {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-risk-low, #2563eb);
  border: 0.5px solid rgba(37, 99, 235, 0.2);
}

.badge-info {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-subtle, #888888);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
}

/* Checkbox */
.checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 3px;
  background: var(--color-canvas-default, #ffffff);
  cursor: pointer;
  transition: all 0.15s;
}

.checkbox.checked {
  background: var(--color-accent-fg, #2563eb);
  border-color: var(--color-accent-fg, #2563eb);
}

.table-footer {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  padding: 8px 12px;
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
}

.event-type-badge {
  font-size: 11px;
  font-weight: 400;
  background: var(--color-canvas-inset, #f5f5f5);
  padding: 2px 8px;
  border-radius: 4px;
  color: var(--color-fg-default, #111111);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
}

.event-summary {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

.stage-tag {
  font-size: 11px;
  font-weight: 400;
  padding: 1px 8px;
  border-radius: 4px;
  white-space: nowrap;
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-default, #111111);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
}

.stage-none, .ioc-none {
  color: var(--color-fg-light, #a3a3a3);
  font-size: 12px;
  font-weight: 400;
}

.ioc-badge {
  display: inline-flex;
  align-items: center;
  padding: 0 6px;
  height: 18px;
  font-size: 11px;
  font-weight: 400;
  border-radius: 4px;
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-danger-fg, #dc2626);
  border: 0.5px solid rgba(220, 38, 38, 0.2);
}

/* 状态标签 */
.status-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 400;
  border-radius: 4px;
  line-height: 1.4;
  border: 0.5px solid transparent;
}

.status-pending {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-subtle, #888888);
  border-color: var(--color-border-default, #e5e5e5);
}

.status-triaging {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
  border-color: rgba(37, 99, 235, 0.2);
}

.status-investigating {
  background: var(--color-warning-subtle, #fffbeb);
  color: var(--color-warning-fg, #d97706);
  border-color: rgba(217, 119, 6, 0.2);
}

.status-resolved {
  background: var(--color-success-subtle, #f0fdf4);
  color: var(--color-success-fg, #16a34a);
  border-color: rgba(22, 163, 74, 0.2);
}

.status-rejected {
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-danger-fg, #dc2626);
  border-color: rgba(220, 38, 38, 0.2);
}

.assignee-name {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
}

.assignee-none {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
  font-style: italic;
}

.row-actions {
  display: flex;
  gap: 8px;
  white-space: nowrap;
}

/* 操作按钮 */
.action-btn {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1;
}

.action-btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
}

.action-btn.action-success {
  color: var(--color-success-fg, #16a34a);
}

.action-btn.action-success:hover {
  background: var(--color-success-subtle, #f0fdf4);
  border-color: var(--color-success-fg, #16a34a);
}

.action-btn.action-danger {
  color: var(--color-danger-fg, #dc2626);
}

.action-btn.action-danger:hover {
  background: var(--color-danger-subtle, #fef2f2);
  border-color: var(--color-danger-fg, #dc2626);
}

.case-name-text { font-size: 13px; font-weight: 400; color: var(--color-fg-default, #111111); }
.host-name { font-weight: 500; font-size: 13px; color: var(--color-fg-default, #111111); }
.host-ip { font-size: 11px; font-weight: 400; color: var(--color-fg-subtle, #888888); margin-left: 4px; }

/* 规则标签 */
.c-rt {
  display: flex;
  gap: 4px;
  flex-wrap: nowrap;
  align-items: center;
}
.rtag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 400;
  border-radius: 4px;
  line-height: 1.4;
  white-space: nowrap;
  border: 0.5px solid transparent;
}
.rtag.sev-critical {
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-risk-critical, #dc2626);
  border-color: rgba(220, 38, 38, 0.2);
}
.rtag.sev-high {
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-risk-critical, #dc2626);
  border-color: rgba(220, 38, 38, 0.2);
}
.rtag.sev-medium {
  background: var(--color-warning-subtle, #fffbeb);
  color: var(--color-risk-medium, #d97706);
  border-color: rgba(217, 119, 6, 0.2);
}
.rtag.sev-low {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-risk-low, #2563eb);
  border-color: rgba(37, 99, 235, 0.2);
}
.rtag.sev-info {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-subtle, #888888);
  border-color: var(--color-border-default, #e5e5e5);
}
.rtag.more {
  background: var(--color-canvas-subtle, #fafafa);
  color: var(--color-fg-subtle, #888888);
  border-color: var(--color-border-default, #e5e5e5);
}
.rtag .conf {
  font-size: 9px;
  opacity: 0.7;
}
.unmatched-badge {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
}

/* 风险分 */
.rs { display: inline-flex; align-items: center; gap: 6px; }
.rs-bar { width: 36px; height: 4px; background: var(--color-canvas-inset); border-radius: 2px; overflow: hidden; }
.rs-fill { height: 100%; border-radius: 2px; }
.rs-val { font-size: 12px; font-weight: 500; width: 22px; text-align: right; }

/* 父进程信息 */
.pp-info { font-size: 12px; color: var(--color-fg-subtle); }
.pp-sep { margin: 0 4px; color: var(--color-fg-light); }
.pp-orphan { display: inline-flex; align-items: center; padding: 0 5px; font-size: 10px; font-weight: 500; background: var(--color-danger-subtle); color: var(--color-danger-fg); border-radius: 3px; margin-left: 4px; }

/* 网络方向图标 */
.net-dir { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; }
.net-dir svg { width: 12px; height: 12px; }
.net-dir.outbound svg { color: var(--color-accent-fg); }
.net-dir.inbound svg { color: var(--color-danger-fg); }
.net-dir.dns svg { color: var(--color-fg-light); }

/* 路径风险着色 */
.path-critical { color: var(--color-danger-fg); font-weight: 500; }
.path-sensitive { color: var(--color-warning-fg); font-weight: 500; }
</style>
