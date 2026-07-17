<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
    <el-table-column prop="location" label="位置" min-width="220" show-overflow-tooltip />
    <el-table-column prop="type" label="类型" width="130">
      <template #default="{ row }">
        <el-tag size="small" :type="typeTagType(row.type)" effect="plain" class="startup-type-tag">{{ typeLabel(row.type) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="user" label="用户" width="120" show-overflow-tooltip />
    <el-table-column prop="command" label="启动命令" min-width="250" show-overflow-tooltip />
    <el-table-column prop="reason" label="可疑原因" min-width="200" show-overflow-tooltip />
    <el-table-column prop="rule_name" label="命中规则" min-width="150" show-overflow-tooltip />
    <el-table-column prop="severity" label="严重程度" width="100">
      <template #default="{ row }">
        <el-tag size="small" :type="severityTagType(row.severity)" effect="plain" class="severity-tag">{{ severityLabel(row.severity) }}</el-tag>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})

/** Map startup type to Element Plus tag type */
function typeTagType(type) {
  const map = {
    registry: 'warning',
    folder: 'info',
    scheduled_task: 'primary'
  }
  return map[type] || 'info'
}

/** Map startup type to Chinese label */
function typeLabel(type) {
  const map = {
    registry: '注册表',
    folder: '启动文件夹',
    scheduled_task: '计划任务'
  }
  return map[type] || type
}

/** Map severity level to Element Plus tag type */
function severityTagType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'info',
    info: 'info'
  }
  return map[severity] || 'info'
}

/** Map severity level to Chinese label */
function severityLabel(severity) {
  const map = {
    critical: '严重',
    high: '高危',
    medium: '中危',
    low: '低危',
    info: '信息'
  }
  return map[severity] || severity
}
</script>

<style scoped>
:deep(.el-table) {
  --el-table-border-color: var(--color-border-default, #e5e5e5);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 8px;
  overflow: hidden;
}
:deep(.el-table th.el-table__cell) {
  background: var(--color-canvas-subtle, #fafafa) !important;
  color: var(--color-fg-subtle, #888) !important;
  font-weight: 500 !important;
  font-size: 12px !important;
  padding: 8px 10px !important;
}
:deep(.el-table td.el-table__cell) {
  padding: 6px 8px !important;
  font-size: 12px !important;
  line-height: 1.4 !important;
}
</style>
