<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="username" label="用户名" min-width="150" show-overflow-tooltip />
    <el-table-column prop="is_admin" label="管理员权限" width="110">
      <template #default="{ row }">
        <el-tag :type="row.is_admin ? 'danger' : 'info'" size="small">
          {{ row.is_admin ? '是' : '否' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="is_disabled" label="禁用状态" width="100">
      <template #default="{ row }">
        <el-tag :type="row.is_disabled ? 'warning' : 'success'" size="small">
          {{ row.is_disabled ? '已禁用' : '正常' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="last_logon" label="最后登录" width="180" show-overflow-tooltip />
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})
</script>
