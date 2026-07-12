<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="protocol" label="协议" width="70" />
    <el-table-column label="本地地址" min-width="150">
      <template #default="{ row }">
        {{ row.local_address }}:{{ row.local_port }}
      </template>
    </el-table-column>
    <el-table-column label="远程地址" min-width="150">
      <template #default="{ row }">
        {{ row.remote_address }}:{{ row.remote_port }}
      </template>
    </el-table-column>
    <el-table-column prop="state" label="状态" width="100" />
    <el-table-column prop="process_name" label="进程" width="120" show-overflow-tooltip />
    <el-table-column prop="reason" label="命中原因" min-width="200" show-overflow-tooltip />
    <el-table-column prop="severity" label="严重程度" width="100">
      <template #default="{ row }">
        <el-tag :type="severityType(row.severity)" size="small">
          {{ row.severity }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="威胁情报" width="110">
      <template #default="{ row }">
        <el-tag :type="threatIntel(row).type" size="small" effect="dark">
          {{ threatIntel(row).label }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="知识匹配" width="70" v-if="hasKnowledgeHits">
      <template #default="{ row }">
        <el-tooltip
          v-if="row.knowledge_hit"
          :content="row.knowledge_hit.title + ' (' + row.knowledge_hit.confidence + ')'"
          placement="top"
        >
          <span class="knowledge-badge" @click.stop="$emit('knowledge-click', row.knowledge_hit.entry_ref)">📚</span>
        </el-tooltip>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] }
})

defineEmits(['knowledge-click'])

const hasKnowledgeHits = computed(() => {
  return props.data.some(row => row.knowledge_hit)
})

function severityType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary',
    info: 'info'
  }
  return map[severity] || 'info'
}

// 根据威胁情报字段与远程地址，渲染「威胁情报」列标签
function threatIntel(row) {
  const level = row.threat_level
  const addr = row.remote_address || ''
  if (level === 'high') {
    return { label: '恶意', type: 'danger' }
  }
  if (level === 'medium') {
    return { label: '可疑', type: 'warning' }
  }
  if (level === 'low' || level === 'clean') {
    return { label: '干净', type: 'success' }
  }
  // level 为 None / 空：按远程地址判断私网跳过或未检测
  if (isPrivateAddress(addr)) {
    return { label: '私网跳过', type: 'info' }
  }
  return { label: '未检测', type: 'info' }
}

// 判断 IPv4/IPv6 是否为私网/保留地址（与后端 ipaddress 过滤口径一致）
function isPrivateAddress(addr) {
  if (!addr) return false
  const host = addr.split(':')[0].trim()
  // IPv4
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(host)) {
    const parts = host.split('.').map(Number)
    if (parts.some((p) => Number.isNaN(p) || p > 255)) return false
    const [a, b] = parts
    if (a === 10) return true
    if (a === 172 && b >= 16 && b <= 31) return true
    if (a === 192 && b === 168) return true
    if (a === 127) return true
    if (a === 169 && b === 254) return true
    if (a === 0) return true
    if (a >= 224 && a <= 239) return true // 组播
    return false
  }
  // IPv6
  const v6 = host.toLowerCase()
  if (v6 === '::1' || v6 === '0:0:0:0:0:0:0:1') return true
  if (v6.startsWith('fe80')) return true // 链路本地
  if (v6.startsWith('fc') || v6.startsWith('fd')) return true // 唯一本地
  if (v6 === '::') return true
  if (v6.startsWith('ff')) return true // 组播
  return false
}
</script>
<style scoped>
.knowledge-badge { cursor: pointer; font-size: 16px; }
</style>
