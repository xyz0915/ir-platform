<template>
  <div class="event-table-container">
    <!-- 工具栏 -->
    <div class="table-toolbar">
      <span class="table-hint">共 {{ events.length }} 条事件</span>
      <div class="toolbar-actions">
        <slot name="toolbar"></slot>
      </div>
    </div>

    <!-- 表格 -->
    <el-table
      :data="events"
      :loading="loading"
      stripe
      border
      height="400"
      highlight-current-row
      @row-click="handleRowClick"
      @sort-change="handleSortChange"
    >
      <el-table-column prop="timestamp" label="时间" width="170" sortable="custom">
        <template #default="{ row }">
          <span class="cell-time">{{ formatTime(row.timestamp) }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="event_type" label="类型" width="90">
        <template #default="{ row }">
          <el-tag
            :color="getEventTypeColor(row.event_type)"
            effect="dark"
            size="small"
          >
            {{ getEventTypeLabel(row.event_type) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="severity" label="严重度" width="85" sortable="custom">
        <template #default="{ row }">
          <el-tag
            :color="getSeverityColor(row.severity)"
            effect="dark"
            size="small"
          >
            {{ getSeverityLabel(row.severity) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="status" label="状态" width="80">
        <template #default="{ row }">
          <el-tag
            :style="{ backgroundColor: getStatusColor(row.status), borderColor: getStatusColor(row.status) }"
            effect="dark"
            size="small"
          >
            {{ getStatusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />

      <el-table-column prop="source" label="来源" width="120" show-overflow-tooltip />

      <el-table-column label="Kill Chain" width="100">
        <template #default="{ row }">
          <span v-if="row.kill_chain_stage" class="kill-chain-tag">
            {{ getKillChainLabel(row.kill_chain_stage) }}
          </span>
          <span v-else class="cell-na">-</span>
        </template>
      </el-table-column>

      <el-table-column label="IOC" width="55" align="center">
        <template #default="{ row }">
          <el-icon v-if="row.ioc_hit_id" color="red" :size="18">
            <WarningFilled />
          </el-icon>
          <span v-else class="cell-na">-</span>
        </template>
      </el-table-column>

      <el-table-column label="时效" width="90" align="center" sortable="custom">
        <template #default="{ row }">
          <span
            :class="['cell-elapsed', { 'elapsed-overdue': isOverdue(row.timestamp) }]"
          >
            {{ formatElapsed(row.timestamp) }}
          </span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { WarningFilled } from '@element-plus/icons-vue'
import { SEVERITY, EVENT_TYPE, KILL_CHAIN, SLA, EVENT_STATUS } from '@/constants/design-tokens.js'

const props = defineProps({
  events: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['row-click', 'sort-change'])

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

function isOverdue(ts) {
  if (!ts) return false
  const elapsed = Date.now() - new Date(ts).getTime()
  return elapsed > SLA.TIMEOUT_HOURS * 3600 * 1000
}

function formatElapsed(ts) {
  if (!ts) return '-'
  const elapsed = Date.now() - new Date(ts).getTime()
  const hours = Math.floor(elapsed / (3600 * 1000))
  if (hours < 1) return '< 1h'
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d ${hours % 24}h`
}

function getStatusColor(status) {
  return EVENT_STATUS[status]?.color || EVENT_STATUS.new.color
}

function getStatusLabel(status) {
  return EVENT_STATUS[status]?.label || status || '新建'
}

function handleRowClick(row) {
  emit('row-click', row)
}

function handleSortChange(sort) {
  emit('sort-change', sort)
}
</script>

<style scoped>
.event-table-container {
  margin-top: 16px;
}
.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding: 8px 12px;
  background: var(--color-canvas-subtle, #f5f7fa);
  border-radius: 6px;
  border: 1px solid var(--color-border-default, #e4e7ed);
}
.table-hint {
  font-size: 13px;
  color: var(--color-fg-muted, #909399);
}
.toolbar-actions {
  display: flex;
  gap: 8px;
}
.cell-time {
  font-size: 12px;
  font-family: monospace;
  white-space: nowrap;
}
.cell-na {
  color: #c0c4cc;
}
.cell-elapsed {
  font-size: 12px;
}
.cell-elapsed.elapsed-overdue {
  color: #FF0000;
  font-weight: 600;
}
.kill-chain-tag {
  font-size: 12px;
  color: #606266;
}
</style>
