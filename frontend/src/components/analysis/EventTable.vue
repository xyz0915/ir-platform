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
      <el-table-column type="selection" width="40" fixed />

      <!-- 严重等级 -->
      <el-table-column label="等级" width="80" sortable="custom" prop="severity">
        <template #default="{ row }">
          <span class="severity-dot" :style="{ backgroundColor: sevColor(row.severity) }" />
          <span class="severity-text">{{ row.severity }}</span>
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
      <el-table-column label="主机" width="100" sortable="custom" prop="host_id">
        <template #default="{ row }">
          #{{ row.host_id }}
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
            :style="{ backgroundColor: stageColor(row.attack_stage), color: '#333' }"
          >
            {{ stageLabel(row.attack_stage) }}
          </span>
          <span v-else class="stage-none">—</span>
        </template>
      </el-table-column>

      <!-- IOC 命中 -->
      <el-table-column label="IOC" width="70">
        <template #default="{ row }">
          <el-tag
            v-if="row.ioc_matches && row.ioc_matches.length > 0"
            size="small"
            type="danger"
          >
            {{ row.ioc_matches.length }}
          </el-tag>
          <span v-else class="ioc-none">—</span>
        </template>
      </el-table-column>

      <!-- 状态 -->
      <el-table-column label="状态" width="100" sortable="custom" prop="status">
        <template #default="{ row }">
          <el-tag :color="statusColor(row.status)" size="small" effect="dark">
            {{ statusLabel(row.status) }}
          </el-tag>
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
            <el-button
              v-if="row.status === 'pending'"
              size="small"
              type="primary"
              link
              @click.stop="onAction(row.id, 'triaging')"
            >
              分诊
            </el-button>
            <el-button
              v-if="row.status === 'triaging'"
              size="small"
              type="warning"
              link
              @click.stop="onAction(row.id, 'investigating')"
            >
              调查
            </el-button>
            <el-button
              v-if="row.status === 'investigating'"
              size="small"
              type="success"
              link
              @click.stop="onAction(row.id, 'resolved')"
            >
              解决
            </el-button>
            <el-button
              v-if="row.status !== 'rejected' && row.status !== 'resolved'"
              size="small"
              type="danger"
              link
              @click.stop="onAction(row.id, 'rejected')"
            >
              误报
            </el-button>
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
import { ref, computed } from 'vue'

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
  critical: '#DC2626', high: '#EF4444', medium: '#EAB308',
  low: '#3B82F6', info: '#9CA3AF',
}
const STATUS_COLORS = {
  pending: '#9CA3AF', triaging: '#3B82F6', investigating: '#F97316',
  resolved: '#22C55E', rejected: '#EF4444',
}
const STAGE_COLORS = {
  initial_access: '#FFE0E0', execution: '#FFF3E0', persistence: '#FFFDE7',
  privilege_escalation: '#F3E5F5', defense_evasion: '#E8EAF6',
  credential_access: '#E0F2F1', discovery: '#E8F5E9',
  lateral_movement: '#FFF3E0', collection: '#FCE4EC',
  command_and_control: '#EFEBE9', exfiltration: '#FFEBEE',
  impact: '#FFCDD2', unknown: '#F5F5F5',
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

function sevColor(s) { return SEV_COLORS[s] || '#9CA3AF' }
function statusColor(s) { return STATUS_COLORS[s] || '#9CA3AF' }
function stageColor(s) { return STAGE_COLORS[s] || '#F5F5F5' }
function stageLabel(s) { return STAGE_LABELS[s] || s }
function eventTypeLabel(t) { return EVENT_TYPE_LABELS[t] || t }
function statusLabel(s) { return STATUS_LABELS[s] || s }

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function buildSummary(row) {
  const ev = row.evidence || {}
  switch (row.event_type) {
    case 'process_start':
    case 'process_terminate':
      return `${ev.process_name || '?'} (PID: ${ev.pid || '?'})`
    case 'network_outbound':
    case 'network_listen':
      return `${ev.remote_address || '?'}:${ev.remote_port || '?'} → ${ev.process_name || '?'}`
    case 'dns_query':
      return `${ev.query || '?'} (${ev.query_type || 'A'})`
    case 'file_create':
    case 'file_modify':
      return `${ev.file_name || ev.file_path || '?'}`
    case 'registry_modify':
    case 'registry_delete':
      return `${ev.key_path || '?'}`
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

.table-footer {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  padding: 8px 12px;
  border-top: 1px solid #e5e7eb;
  background: #fff;
}

.severity-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}

.severity-text {
  font-size: 12px;
  vertical-align: middle;
}

.event-type-badge {
  font-size: 11px;
  background: #f3f4f6;
  padding: 2px 6px;
  border-radius: 4px;
  color: #374151;
}

.event-summary {
  font-size: 12px;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

.stage-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.stage-none, .ioc-none {
  color: #9ca3af;
  font-size: 12px;
}

.assignee-name {
  font-size: 12px;
  color: #374151;
}

.assignee-none {
  font-size: 12px;
  color: #9ca3af;
  font-style: italic;
}

.row-actions {
  display: flex;
  gap: 4px;
  white-space: nowrap;
}
</style>
