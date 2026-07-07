<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="ioc_type" label="IOC 类型" width="100">
      <template #default="{ row }">
        <el-tag size="small">{{ row.ioc_type }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="ioc_value" label="IOC 值" min-width="180" show-overflow-tooltip />
    <el-table-column prop="matched_in" label="命中位置" width="150" show-overflow-tooltip />
    <el-table-column prop="context" label="上下文" min-width="200" show-overflow-tooltip />
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
