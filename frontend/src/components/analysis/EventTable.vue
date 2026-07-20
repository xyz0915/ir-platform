<template>
  <div class="event-table-wrapper" ref="wrapperRef">
    <!-- 批量操作栏 -->
    <div class="batch-bar" v-if="selectedCount >= 2">
      <span class="batch-count">已选 {{ selectedCount }} 条</span>
      <span class="batch-sep"></span>
      <button class="batch-btn" @click="$emit('batch-reject')">标记误报</button>
      <button class="batch-btn" @click="$emit('batch-assign')">指派</button>
      <button class="batch-btn" @click="$emit('batch-link-case')">关联案件</button>
      <button class="batch-btn" @click="$emit('batch-export')">导出</button>
      <button class="batch-btn batch-cancel" @click="$emit('clear-selection')">取消选择</button>
    </div>
    <!-- 自定义列选择器 -->
    <div class="col-picker">
      <el-dropdown trigger="click" @command="toggleCol">
        <button class="col-picker-btn">
          自定义列 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="c in allColumns" :key="c.key" :command="c.key">
              <span class="col-pick-item">
                <span class="col-pick-check">{{ colVis[c.key] ? '☑' : '☐' }}</span>
                {{ c.label }}
              </span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
    <el-table
      :data="events"
      style="width: 100%"
      :height="tableHeight"
      :highlight-current-row="true"
      :row-class-name="rowClassName"
      stripe
      size="small"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
      @sort-change="onSortChange"
    >
      <!-- 书签列 -->
      <el-table-column width="30" fixed>
        <template #default="{ row }">
          <span class="bm-icon" :class="{ active: store.isBookmarked(row.id) }"
                @click.stop="store.toggleBookmark(row.id)">
            {{ store.isBookmarked(row.id) ? '⚑' : '⚐' }}
          </span>
        </template>
      </el-table-column>
      <!-- 多选列 -->
      <el-table-column type="selection" width="40" fixed>
        <template #default="{ row }">
          <span class="checkbox" :class="{ checked: props.selectedIds?.includes(row.id) }" @click.stop />
        </template>
      </el-table-column>

      <!-- 严重等级 -->
      <el-table-column v-if="colVis.severity" label="等级" width="80" sortable="custom" prop="severity">
        <template #default="{ row }">
          <div class="severity-cell">
            <span class="severity-bar" :style="{ backgroundColor: sevColor(row.severity) }" />
            <span class="severity-badge" :class="'badge-' + (row.severity || 'info')">{{ row.severity }}</span>
          </div>
        </template>
      </el-table-column>

      <!-- 风险分 -->
      <el-table-column v-if="colVis.risk_score" label="风险" width="72" sortable="custom" prop="risk_score">
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
      <el-table-column v-if="colVis.timestamp" label="时间" width="170" sortable="custom" prop="timestamp">
        <template #default="{ row }">
          {{ formatTime(row.timestamp) }}
        </template>
      </el-table-column>

      <!-- T-code / 事件类型 -->
      <el-table-column v-if="colVis.t_code" label="T-code" width="90" sortable="custom" prop="t_code">
        <template #default="{ row }">
          <span class="tcode-badge">{{ row.t_code || '—' }}</span>
          <span class="etype-sub">{{ eventTypeLabel(row.event_type) }}</span>
        </template>
      </el-table-column>

      <!-- 案件名称 -->
      <el-table-column v-if="colVis.case_name" label="案件" width="120" prop="case_name">
        <template #default="{ row }">
          <span :title="'案件ID: ' + row.case_id" class="case-name-text">{{ row.case_name || ('案件#' + row.case_id) }}</span>
        </template>
      </el-table-column>

      <!-- 主机 -->
      <el-table-column v-if="colVis.hostname" label="主机" width="140" sortable="custom" prop="host_id">
        <template #default="{ row }">
          <span class="host-name">{{ row.hostname || ('#主机' + row.host_id) }}</span>
          <span v-if="row.ip_address" class="host-ip">({{ row.ip_address }})</span>
        </template>
      </el-table-column>

      <!-- ATT&CK 阶段 -->
      <el-table-column v-if="colVis.attack_stage" label="ATT&CK 阶段" width="120" sortable="custom" prop="attack_stage">
        <template #default="{ row }">
          <span
            v-if="row.attack_stage"
            class="stage-tag" :class="`stage-${row.attack_stage || 'default'}`"
          >
            {{ stageLabel(row.attack_stage) }}
          </span>
          <span v-else class="stage-none">—</span>
        </template>
      </el-table-column>

      <!-- 摘要 -->
      <el-table-column v-if="colVis.summary" label="摘要" min-width="200">
        <template #default="{ row }">
          <span class="summary-cell" :title="row.summary">{{ row.summary || eventTypeLabel(row.event_type) || '—' }}</span>
        </template>
      </el-table-column>

      <!-- AI 分析 -->
      <el-table-column v-if="colVis.ai_analysis && hasAiContent" label="AI分析" min-width="200">
        <template #default="{ row }">
          <div class="summary-wrap" v-if="row.event_type === 'ai_recommended' || row.ai_analysis || getVerdictLabel(row)">
            <span v-if="getVerdictLabel(row)" class="verdict-tag-sm" :class="'vlabel-' + getVerdictLabel(row)">{{ verdictShort(getVerdictLabel(row)) }}</span>
            <span v-if="row.event_type === 'ai_recommended' || row.ai_analysis" class="ai-badge-sm">🤖 AI</span>
            <span class="ai-text-cell" :title="row.ai_analysis">{{ row.ai_analysis }}</span>
          </div>
          <span v-else class="summary-cell">—</span>
        </template>
      </el-table-column>

      <!-- 状态 -->
      <el-table-column v-if="colVis.status" label="状态" width="100" sortable="custom" prop="status">
        <template #default="{ row }">
          <span class="status-tag" :class="'status-' + row.status">
            {{ statusLabel(row.status) }}
          </span>
        </template>
      </el-table-column>

      <!-- 告警来源 -->
      <el-table-column v-if="colVis.source" label="来源" width="80" prop="source">
        <template #default="{ row }">
          <span class="source-tag" :class="'src-' + (row.source || '未知')">{{ row.source || '—' }}</span>
        </template>
      </el-table-column>

      <!-- 规则匹配 -->
      <el-table-column v-if="colVis.matched_rules" label="规则匹配" width="200">
        <template #default="{ row }">
          <div class="c-rt">
            <template v-if="row.matched_rules && row.matched_rules.length">
              <span
                v-for="rule in row.matched_rules.slice(0, 1)"
                :key="rule.rule_id"
                class="rtag"
                :class="['sev-' + (rule.severity || 'info'), rule.severity === 'critical' || rule.severity === 'high' ? 'rtag-bang' : '']"
                :title="rule.rule_name + ' (置信度: ' + Math.round((rule.confidence || 0) * 100) + '%)'"
              >
                <span class="rtag-name">{{ rule.rule_name }}</span>
                <span class="conf">{{ Math.round((rule.confidence || 0) * 100) }}%</span>
              </span>
              <span v-if="row.matched_rules.length > 1" class="rtag more" :title="row.matched_rules.slice(1).map(r => r.rule_name).join('; ')">
                +{{ row.matched_rules.length - 1 }}
              </span>
            </template>
            <span v-else class="unmatched-badge">未匹配</span>
          </div>
        </template>
      </el-table-column>

      <!-- 额外可选列 -->
      <el-table-column v-if="colVis.event_type" label="事件类型" width="120" prop="event_type" sortable="custom">
        <template #default="{ row }">{{ eventTypeLabel(row.event_type) }}</template>
      </el-table-column>
      <el-table-column v-if="colVis.source_collector" label="采集器" width="100" prop="source_collector">
        <template #default="{ row }">{{ row.source_collector || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="colVis.attack_chain_id" label="攻击链ID" width="150" prop="attack_chain_id">
        <template #default="{ row }">{{ row.attack_chain_id || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="colVis.assignee" label="负责人" width="100" prop="assignee" sortable="custom">
        <template #default="{ row }">{{ row.assignee || '—' }}</template>
      </el-table-column>
      <el-table-column v-if="colVis.ai_verdict" label="AI研判" width="90" prop="ai_verdict">
        <template #default="{ row }">
          <span v-if="row.ai_verdict?.label" class="verdict-tag-sm" :class="'vlabel-' + row.ai_verdict.label">
            {{ verdictShort(row.ai_verdict.label) }}
          </span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column v-if="colVis.created_at" label="入库时间" width="170" prop="created_at">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
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
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'
import { ArrowDown } from '@element-plus/icons-vue'

