<template>
  <div class="page-container">
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">分析报告</h2>
        <div>
          <el-button type="primary" :loading="downloading" @click="handleDownloadPdf">
            <el-icon><Download /></el-icon> 导出 PDF
          </el-button>
          <el-button @click="$router.back()">
            <el-icon><Back /></el-icon> 返回
          </el-button>
        </div>
      </div>
      <div class="report-frame-container">
        <iframe
          :src="reportUrl"
          class="report-frame"
          frameborder="0"
        ></iframe>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import reportApi from '@/api/report'

const route = useRoute()
const hostId = route.params.id

const downloading = ref(false)

const reportUrl = `/api/hosts/${hostId}/report`

async function handleDownloadPdf() {
  downloading.value = true
  try {
    const res = await reportApi.downloadPdf(hostId)
    const blob = new Blob([res], { type: 'application/pdf' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `report_host_${hostId}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('PDF 下载成功')
  } catch (error) {
    // handled
  } finally {
    downloading.value = false
  }
}
</script>

<style scoped>
.report-frame-container {
  width: 100%;
  height: calc(100vh - 250px);
  border: 1px solid var(--color-border-default);
  border-radius: 4px;
  overflow: hidden;
}

.report-frame {
  width: 100%;
  height: 100%;
}
</style>
