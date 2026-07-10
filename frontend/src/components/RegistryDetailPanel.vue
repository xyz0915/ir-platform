<template>
  <div class="detail-panel" v-loading="loading">
    <el-table :data="items" border stripe size="small" v-if="items.length">
      <el-table-column prop="key_path" label="键路径" min-width="220" show-overflow-tooltip />
      <el-table-column prop="value_name" label="值名称" width="150" show-overflow-tooltip />
      <el-table-column prop="value_type" label="值类型" width="90" />
      <el-table-column prop="value_data" label="值数据" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <code class="mono-code">{{ row.value_data }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="last_write_time" label="最后写入时间" min-width="160" />
    </el-table>
    <el-empty v-else description="暂无注册表数据" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import analysisApi from '@/api/analysis'

const props = defineProps({
  hostId: { type: Number, required: true }
})

const loading = ref(false)
const items = ref([])

onMounted(() => {
  loadData()
})

async function loadData() {
  loading.value = true
  try {
    const res = await analysisApi.getRegistryKeys(props.hostId)
    items.value = res.data || []
  } catch (error) {
    items.value = []
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.detail-panel {
  padding: 12px 0;
}
.mono-code {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  color: #303133;
}
</style>