const store = useAnalysisStore()

// 自定义列配置
const COL_KEY = 'event_table_cols'
const DEFAULT_COLS = {
  severity: true, risk_score: true, timestamp: true, t_code: true,
  case_name: true, hostname: true, attack_stage: true, summary: true,
  ai_analysis: true, status: true, source: true, matched_rules: true,
  event_type: false, source_collector: false, attack_chain_id: false,
  assignee: false, ai_verdict: false, created_at: false,
}

function loadColVis() {
  try {
    const saved = JSON.parse(localStorage.getItem(COL_KEY))
    if (saved) return { ...DEFAULT_COLS, ...saved }
  } catch {}
  return { ...DEFAULT_COLS }
}
const colVis = reactive(loadColVis())

function toggleCol(key) {
  colVis[key] = !colVis[key]
  const toSave = {}
  for (const k in colVis) toSave[k] = colVis[k]
  localStorage.setItem(COL_KEY, JSON.stringify(toSave))
}

const allColumns = [
  { key: 'severity', label: '等级' },
  { key: 'risk_score', label: '风险' },
  { key: 'timestamp', label: '时间' },
  { key: 't_code', label: 'T-code' },
  { key: 'case_name', label: '案件' },
  { key: 'hostname', label: '主机' },
  { key: 'attack_stage', label: 'ATT&CK 阶段' },
  { key: 'summary', label: '摘要' },
  { key: 'ai_analysis', label: 'AI分析' },
  { key: 'status', label: '状态' },
  { key: 'source', label: '来源' },
  { key: 'matched_rules', label: '规则匹配' },
  { key: 'event_type', label: '事件类型' },
  { key: 'source_collector', label: '采集器' },
  { key: 'attack_chain_id', label: '攻击链ID' },
  { key: 'assignee', label: '负责人' },
  { key: 'ai_verdict', label: 'AI研判标签' },
  { key: 'created_at', label: '入库时间' },
]

