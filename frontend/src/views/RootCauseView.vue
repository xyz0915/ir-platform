<template>
  <div class="root-cause-view">
    <!-- 查询区 -->
    <el-card shadow="never" class="query-card">
      <div class="query-row">
        <span class="query-label">主机 ID</span>
        <el-input-number v-model="hostId" :min="1" :controls="true" placeholder="如 1" />
        <span class="query-label">事件 ID（可选）</span>
        <el-input v-model="eventId" placeholder="security_events.id" style="width: 200px" clearable />
        <el-button type="primary" :icon="Aim" :loading="loading" @click="analyze">
          发起根因分析
        </el-button>
      </div>
      <div class="hint">基于进程树回溯（ProcessTreeBuilder），复用真实 process_events / normalized_logs 数据；LLM 不可用时自动降级为结构化因果链。</div>
    </el-card>

    <!-- 结果区 -->
    <el-card shadow="never" class="result-card">
      <RootCausePanel :result="result" :loading="loading" />
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Aim } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getRootCause } from '@/api/incidents'
import RootCausePanel from '@/components/analysis/RootCausePanel.vue'

const hostId = ref(null)
const eventId = ref('')
const loading = ref(false)
const result = ref(null)

async function analyze() {
  if (!hostId.value) {
    ElMessage.warning('请填写主机 ID')
    return
  }
  loading.value = true
  try {
    const res = await getRootCause({ host_id: hostId.value, event_id: eventId.value || null })
    result.value = res?.data || null
  } catch (e) {
    result.value = null
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.root-cause-view { padding: 16px; }
.query-card { border-radius: 10px; margin-bottom: 14px; }
.query-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.query-label { font-size: 13px; color: var(--el-text-color-regular); }
.hint { margin-top: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.result-card { border-radius: 10px; min-height: 240px; }
</style>
