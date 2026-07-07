<template>
  <el-dialog v-model="visible" title="下载 Agent" width="450px">
    <el-radio-group v-model="selectedOs" class="os-select">
      <el-radio label="windows">
        <el-icon><Monitor /></el-icon>
        Windows 版本 (.exe)
      </el-radio>
      <el-radio label="linux">
        <el-icon><Platform /></el-icon>
        Linux 版本
      </el-radio>
    </el-radio-group>
    <el-alert
      title="使用说明"
      type="info"
      :closable="false"
      class="mt-20"
    >
      <p>1. 下载对应平台的 Agent 文件</p>
      <p>2. 将 Agent 复制到目标主机</p>
      <p>3. 以管理员/root权限运行 Agent</p>
      <p>4. 运行完成后将生成的 JSON 文件导入平台</p>
    </el-alert>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleDownload">
        下载 Agent
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import hostsApi from '@/api/hosts'

const visible = ref(false)
const selectedOs = ref('windows')
const loading = ref(false)

function show() {
  visible.value = true
  selectedOs.value = 'windows'
}

async function handleDownload() {
  loading.value = true
  try {
    const res = await hostsApi.downloadAgent(selectedOs.value)
    const filename = selectedOs.value === 'windows' ? 'agent_windows.exe' : 'agent_linux'
    const blob = new Blob([res], { type: 'application/octet-stream' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('Agent 下载成功')
    visible.value = false
  } catch (error) {
    // 错误已在拦截器中处理
  } finally {
    loading.value = false
  }
}

defineExpose({ show })
</script>

<style scoped>
.os-select {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.os-select .el-radio {
  height: auto;
  padding: 10px 0;
}
</style>
