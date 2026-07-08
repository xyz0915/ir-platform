<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="name" label="服务名" min-width="180" show-overflow-tooltip />
    <el-table-column prop="status" label="状态" width="100">
      <template #default="{ row }">
        <el-tag :type="row.status === 'running' ? 'success' : 'info'" size="small">
          {{ row.status === 'running' ? '运行中' : row.status }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="start_type" label="启动类型" width="120" show-overflow-tooltip />
    <el-table-column prop="binary_path" label="路径" min-width="250" show-overflow-tooltip />
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})
</script>
