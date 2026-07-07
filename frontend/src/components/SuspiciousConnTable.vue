<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="protocol" label="协议" width="70" />
    <el-table-column label="本地地址" min-width="150">
      <template #default="{ row }">
        {{ row.local_address }}:{{ row.local_port }}
      </template>
    </el-table-column>
    <el-table-column label="远程地址" min-width="150">
      <template #default="{ row }">
        {{ row.remote_address }}:{{ row.remote_port }}
      </template>
    </el-table-column>
    <el-table-column prop="state" label="状态" width="100" />
    <el-table-column prop="process_name" label="进程" width="120" show-overflow-tooltip />
    <el-table-column prop="reason" label="命中原因" min-width="200" show-overflow-tooltip />
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
