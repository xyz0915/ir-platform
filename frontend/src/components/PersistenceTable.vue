<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="type" label="类型" width="130">
      <template #default="{ row }">
        <el-tag size="small" :type="row.is_suspicious ? 'danger' : 'info'">{{ row.type }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
    <el-table-column prop="command" label="命令" min-width="250" show-overflow-tooltip />
    <el-table-column prop="location" label="位置" min-width="200" show-overflow-tooltip />
    <el-table-column prop="user" label="用户" width="100" />
    <el-table-column label="可疑" width="80">
      <template #default="{ row }">
        <el-tag :type="row.is_suspicious ? 'danger' : 'success'" size="small">
          {{ row.is_suspicious ? '可疑' : '正常' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})
</script>
