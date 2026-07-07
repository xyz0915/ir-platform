<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="pid" label="PID" width="80" />
    <el-table-column prop="process_name" label="进程名" width="130" show-overflow-tooltip />
    <el-table-column prop="process_path" label="路径" min-width="200" show-overflow-tooltip />
    <el-table-column prop="command_line" label="命令行" min-width="250" show-overflow-tooltip />
    <el-table-column prop="parent_name" label="父进程" width="120" show-overflow-tooltip />
    <el-table-column prop="rule_name" label="命中规则" min-width="180" show-overflow-tooltip />
    <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
    <el-table-column prop="severity" label="严重程度" width="100">
      <template #default="{ row }">
        <el-tag :type="severityType(row.severity)" size="small">
          {{ row.severity }}
        </el-tag>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})

function severityType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary',
    info: 'info'
  }
  return map[severity] || 'info'
}
</script>
