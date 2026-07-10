<template>
  <div>
    <div class="flex-between mb-10">
      <span class="tab-hint">共 {{ data.length }} 条网络连接</span>
      <el-button
        type="primary"
        :loading="enriching"
        @click="handleEnrich"
        :disabled="!data.length"
      >
        一键威胁情报检测
      </el-button>
    </div>
    <el-table :data="data" border stripe size="small">
      <el-table-column prop="protocol" label="协议" width="70" />
      <el-table-column prop="local_addr" label="本地地址" min-width="130" />
      <el-table-column prop="local_port" label="本地端口" width="90" />
      <el-table-column label="远程地址" min-width="140">
        <template #default="{ row }">
          <el-tag v-if="isPublicAddress(row.remote_addr)" type="warning" size="small" effect="dark">
            {{ row.remote_addr }}
          </el-tag>
          <span v-else>{{ row.remote_addr }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="remote_port" label="远程端口" width="90" />
      <el-table-column label="威胁情报" min-width="150">
        <template #default="{ row }">
          <template v-if="row.threat_level === 'high'">
            <el-tag type="danger" size="small">恶意</el-tag>
          </template>
          <template v-else-if="row.threat_level === 'medium'">
            <el-tag type="warning" size="small">可疑</el-tag>
          </template>
          <template v-else-if="row.threat_level === 'low'">
            <el-tag type="success" size="small">干净</el-tag>
          </template>
          <template v-else-if="isPublicAddress(row.remote_addr)">
            <el-tag type="info" size="small">未检测</el-tag>
          </template>
          <template v-else>
            <span class="text-muted">私网</span>
          </template>
        </template>
      </el-table-column>
      <el-table-column prop="state" label="状态" width="100" />
      <el-table-column prop="pid" label="PID" width="70" />
      <el-table-column prop="process_name" label="进程名" width="140" show-overflow-tooltip />
      <el-table-column prop="collected_at" label="采集时间" min-width="160" />
    </el-table>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import analysisApi from '@/api/analysis'

const props = defineProps({
  hostId: { type: Number, default: 0 },
  data: { type: Array, default: () => [] }
})

const emit = defineEmits(['refresh'])

const enriching = ref(false)

async function handleEnrich() {
  if (!props.hostId) return
  enriching.value = true
  try {
    const res = await analysisApi.enrichNetworkConnections(props.hostId)
    const d = res.data || res
    const parts = []
    if (d.public) parts.push(`去重公网IP ${d.public} 个`)
    if (d.enriched) parts.push(`检测 ${d.enriched} 个`)
    if (d.malicious) parts.push(`恶意 ${d.malicious}`)
    if (d.suspicious) parts.push(`可疑 ${d.suspicious}`)
    if (d.skipped_private) parts.push(`跳过私网 ${d.skipped_private}`)
    ElMessage.success(parts.join('，'))
    emit('refresh')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '检测失败')
  } finally {
    enriching.value = false
  }
}

function isPublicAddress(addr) {
  if (!addr) return false
  const host = addr.split(':')[0].trim()
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) {
    const parts = host.split('.').map(Number)
    if (parts.some((p) => Number.isNaN(p) || p > 255)) return false
    const [a, b] = parts
    if (a === 10) return false
    if (a === 172 && b >= 16 && b <= 31) return false
    if (a === 192 && b === 168) return false
    if (a === 127) return false
    if (a === 169 && b === 254) return false
    if (a === 0) return false
    if (a >= 224 && a <= 239) return false
    return true
  }
  const v6 = host.toLowerCase()
  if (v6 === '::1' || v6 === '0:0:0:0:0:0:0:1') return false
  if (v6.startsWith('fe80')) return false
  if (v6.startsWith('fc') || v6.startsWith('fd')) return false
  if (v6 === '::') return false
  if (v6.startsWith('ff')) return false
  return true
}
</script>

<style scoped>
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.mb-10 { margin-bottom: 10px; }
.tab-hint { font-size: 13px; color: #909399; }
.text-muted { color: #c0c4cc; font-size: 12px; }
</style>
