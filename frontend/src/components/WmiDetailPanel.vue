<template>
  <div class="detail-panel" v-loading="loading">
    <el-table :data="items" border stripe size="small" v-if="items.length">
      <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
      <el-table-column label="EventFilter" min-width="300">
        <template #default="{ row }">
          <pre class="json-pre">{{ formatJson(row.event_filter) }}</pre>
        </template>
      </el-table-column>
      <el-table-column label="EventConsumer" min-width="300">
        <template #default="{ row }">
          <pre class="json-pre">{{ formatJson(row.event_consumer) }}</pre>
        </template>
      </el-table-column>
      <el-table-column prop="binding_type" label="绑定类型" width="120" />
      <el-table-column label="风险等级" width="100">
        <template #default="{ row }">
          <el-tag :type="riskTagType(row.risk_level)" size="small">
            {{ row.risk_level || '未知' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无 WMI 订阅数据" />
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
    const res = await analysisApi.getWmiSubscriptions(props.hostId)
    items.value = res.data || []
  } catch (error) {
    items.value = []
  } finally {
    loading.value = false
  }
}

function formatJson(value) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return JSON.stringify(parsed, null, 2)
    } catch {
      return value
    }
  }
  return JSON.stringify(value, null, 2)
}

function riskTagType(level) {
  const map = {
    high: 'danger',
    critical: 'danger',
    medium: 'warning',
    low: 'info',
  }
  return map[level] || 'info'
}
</script>

<style scoped>
.detail-panel {
  padding: 12px 0;
}
.json-pre {
  margin: 0;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow-y: auto;
  background: #f5f7fa;
  padding: 6px 8px;
  border-radius: 4px;
}
</style>
