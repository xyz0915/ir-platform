<template>
  <el-drawer
    :model-value="visible"
    :title="isEditMode ? '编辑工具' : '上传应急工具'"
    direction="rtl"
    size="520px"
    :before-close="handleClose"
  >
    <div class="upload-body">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="default"
      >
        <!-- 工具名称 -->
        <el-form-item label="工具名称" prop="name">
          <el-input
            v-model="form.name"
            placeholder="例如：Volatility 内存取证工具"
            :disabled="submitting"
          />
        </el-form-item>

        <!-- 简要描述 -->
        <el-form-item label="简要描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="工具用途、适用场景等"
            :disabled="submitting"
          />
        </el-form-item>

        <!-- 分类 + 版本号 -->
        <div class="form-row">
          <el-form-item label="分类" prop="category" class="form-row-item">
            <el-select v-model="form.category" placeholder="选择分类" :disabled="submitting" style="width:100%">
              <el-option v-for="cat in categoryOptions" :key="cat" :label="cat" :value="cat" />
            </el-select>
          </el-form-item>
          <el-form-item label="版本号" prop="version" class="form-row-item">
            <el-input
              v-model="form.version"
              placeholder="1.0.0"
              :disabled="submitting"
            />
          </el-form-item>
        </div>

        <!-- 标签 -->
        <el-form-item label="标签" prop="tags">
          <el-input
            v-model="form.tags"
            placeholder="例如：内存, Rootkit, 取证（逗号分隔）"
            :disabled="submitting"
          />
        </el-form-item>

        <!-- 工具文件 -->
        <el-form-item label="工具文件" prop="toolFile" :required="!isEditMode">
          <el-upload
            ref="toolUploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="onToolFileChange"
            :on-remove="onToolFileRemove"
            :file-list="toolFileList"
            drag
            class="upload-dragger"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="upload-text">
              拖拽或 <em>点击选择</em> 工具文件
            </div>
            <template #tip>
              <div class="upload-hint">支持 .exe .zip .tar.gz .py .ps1，最大 200MB</div>
            </template>
          </el-upload>
        </el-form-item>

        <!-- 操作文档 -->
        <el-form-item label="操作文档">
          <el-upload
            ref="docUploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="onDocFileChange"
            :on-remove="onDocFileRemove"
            :file-list="docFileList"
            drag
            class="upload-dragger"
          >
            <el-icon class="upload-icon"><Document /></el-icon>
            <div class="upload-text">
              拖拽或点击选择文档（.md / .pdf / .html）
            </div>
            <template #tip>
              <div class="upload-hint">可选，最大 50MB</div>
            </template>
          </el-upload>
        </el-form-item>

        <!-- 更新日志（上传模式也显示，用于首次版本） -->
        <el-form-item label="更新日志" prop="changeLog">
          <el-input
            v-model="form.changeLog"
            type="textarea"
            :rows="3"
            placeholder="描述此版本的主要变更…"
            :disabled="submitting"
          />
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <div class="upload-footer">
        <el-button @click="handleClose" :disabled="submitting">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          {{ isEditMode ? '保存修改' : '提交上传' }}
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled, Document } from '@element-plus/icons-vue'
import { uploadTool, updateTool, publishVersion, getToolDetail } from '@/api/toolbox'

const props = defineProps({
  visible: { type: Boolean, default: false },
  editToolId: { type: [Number, String], default: null },
})

const emit = defineEmits(['close', 'success'])

const categoryOptions = [
  '内存取证',
  '恶意分析',
  '查杀清理',
  '网络检测',
  '日志分析',
  '实用工具',
]

const isEditMode = computed(() => !!props.editToolId)

// ── Form ──
const formRef = ref(null)
const toolUploadRef = ref(null)
const docUploadRef = ref(null)
const submitting = ref(false)

const form = reactive({
  name: '',
  description: '',
  category: '内存取证',
  version: '1.0.0',
  tags: '',
  changeLog: '',
})

const toolFileList = ref([])
const docFileList = ref([])
let toolFileRaw = null
let docFileRaw = null

