<template>
  <div class="system-params-view">
    <div class="page-header">
      <h2>系统参数</h2>
    </div>

    <el-table :data="paramList" border stripe style="width: 100%" v-loading="loading">
      <el-table-column label="参数名" width="280">
        <template #default="{ row }">
          <code class="param-key">{{ row.key }}</code>
        </template>
      </el-table-column>
      <el-table-column label="当前值" width="200">
        <template #default="{ row }">
          <!-- bool 类型用 Switch -->
          <el-switch
            v-if="row.value_type === 'bool'"
            :model-value="row.value === 'true'"
            @change="(val) => handleChange(row, val ? 'true' : 'false')"
          />
          <!-- int 类型用 InputNumber -->
          <el-input-number
            v-else-if="row.value_type === 'int'"
            :model-value="Number(row.value)"
            :min="1"
            controls-position="right"
            style="width: 160px"
            @change="(val) => handleChange(row, String(val))"
          />
          <!-- string 类型用 Input -->
          <el-input
            v-else
            :model-value="row.value"
            style="width: 240px"
            @blur="(e) => handleChange(row, e.target.value)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="200" />
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemSettings, updateSystemSetting } from '@/api/settings'

const loading = ref(false)
const paramList = ref([])

async function fetchParams() {
  loading.value = true
  try {
    const res = await getSystemSettings()
    paramList.value = res.data || []
  } catch (e) {
    console.error('获取系统参数失败', e)
  } finally {
    loading.value = false
  }
}

async function handleChange(row, newValue) {
  const oldValue = row.value
  if (String(newValue) === String(oldValue)) return

  row.value = String(newValue)
  try {
    await updateSystemSetting(row.key, { value: String(newValue) })
    ElMessage.success(`${row.key} 已更新`)
  } catch (e) {
    row.value = oldValue
    console.error('更新参数失败', e)
  }
}

onMounted(() => {
  fetchParams()
})
</script>

<style scoped>
.system-params-view {
  max-width: 900px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.param-key {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  background: var(--color-canvas-subtle, #f3f4f6);
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
