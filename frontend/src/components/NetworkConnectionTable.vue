<template>
  <div>
    <!-- 操作栏 -->
    <div class="flex-between mb-8">
      <span class="tab-hint">共 {{ filteredData.length }} / {{ data.length }} 条网络连接</span>
      <el-button
        type="primary"
        :loading="enriching"
        @click="handleEnrich"
        :disabled="!data.length"
      >
        一键威胁情报检测
      </el-button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="filters.addrScope" size="small" class="filter-item" @change="handleFilterChange">
        <el-option label="全部地址" value="all" />
        <el-option label="仅公网" value="public" />
        <el-option label="仅私网" value="private" />
      </el-select>
      <el-select v-model="filters.state" size="small" class="filter-item" clearable placeholder="全部状态">
        <el-option v-for="s in stateOptions" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="filters.protocol" size="small" class="filter-item" clearable placeholder="全部协议">
        <el-option label="TCP" value="TCP" />
        <el-option label="UDP" value="UDP" />
      </el-select>
      <el-select v-model="filters.threat" size="small" class="filter-item" clearable placeholder="全部威胁等级">
        <el-option label="恶意" value="high" />
        <el-option label="可疑" value="medium" />
        <el-option label="干净" value="low" />
        <el-option label="未检测" value="none" />
      </el-select>
      <el-input v-model="filters.processName" size="small" class="filter-item filter-search" placeholder="搜索进程名" clearable @clear="handleFilterChange" @input="handleFilterChange" />
    </div>

    <!-- 表格 -->
    <el-table :data="filteredData" border stripe size="small">
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
      <el-table-column label="威胁情报" min-width="130">
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
      <el-table-column prop="state" label="状态" width="110" />
      <el-table-column prop="pid" label="PID" width="70" />
      <el-table-column prop="process_name" label="进程名" width="140" show-overflow-tooltip />
      <el-table-column prop="collected_at" label="采集时间" min-width="160" />
    </el-table>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import analysisApi from '@/api/analysis'

const props = defineProps({
  hostId: { type: Number, default: 0 },
  data: { type: Array, default: () => [] }
})

const emit = defineEmits(['refresh'])
const enriching = ref(false)

// ── 筛选状态 ──
const filters = ref({
  addrScope: 'public',   // 默认只看公网
  state: '',
  protocol: '',
  threat: '',
  processName: '',
})

const stateOptions = computed(() => {
  const set = new Set()
  for (const row of props.data) {
    if (row.state) set.add(row.state)
  }
  return [...set].sort()
})

const filteredData = computed(() => {
  let rows = props.data
  const f = filters.value

  // 地址范围
  if (f.addrScope === 'public') rows = rows.filter(r => isPublicAddress(r.remote_addr))
  else if (f.addrScope === 'private') rows = rows.filter(r => r.remote_addr && !isPublicAddress(r.remote_addr))

  // 状态
  if (f.state) rows = rows.filter(r => r.state === f.state)

  // 协议
  if (f.protocol) rows = rows.filter(r => r.protocol === f.protocol)

  // 威胁等级
  if (f.threat === 'none') rows = rows.filter(r => !r.threat_level && isPublicAddress(r.remote_addr))
  else if (f.threat) rows = rows.filter(r => r.threat_level === f.threat)

  // 进程名搜索
  if (f.processName) {
    const q = f.processName.toLowerCase()
    rows = rows.filter(r => (r.process_name || '').toLowerCase().includes(q))
  }

  return rows
})

function handleFilterChange() {
  // 计算属性自动响应，占位函数用于保持表意
}

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
.mb-8 { margin-bottom: 8px; }
.tab-hint { font-size: 13px; color: #909399; }
.text-muted { color: #c0c4cc; font-size: 12px; }
.filter-bar {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 10px; padding: 8px 10px;
  background: #f5f7fa; border-radius: 6px;
}
.filter-item { width: 120px; }
.filter-search { width: 200px; }
</style>