const props = defineProps({
  events: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  pagination: { type: Object, default: () => ({ page: 1, pageSize: 50 }) },
  selectedIds: { type: Array, default: () => [] },
})

const selectedCount = computed(() => props.selectedIds?.length || 0)

const emit = defineEmits([
  'select-event',
  'selection-change',
  'page-change',
  'sort-change',
  'update-status',
  'batch-reject',
  'batch-assign',
  'batch-link-case',
  'batch-export',
  'clear-selection',
])

// 动态表格高度: ResizeObserver 跟踪父容器实际高度
const wrapperRef = ref(null)
const wrapperHeight = ref(0)
let resizeObserver = null
const PAGINATION_HEIGHT = 48

const tableHeight = computed(() => {
  if (wrapperHeight.value > 0) {
    return Math.max(wrapperHeight.value - PAGINATION_HEIGHT, 200)
  }
  return 'calc(100vh - 510px)'
})

onMounted(() => {
  if (wrapperRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        wrapperHeight.value = entry.contentRect.height
      }
    })
    resizeObserver.observe(wrapperRef.value)
  }
})

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
})
const currentPage = ref(props.pagination.page)
const currentPageSize = ref(props.pagination.pageSize)

// 同步父组件传过来的 pagination 变更（视图切换/案件切换时会重置页码）
watch(() => props.pagination?.page, (newPage) => {
  if (newPage && newPage !== currentPage.value) {
    currentPage.value = newPage
  }
})
watch(() => props.pagination?.pageSize, (newSize) => {
  if (newSize && newSize !== currentPageSize.value) {
    currentPageSize.value = newSize
  }
})

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

// 检查当前数据中是否有 AI 分析内容，控制 AI 分析列显示
const hasAiContent = computed(() => {
  return props.events?.some(r => r.event_type === 'ai_recommended' || r.ai_analysis || getVerdictLabel(r))
})

// 从列表行中解析 ai_verdict（列表接口返回为 JSON 字符串）取出 label
function getVerdictLabel(row) {
  const raw = row?.ai_verdict
  if (!raw) return ''
  let v = raw
  if (typeof raw === 'string') {
    try { v = JSON.parse(raw) } catch { return '' }
  }
  return (v && v.label) ? v.label : ''
}

