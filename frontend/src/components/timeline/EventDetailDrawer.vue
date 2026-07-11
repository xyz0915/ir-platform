<template>
  <el-drawer
    :model-value="visible"
    title="事件详情"
    direction="rtl"
    size="480px"
    @close="$emit('close')"
  >
    <template v-if="event">
      <!-- 基本信息 -->
      <el-descriptions :column="1" border size="small" class="detail-descriptions">
        <el-descriptions-item label="时间">
          {{ formatTime(event.timestamp) }}
        </el-descriptions-item>
        <el-descriptions-item label="事件类型">
          <el-tag :color="getEventTypeColor(event.event_type)" effect="dark" size="small">
            {{ getEventTypeLabel(event.event_type) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="严重度">
          <el-tag :color="getSeverityColor(event.severity)" effect="dark" size="small">
            {{ getSeverityLabel(event.severity) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="来源">{{ event.source || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Kill Chain 阶段">{{ getKillChainLabel(event.kill_chain_stage) || '-' }}</el-descriptions-item>
        <el-descriptions-item label="MITRE 技术 ID">{{ event.mitre_technique_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="处置状态">
          <el-tag :style="{ backgroundColor: getStatusColor(event.status), borderColor: getStatusColor(event.status) }" effect="dark" size="small">
            {{ getStatusLabel(event.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="指派给">{{ event.assigned_to || '-' }}</el-descriptions-item>
        <el-descriptions-item label="IOC 命中">
          <el-icon v-if="event.ioc_hit_id" color="red"><WarningFilled /></el-icon>
          <span v-else>否</span>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 描述 -->
      <div class="detail-section">
        <h4 class="section-title">描述</h4>
        <p class="section-content">{{ event.description || '无描述' }}</p>
      </div>

      <!-- 完整 details JSON -->
      <div class="detail-section" v-if="event.details && Object.keys(event.details).length > 0">
        <h4 class="section-title">详细数据</h4>
        <pre class="detail-json">{{ JSON.stringify(event.details, null, 2) }}</pre>
      </div>

      <!-- 状态变更历史 -->
      <div class="detail-section">
        <h4 class="section-title">状态变更历史</h4>
        <el-timeline v-if="auditLogs.length > 0" class="audit-timeline">
          <el-timeline-item
            v-for="(log, idx) in auditLogs"
            :key="idx"
            :timestamp="log.created_at || '-'"
            placement="top"
          >
            <div class="audit-item">
              <span>{{ (log.old_status || '') }} → {{ log.new_status || '' }}</span>
              <span v-if="log.operator" class="audit-operator">操作人: {{ log.operator }}</span>
              <span v-if="log.comment" class="audit-comment">{{ log.comment }}</span>
            </div>
          </el-timeline-item>
        </el-timeline>
        <p v-else class="section-empty">暂无变更记录</p>
      </div>

      <!-- 状态流转操作 -->
      <el-divider />
      <div class="status-controls">
        <h4 class="section-title">处置操作</h4>
        <el-form label-width="80px" size="small">
          <el-form-item label="状态">
            <el-select v-model="statusForm.status" placeholder="选择状态">
              <el-option
                v-for="s in statusOptions"
                :key="s.value"
                :label="s.label"
                :value="s.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="处置备注">
            <el-input
              v-model="statusForm.resolution"
              type="textarea"
              :rows="2"
              placeholder="输入处置备注..."
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="submitting" @click="handleSubmit">
              提交
            </el-button>
          </el-form-item>
        </el-form>
      </div>
    </template>

    <template v-else>
      <div class="drawer-empty">请选择一个事件查看详情</div>
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import { SEVERITY, EVENT_TYPE, KILL_CHAIN, EVENT_STATUS } from '@/constants/design-tokens.js'

const props = defineProps({
  event: { type: Object, default: null },
  visible: { type: Boolean, default: false },
  auditLogs: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'status-updated'])

const submitting = ref(false)

const statusOptions = Object.entries(EVENT_STATUS).map(([value, info]) => ({
  value,
  label: info.label,
}))

const initialStatus = {
  status: '',
  resolution: '',
}

const statusForm = ref({ ...initialStatus })

// 当 event 改变时重置表单
watch(() => props.event, (newVal) => {
  if (newVal) {
    statusForm.value = {
      status: newVal.status || '',
      resolution: newVal.resolution || '',
    }
  } else {
    statusForm.value = { ...initialStatus }
  }
})

function formatTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function getEventTypeColor(type) {
  return EVENT_TYPE.COLOR[type] || EVENT_TYPE.COLOR.other
}

function getEventTypeLabel(type) {
  return EVENT_TYPE.LABEL[type] || type || '其他'
}

function getSeverityColor(severity) {
  return SEVERITY.COLOR[severity] || SEVERITY.COLOR.info
}

function getSeverityLabel(severity) {
  return SEVERITY.LABEL[severity] || severity || '未知'
}

function getKillChainLabel(stage) {
  const found = KILL_CHAIN.STAGES.find(s => s.key === stage)
  return found ? found.label : stage
}

function getStatusColor(status) {
  return EVENT_STATUS[status]?.color || EVENT_STATUS.new.color
}

function getStatusLabel(status) {
  return EVENT_STATUS[status]?.label || status || '新建'
}

async function handleSubmit() {
  if (!statusForm.value.status) {
    ElMessage.warning('请选择处置状态')
    return
  }
  submitting.value = true
  try {
    emit('status-updated', {
      eventId: props.event?.id,
      ...statusForm.value,
    })
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.detail-descriptions {
  margin-bottom: 16px;
}
.detail-section {
  margin-bottom: 16px;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.section-content {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
}
.detail-json {
  font-size: 12px;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
  line-height: 1.5;
}
.section-empty {
  font-size: 13px;
  color: #c0c4cc;
  text-align: center;
  padding: 12px 0;
}
.audit-timeline {
  padding-left: 8px;
}
.audit-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: #606266;
}
.audit-operator {
  color: #909399;
  font-size: 11px;
}
.audit-comment {
  color: #303133;
  font-size: 12px;
  margin-top: 2px;
}
.status-controls {
  margin-top: 16px;
}
.drawer-empty {
  text-align: center;
  color: #c0c4cc;
  padding: 40px 0;
}
</style>