const rules = {
  name: [{ required: true, message: '请输入工具名称', trigger: 'blur' }],
  version: [
    { required: true, message: '请输入版本号', trigger: 'blur' },
    { pattern: /^\d+\.\d+\.\d+$/, message: '版本号格式必须为 x.y.z', trigger: 'blur' },
  ],
  toolFile: [
    {
      validator: () => toolFileRaw !== null,
      message: '请上传工具文件',
      trigger: 'change',
    },
  ],
}

// ── File handlers ──
function onToolFileChange(uploadFile) {
  toolFileRaw = uploadFile.raw
  toolFileList.value = [uploadFile]
  // 主动触发 toolFile 字段校验
  formRef.value?.validateField('toolFile').catch(() => {})
}
function onToolFileRemove() {
  toolFileRaw = null
  toolFileList.value = []
  formRef.value?.validateField('toolFile').catch(() => {})
}
function onDocFileChange(uploadFile) {
  docFileRaw = uploadFile.raw
  docFileList.value = [uploadFile]
}
function onDocFileRemove() {
  docFileRaw = null
  docFileList.value = []
}

// ── Edit mode: load existing data ──
async function loadEditData() {
  if (!props.editToolId) return
  try {
    const res = await getToolDetail(props.editToolId)
    if (res.code === 0 && res.data) {
      const d = res.data
      form.name = d.name || ''
      form.description = d.description || ''
      form.category = d.category || '内存取证'
      form.version = d.current_version || '1.0.0'
      if (Array.isArray(d.tags)) {
        form.tags = d.tags.join(', ')
      } else if (typeof d.tags === 'string') {
        try {
          form.tags = JSON.parse(d.tags).join(', ')
        } catch {
          form.tags = d.tags
        }
      }
    }
  } catch {
    // silent
  }
}

watch(
  () => props.visible,
  (val) => {
    if (val) {
      if (props.editToolId) {
        loadEditData()
      } else {
        // Reset form
        form.name = ''
        form.description = ''
        form.category = '内存取证'
        form.version = '1.0.0'
        form.tags = ''
        form.changeLog = ''
        toolFileRaw = null
        docFileRaw = null
        toolFileList.value = []
        docFileList.value = []
      }
    }
  }
)

// ── Submit ──
async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  if (!isEditMode.value && !toolFileRaw) {
    ElMessage.warning('请上传工具文件')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', form.name)
    fd.append('description', form.description || '')
    fd.append('category', form.category)
    fd.append('version', form.version)
    fd.append('tags', form.tags || '')
    fd.append('change_log', form.changeLog || '')

    if (!isEditMode.value && toolFileRaw) {
      fd.append('tool_file', toolFileRaw)
    }
    if (docFileRaw) {
      fd.append('doc_file', docFileRaw)
    }

    let res
    if (isEditMode.value) {
      // 编辑模式：更新基本信息
      res = await updateTool(props.editToolId, fd)
    } else {
      // 上传模式
      res = await uploadTool(fd)
    }

    if (res && res.code === 0) {
      ElMessage.success(isEditMode.value ? '工具已更新' : '上传成功')
      emit('success')
    } else {
      ElMessage.error(res?.message || '操作失败')
    }
  } catch (e) {
    ElMessage.error(e?.message || '请求失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

function handleClose() {
  emit('close')
}
</script>

<style scoped>
.upload-body {
  padding: 0 4px;
}
.form-row {
  display: flex;
  gap: 12px;
}
.form-row-item {
  flex: 1;
}
.upload-dragger {
  width: 100%;
}
.upload-icon {
  font-size: 28px;
  color: var(--color-fg-muted, #86868b);
  margin-bottom: 4px;
}
.upload-text {
  font-size: 13px;
  color: var(--color-fg-muted, #515154);
}
.upload-text em {
  color: var(--el-color-primary, #0071e3);
  font-style: normal;
  font-weight: 500;
}
.upload-hint {
  font-size: 11px;
  color: var(--color-fg-muted, #d2d2d7);
  margin-top: 4px;
}
.upload-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