// label → 中文短标签
function verdictShort(label) {
  const m = { suspicious: '可疑', false_positive: '误报', benign: '良性', unknown: '降级' }
  return m[label] || label
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

// §10.3 高亮机制：ioc_hit / 融合场景命中时行加红色徽标
function rowClassName({ row }) {
  if (row.event_type === 'ai_recommended') return 'row-ai-recommended'
  if (row.ioc_matches?.length) return 'row-ioc-hit'
  if (row.fusion_scene) return 'row-ioc-hit'
  return ''
}
</script>

<style scoped>
.event-table-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-default, #ffffff);
  border-radius: 8px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  overflow: hidden;
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

/* 批量操作栏 */
.batch-bar { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: var(--color-accent-subtle, #eff6ff); border-radius: 6px; margin-bottom: 6px; font-size: 12px; }
.batch-count { font-weight: 600; color: var(--color-accent-fg, #2563eb); }
.batch-sep { width: 1px; height: 16px; background: var(--color-border-default); }
.batch-btn { padding: 3px 10px; border: 0.5px solid var(--color-border-default); border-radius: 4px; background: #fff; cursor: pointer; font-size: 12px; }
.batch-btn:hover { background: var(--color-canvas-subtle); }
.batch-cancel { margin-left: auto; color: var(--color-fg-subtle); }

.event-table-wrapper :deep(.el-table th.el-table__cell) {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle, #888888);
  background: var(--color-canvas-subtle, #fafafa);
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  padding: 6px 0;
}

.event-table-wrapper :deep(.el-table td.el-table__cell) {
  font-size: 12.5px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  border-bottom: 0.5px solid var(--color-border-default, #ebebeb);
  padding: 4px 0;
}

.event-table-wrapper :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: var(--color-canvas-subtle, #fafafa);
}

.event-table-wrapper :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: var(--color-accent-subtle, #eff6ff) !important;
}
.event-table-wrapper :deep(.el-table__body tr.current-row > td.el-table__cell) {
  background: var(--color-accent-subtle, #eff6ff) !important;
}

/* 书签图标 */
.bm-icon { cursor: pointer; font-size: 15px; opacity: 0.35; transition: all 0.15s; user-select: none; }
.bm-icon:hover { opacity: 0.8; transform: scale(1.2); }
.bm-icon.active { opacity: 1; color: #f59e0b; }

/* 列选择器 */
.col-picker { display: flex; justify-content: flex-end; margin-bottom: 4px; }
.col-picker-btn { padding: 3px 10px; font-size: 11px; border: 0.5px solid var(--color-border-default); border-radius: 4px; background: var(--color-canvas-default); cursor: pointer; color: var(--color-fg-subtle); display: inline-flex; align-items: center; gap: 4px; }
.col-picker-btn:hover { background: var(--color-canvas-subtle); color: var(--color-fg-default); }
.col-pick-item { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.col-pick-check { font-size: 14px; }

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

/* T-code 徽标 */
.tcode-badge {
  display: inline-block;
  font-family: 'Courier New', monospace;
  font-size: 11px;
  font-weight: 600;
  background: linear-gradient(135deg, #ede9fe, #ddd6fe);
  color: #5b21b6;
  padding: 1px 6px;
  border-radius: 4px;
  border: 0.5px solid #c4b5fd;
  margin-right: 4px;
}
.etype-sub {
  font-size: 10px;
  color: var(--color-fg-light, #a3a3a3);
  white-space: nowrap;
}

/* 告警来源标签 */
.source-tag {
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 10px;
  white-space: nowrap;
}
.src-规则引擎 {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
  border: 0.5px solid rgba(37,99,235,0.2);
}
.src-行为分析 {
  background: var(--color-warning-subtle, #fffbeb);
  color: var(--color-risk-medium, #d97706);
  border: 0.5px solid rgba(217,119,6,0.2);
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
  display: inline-block;
  font-size: 10.5px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
  background: linear-gradient(135deg, #ede9fe, #ddd6fe);
  color: #5b21b6;
  border: 0.5px solid #c4b5fd;
}

.stage-persistence { background: linear-gradient(135deg, #fed7aa, #fdba74); color: #9a3412; border-color: #fb923c; }
.stage-execution { background: linear-gradient(135deg, #fecaca, #fca5a5); color: #991b1b; border-color: #f87171; }
.stage-discovery { background: linear-gradient(135deg, #bfdbfe, #93c5fd); color: #1e40af; border-color: #60a5fa; }
.stage-credential_access { background: linear-gradient(135deg, #fef08a, #fde047); color: #854d0e; border-color: #facc15; }
.stage-lateral_movement { background: linear-gradient(135deg, #fbcfe8, #f9a8d4); color: #9d174d; border-color: #f472b6; }
.stage-collection { background: linear-gradient(135deg, #a7f3d0, #6ee7b7); color: #065f46; border-color: #34d399; }
.stage-defense_evasion { background: linear-gradient(135deg, #fde68a, #fcd34d); color: #92400e; border-color: #fbbf24; }

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
  padding: 2px 8px;
  font-size: 10.5px;
  font-weight: 500;
  border-radius: 10px;
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
  gap: 3px;
  flex-wrap: nowrap;
  align-items: center;
}
.rtag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 7px;
  font-size: 10.5px;
  font-weight: 500;
  border-radius: 10px;
  line-height: 1.5;
  white-space: nowrap;
  border: 0.5px solid transparent;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rtag-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 130px;
}
.rtag.rtag-bang {
  box-shadow: 0 0 0 1px rgba(220, 38, 38, 0.3), 0 0 6px rgba(220, 38, 38, 0.1);
}
.rtag.sev-critical {
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-risk-critical, #dc2626);
  border-color: rgba(220, 38, 38, 0.2);
  font-weight: 600;
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
  font-size: 9.5px;
  font-weight: 500;
}
.rtag .conf {
  font-size: 9px;
  opacity: 0.75;
  font-weight: 400;
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

/* v2.1 摘要列 */
.summary-cell {
  display: block;
  font-size: 12px;
  line-height: 1.4;
  color: var(--color-fg-default);
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 高亮行：ioc/融合场景命中 */
:deep(.el-table .row-ioc-hit) {
  background: rgba(220, 38, 38, 0.04) !important;
}
:deep(.el-table .row-ioc-hit:hover > td) {
  background: rgba(220, 38, 38, 0.08) !important;
}
/* AI 推荐行 */
:deep(.el-table .row-ai-recommended) {
  background: rgba(22, 163, 74, 0.04) !important;
}
:deep(.el-table .row-ai-recommended:hover > td) {
  background: rgba(22, 163, 74, 0.08) !important;
}

/* AI 小徽标（摘要列内嵌） */
.ai-badge-sm {
  display: inline-flex;
  align-items: center;
  font-size: 10px;
  padding: 0 5px;
  margin-right: 4px;
  border-radius: 3px;
  background: #16a34a;
  color: #fff;
  flex-shrink: 0;
}

/* 已研判标记（读 row.ai_verdict.label） */
.verdict-tag-sm {
  display: inline-flex;
  align-items: center;
  font-size: 10px;
  font-weight: 600;
  padding: 0 5px;
  margin-right: 4px;
  border-radius: 3px;
  flex-shrink: 0;
}
.verdict-tag-sm.vlabel-suspicious { background: rgba(217,119,6,0.15); color: #d97706; }
.verdict-tag-sm.vlabel-false_positive { background: rgba(163,163,163,0.15); color: #6b7280; }
.verdict-tag-sm.vlabel-benign { background: rgba(22,163,74,0.15); color: #16a34a; }
.verdict-tag-sm.vlabel-unknown { background: rgba(100,116,139,0.15); color: #64748b; }
.summary-wrap {
  display: flex;
  align-items: center;
}

/* AI 分析文本（独立列） */
.ai-text-cell {
  display: inline-block;
  font-size: 11px;
  line-height: 1.3;
  color: var(--color-fg-default, #111111);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 400;
}

/* 事件分类标签 */
.category-tag {
  display: inline-block;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
}
.category-tag.cat-behavior {
  background: rgba(220, 38, 38, 0.1);
  color: var(--color-danger-fg);
}

/* 事件ID */
.event-id-text {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: var(--color-fg-light);
}

/* 攻击链 */
.chain-text {
  font-size: 11px;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
}
</style>
