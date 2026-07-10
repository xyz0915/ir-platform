<template>
  <el-table :data="data" border stripe size="small" row-key="id">
    <el-table-column type="expand">
      <template #default="{ row }">
        <WmiDetailPanel v-if="row.type === 'wmi'" :host-id="hostId" />
        <RegistryDetailPanel v-else-if="row.type === 'registry'" :host-id="hostId" />
        <div v-else class="expand-empty">该类型暂无详细信息</div>
      </template>
    </el-table-column>
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
import WmiDetailPanel from '@/components/WmiDetailPanel.vue'
import RegistryDetailPanel from '@/components/RegistryDetailPanel.vue'

defineProps({
  data: { type: Array, default: () => [] },
  hostId: { type: Number, default: null }
})
</script>

<style scoped>
.expand-empty {
  padding: 16px;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
</style>
