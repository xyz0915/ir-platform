<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="friendly_name" label="设备名称" min-width="200" show-overflow-tooltip />
    <el-table-column prop="device_id" label="设备 ID" min-width="200" show-overflow-tooltip />
    <el-table-column prop="device_type" label="设备类型" width="120" />
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})
</script>
