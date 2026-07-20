<template>
  <el-dialog v-model="visible" title="导入 Agent JSON" width="500px">
    <el-upload
      ref="uploadRef"
      :auto-upload="false"
      :limit="1"
      accept=".json"
      :on-change="handleFileChange"
      :on-exceed="handleExceed"
      drag
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">
        拖拽 JSON 文件到此处，或 <em>点击选择</em>
      </div>
      <template #tip>
        <div class="el-upload__tip">
          仅支持 .json 格式文件，文件大小不超过 100MB
        </div>
      </template>
    </el-upload>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleImport">
        导入
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import hostsApi from '@/api/hosts'

const props = defineProps({
  hostId: { type: Number, required: true }
})

const emit = defineEmits(['success'])

const visible = ref(false)
const loading = ref(false)
const selectedFile = ref(null)
const uploadRef = ref(null)

function show() {
  visible.value = true
  selectedFile.value = null
}

function handleFileChange(file) {
  selectedFile.value = file.raw
}

function handleExceed() {
  ElMessage.warning('只能上传一个文件')
}

async function handleImport() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择 JSON 文件')
    return
  }
  loading.value = true
  try {
    const res = await hostsApi.importJson(props.hostId, selectedFile.value)
    ElMessage.success('导入成功')
    visible.value = false
    emit('success', res.data)
  } catch (error) {
    const msg = error?.response?.data?.detail || error?.message || '导入失败，请检查后端是否正常运行'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

defineExpose({ show })
</script>
