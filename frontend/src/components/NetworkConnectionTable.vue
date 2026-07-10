<template>
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
    <el-table-column prop="state" label="状态" width="100" />
    <el-table-column prop="pid" label="PID" width="70" />
    <el-table-column prop="process_name" label="进程名" width="140" show-overflow-tooltip />
    <el-table-column prop="collected_at" label="采集时间" min-width="160" />
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})

/** 判断 IPv4/IPv6 是否为公网地址 */
function isPublicAddress(addr) {
  if (!addr) return false
  const host = addr.split(':')[0].trim()
  // IPv4
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
  // IPv6
  const v6 = host.toLowerCase()
  if (v6 === '::1' || v6 === '0:0:0:0:0:0:0:1') return false
  if (v6.startsWith('fe80')) return false
  if (v6.startsWith('fc') || v6.startsWith('fd')) return false
  if (v6 === '::') return false
  if (v6.startsWith('ff')) return false
  return true
}
</script>
