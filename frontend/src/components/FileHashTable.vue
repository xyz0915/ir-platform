<template>
  <el-table :data="data" border stripe size="small">
    <el-table-column prop="file_path" label="文件路径" min-width="200" show-overflow-tooltip />
    <el-table-column prop="file_name" label="文件名" width="150" show-overflow-tooltip />
    <el-table-column prop="sha256" label="SHA256" min-width="240" show-overflow-tooltip>
      <template #default="{ row }">
        <code class="mono-code">{{ row.sha256 }}</code>
      </template>
    </el-table-column>
    <el-table-column label="签名状态" width="90">
      <template #default="{ row }">
        <el-tag :type="row.is_signed ? 'success' : 'danger'" size="small">
          {{ row.is_signed ? '已签名' : '未签名' }}
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="signer" label="签名者" min-width="160" show-overflow-tooltip />
    <el-table-column prop="file_size" label="文件大小" width="100" />
    <el-table-column prop="product_name" label="产品名" min-width="140" show-overflow-tooltip />
    <el-table-column prop="product_version" label="产品版本" width="110" />
    <el-table-column prop="collected_at" label="采集时间" min-width="160" />
  </el-table>
</template>

<script setup>
defineProps({
  data: { type: Array, default: () => [] }
})
</script>

<style scoped>
.mono-code {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  color: #303133;
}
</style>
