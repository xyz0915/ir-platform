<template>
  <!-- 主上传对话框 -->
  <el-dialog
    v-model="dialogVisible"
    title="导入日志文件"
    width="560px"
    :close-on-click-modal="false"
    @update:model-value="handleClose"
  >
    <!-- 文件类型选择 -->
    <div style="margin-bottom: 16px">
      <label style="font-size: 13px; color: #606266; margin-bottom: 6px; display: block">日志类型</label>
      <el-select v-model="logType" placeholder="选择日志类型" style="width: 100%">
        <el-option label="自动识别" value="auto" />
        <el-option label="EVTX 文件" value="evtx" />
        <el-option label=".log 日志文件" value="auto_log" />
      </el-select>
    </div>

    <!-- 文件拖拽上传 -->
    <el-upload
      ref="uploadRef"
      :auto-upload="false"
      :limit="1"
      accept=".evtx,.log,.txt"
      :on-change="handleFileChange"
      :on-exceed="handleExceed"
      :before-upload="handleBeforeUpload"
      drag
    >
      <el-icon class="el-icon--upload" style="font-size: 48px; color: #909399">
        <UploadFilled />
      </el-icon>
      <div class="el-upload__text">
        拖拽日志文件到此处，或 <em>点击选择</em>
      </div>
      <template #tip>
        <div class="el-upload__tip">
          支持 .evtx、.log、.txt 格式，单文件最大 500MB
        </div>
      </template>
    </el-upload>

    <!-- 大文件异步提示 -->
    <el-alert
      v-if="isLargeFile"
      type="info"
      :closable="false"
      show-icon
      style="margin-top: 12px"
    >
      <template #title>
        大文件（&gt; 100MB）将异步处理，上传后可离开页面
      </template>
    </el-alert>

    <!-- 文件大小超限提示 -->
    <el-alert
      v-if="isOverLimit"
      type="error"
      :closable="false"
      show-icon
      style="margin-top: 12px"
    >
      <template #title>
        文件大小超过 500MB 限制，请选择较小的文件
      </template>
    </el-alert>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button
        type="primary"
        :loading="loading"
        :disabled="!selectedFile || isOverLimit"
        @click="handleImport"
      >
        {{ loading ? '解析中...' : '确认导入' }}
      </el-button>
    </template>
  </el-dialog>

  <!-- 解析预览对话框 -->
  <el-dialog
    v-model="previewVisible"
    title="解析预览"
    width="780px"
    :close-on-click-modal="false"
    top="5vh"
  >
    <template v-if="previewData">
      <!-- 格式识别结果 -->
      <el-alert
        type="success"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      >
        <template #title>
          检测到 {{ formatLabel(previewData.detected_format) }} 格式（{{ previewData.log_source }}）
        </template>
      </el-alert>

      <!-- 统计摘要 -->
      <div style="display: flex; gap: 16px; margin-bottom: 16px">
        <el-statistic title="总计" :value="previewData.stats?.total || 0" />
        <el-statistic title="High" :value="previewData.stats?.high || 0">
          <template #suffix><el-tag type="danger" size="small" style="margin-left: 4px">high</el-tag></template>
        </el-statistic>
        <el-statistic title="Medium" :value="previewData.stats?.medium || 0">
          <template #suffix><el-tag type="warning" size="small" style="margin-left: 4px">medium</el-tag></template>
        </el-statistic>
        <el-statistic title="Info" :value="previewData.stats?.info || 0">
          <template #suffix><el-tag type="info" size="small" style="margin-left: 4px">info</el-tag></template>
        </el-statistic>
      </div>

      <!-- 前 10 条解析结果 -->
      <h4 style="margin: 12px 0 8px">解析结果预览（前 {{ Math.min(previewData.translated?.length || 0, 10) }} 条）</h4>
      <el-table :data="previewData.translated || []" stripe size="small" style="width: 100%" max-height="300">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ row.timestamp || '-' }}</template>
        </el-table-column>
        <el-table-column label="源 IP" width="130">
          <template #default="{ row }">{{ row.evidence?.src_ip || '-' }}</template>
        </el-table-column>
        <el-table-column label="事件类型" width="120">
          <template #default="{ row }">{{ row.event_type || '-' }}</template>
        </el-table-column>
        <el-table-column label="严重度" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="sevTag(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="URL / 描述" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.evidence?.url || row.evidence?.description || '-' }}</template>
        </el-table-column>
      </el-table>
      <p v-if="!previewData.translated?.length" style="color: #909399; text-align: center; padding: 16px">
        无解析结果
      </p>
    </template>

    <template #footer>
      <el-button @click="previewVisible = false">取消</el-button>
      <el-button type="primary" :loading="confirmLoading" @click="onConfirm">
        {{ confirmLoading ? '导入中...' : '确认入库' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { uploadLogFile, previewLogFile } from '@/api/importLogs'

const props = defineProps({
  visible: { type: Boolean, default: false },
  hostId: { type: Number, required: true },
})

const emit = defineEmits(['update:visible', 'imported'])

// 主对话框
const dialogVisible = ref(false)
const loading = ref(false)
const logType = ref('auto')
const selectedFile = ref(null)
const isLargeFile = ref(false)
const isOverLimit = ref(false)
const uploadRef = ref(null)

// 预览对话框
const previewVisible = ref(false)
const previewData = ref(null)
const confirmLoading = ref(false)

const MAX_FILE_SIZE = 500 * 1024 * 1024   // 500 MB
const ASYNC_THRESHOLD = 100 * 1024 * 1024 // 100 MB

watch(
  () => props.visible,
  (val) => {
    dialogVisible.value = val
    if (!val) {
      resetMainDialog()
    }
  },
)

function handleClose(val) {
  if (!val) {
    emit('update:visible', false)
  }
}

function resetMainDialog() {
  selectedFile.value = null
  isLargeFile.value = false
  isOverLimit.value = false
  logType.value = 'auto'
  previewData.value = null
}

function handleFileChange(file) {
  selectedFile.value = file.raw
  if (file.size > MAX_FILE_SIZE) {
    isOverLimit.value = true
    isLargeFile.value = false
  } else if (file.size > ASYNC_THRESHOLD) {
    isLargeFile.value = true
    isOverLimit.value = false
  } else {
    isLargeFile.value = false
    isOverLimit.value = false
  }
}

function handleExceed() {
  ElMessage.warning('只能上传一个文件')
}

function handleBeforeUpload(file) {
  if (file.size > MAX_FILE_SIZE) {
    ElMessage.error('文件大小超过 500MB 限制')
    return false
  }
  return true
}

function formatLabel(fmt) {
  const map = {
    evtx: 'EVTX',
    nginx_combined: 'Nginx Combined',
    nginx_common: 'Nginx Common',
    apache_combined: 'Apache Combined',
    apache_common: 'Apache Common',
    iis_w3c: 'IIS W3C',
    tomcat_access: 'Tomcat Access',
  }
  return map[fmt] || fmt || '未知'
}

function sevTag(severity) {
  const map = { critical: 'danger', high: 'danger', medium: 'warning', low: 'info', info: 'info' }
  return map[severity] || 'info'
}

async function handleImport() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }

  // 先调用预览
  loading.value = true
  try {
    const logTypeVal = logType.value === 'auto' ? 'auto' : logType.value
    const res = await previewLogFile(props.hostId, selectedFile.value, logTypeVal)
    const data = res.data || {}

    if (data.stats && data.stats.total > 0) {
      // 显示预览对话框
      previewData.value = data
      previewVisible.value = true
    } else {
      // 无解析结果，直接提示
      ElMessage.warning('无法解析该文件，请检查格式')
    }
  } catch (error) {
    const msg = error?.response?.data?.detail || error.message || '文件解析失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

async function onConfirm() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }

  confirmLoading.value = true
  try {
    const logTypeVal = logType.value === 'auto' ? null : logType.value
    const res = await uploadLogFile(props.hostId, selectedFile.value, logTypeVal, true)
    const data = res.data || {}

    if (data.status === 'failed') {
      ElMessage.error(data.message || '导入失败')
    } else if (data.status === 'processing') {
      ElMessage.info(data.message || '文件已提交，正在后台异步处理')
    } else {
      ElMessage.success(`导入成功：解析 ${data.parsed_count || 0} 条，生成 ${data.event_count || 0} 个事件`)
    }

    emit('imported', data)
    previewVisible.value = false
    dialogVisible.value = false
    emit('update:visible', false)
  } catch (error) {
    const msg = error?.response?.data?.detail || error.message || '导入失败'
    ElMessage.error(msg)
  } finally {
    confirmLoading.value = false
  }
}
</script>

<style scoped>
.el-upload__tip {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
</style>
