<template>
  <div class="event-detail-panel">
    <!-- 标题栏 -->
    <div class="detail-header">
      <div class="header-left">
        <span class="severity-badge" :style="{ backgroundColor: sevColor(event.severity) }">
          {{ event.severity }}
        </span>
        <span class="event-id" :title="event.id">
          {{ event.id ? event.id.substring(0, 12) + '...' : '' }}
        </span>
      </div>
      <el-button text size="small" @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </el-button>
    </div>

    <!-- 基本信息 -->
    <div class="detail-section">
      <div class="info-row">
        <span class="info-label">时间</span>
        <span class="info-value">{{ formatTime(event.timestamp) }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">类型</span>
        <span class="info-value">{{ eventTypeLabel(event.event_type) }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">主机</span>
        <span class="info-value">#{{ event.host_id }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">采集器</span>
        <span class="info-value">{{ event.source_collector || '—' }}</span>
      </div>
      <div class="info-row" v-if="event.case_id">
        <span class="info-label">案件 ID</span>
        <span class="info-value">{{ event.case_id }}</span>
      </div>
      <div class="info-row" v-if="event.import_id">
        <span class="info-label">日志 ID</span>
        <span class="info-value">{{ event.import_id }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">攻击链</span>
        <span class="info-value">{{ event.attack_chain_id || '—' }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">ATT&CK</span>
        <span class="info-value">
          {{ event.attack_stage ? stageLabel(event.attack_stage) : '—' }}
        </span>
      </div>
      <div class="info-row">
        <span class="info-label">负责人</span>
        <span class="info-value">{{ event.assignee || '未指派' }}</span>
      </div>
    </div>

    <!-- 处置操作 -->
    <div class="detail-section">
      <div class="section-title">处置操作</div>
      <div class="action-buttons">
        <el-button
          v-if="event.status === 'pending'"
          size="small"
          type="primary"
          @click="onStatusChange('triaging')"
        >
          开始分诊
        </el-button>
        <el-button
          v-if="event.status === 'triaging'"
          size="small"
          type="warning"
          @click="onStatusChange('investigating')"
        >
          进入调查
        </el-button>
        <el-button
          v-if="event.status === 'investigating'"
          size="small"
          type="success"
          @click="onStatusChange('resolved')"
        >
          标记解决
        </el-button>
        <el-button
          v-if="event.status !== 'rejected' && event.status !== 'resolved'"
          size="small"
          type="danger"
          plain
          @click="onStatusChange('rejected')"
        >
          标记误报
        </el-button>
        <el-button
          v-if="event.status === 'resolved'"
          size="small"
          type="warning"
          plain
          @click="onStatusChange('investigating')"
        >
          重新开案
        </el-button>
      </div>
    </div>

    <!-- 证据 JSON -->
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
        <el-tag
          v-for="ioc in event.ioc_matches"
          :key="ioc"
          size="small"
          type="danger"
          class="ioc-tag"
        >
          {{ ioc }}
        </el-tag>
      </div>
    </div>

    <!-- 处置建议（静态） -->
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
        <el-button
          v-for="rid in event.related_events"
          :key="rid"
          link
          size="small"
          @click="onViewRelated(rid)"
        >
          {{ rid.substring(0, 12) + '...' }}
        </el-button>
      </div>
    </div>

    <!-- 查看原始日志（条件渲染） -->
    <div class="detail-section" v-if="event.import_id">
      <div class="section-title">原始日志</div>
      <el-button
        link
        type="primary"
        size="small"
        @click="viewRawLog"
      >
        查看原始日志 →
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { Close } from '@element-plus/icons-vue'

const props = defineProps({
  event: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'update-status', 'assign', 'view-related'])

const SEV_COLORS = {
  critical: '#DC2626', high: '#EF4444', medium: '#EAB308',
  low: '#3B82F6', info: '#9CA3AF',
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

function sevColor(s) { return SEV_COLORS[s] || '#9CA3AF' }
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

function viewRawLog() {
  const caseId = props.event.case_id || ''
  const hostId = props.event.host_id || ''
  const importId = props.event.import_id || ''
  window.open(`/log-search?case_id=${caseId}&host_id=${hostId}&import_id=${importId}`, '_blank')
}
</script>

<style scoped>
.event-detail-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  font-size: 12px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #e5e7eb;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.severity-badge {
  padding: 1px 6px;
  border-radius: 4px;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
}

.event-id {
  font-size: 11px;
  color: #6b7280;
  font-family: monospace;
}

.detail-section {
  padding: 8px 12px;
  border-bottom: 1px solid #f3f4f6;
}

.section-title {
  font-size: 11px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 6px;
}

.info-row {
  display: flex;
  margin-bottom: 4px;
}

.info-label {
  width: 60px;
  flex-shrink: 0;
  color: #9ca3af;
}

.info-value {
  color: #374151;
  flex: 1;
  word-break: break-all;
}

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.json-viewer {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  max-height: 200px;
  overflow: auto;
}

.json-content {
  margin: 0;
  padding: 8px;
  font-size: 11px;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
}

.ioc-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ioc-tag {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suggestion-text {
  color: #6b7280;
  line-height: 1.5;
}

.related-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
</style>
