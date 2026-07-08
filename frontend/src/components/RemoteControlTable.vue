<template>
  <el-table :data="flatData" border stripe size="small">
    <el-table-column prop="name" label="工具名" width="140" />
    <el-table-column prop="install_path" label="路径" min-width="250" show-overflow-tooltip>
      <template #default="{ row }">
        {{ row.install_path || '-' }}
      </template>
    </el-table-column>
    <el-table-column label="安装状态" width="100">
      <template #default="{ row }">
        <el-tag :type="row.installed ? 'success' : 'info'" size="small">
          {{ row.installed ? '已安装' : '未发现' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="运行状态" width="100">
      <template #default="{ row }">
        <el-tag :type="row.running ? 'warning' : 'info'" size="small">
          {{ row.running ? '运行中' : '未运行' }}
        </el-tag>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: [Array, Object], default: () => [] }
})

const flatData = computed(() => {
  if (Array.isArray(props.data)) return props.data
  return Object.entries(props.data || {}).map(([name, info]) => ({
    name,
    ...info
  }))
})
</script>
