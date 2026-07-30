<template>
  <el-drawer
    :model-value="visible"
    :title="toolData ? toolData.name : '工具详情'"
    direction="rtl"
    size="520px"
    :before-close="handleClose"
  >
    <template v-if="loading" #default>
      <div class="drawer-loading">
        <el-skeleton :rows="10" animated />
      </div>
    </template>

    <template v-else-if="toolData" #default>
      <div class="drawer-body">
        <!-- 基本信息 -->
        <div class="dl-section">
          <div class="dl-label">基本信息</div>
          <div class="dl-meta">
            <span class="dl-meta-item">
              版本：<span class="dl-meta-v">v{{ toolData.current_version }}</span>
            </span>
            <span class="dl-meta-item">
              分类：<span class="dl-meta-v">{{ toolData.category }}</span>
            </span>
            <span class="dl-meta-item">
              上传：<span class="dl-meta-v">{{ toolData.author_name || toolData.author_id || '-' }}</span>
            </span>
            <span class="dl-meta-item">
              更新：<span class="dl-meta-v">{{ formatDate(toolData.updated_at) }}</span>
            </span>
            <span class="dl-meta-item">
              下载：<span class="dl-meta-v">{{ toolData.download_count }}</span>
            </span>
          </div>
        </div>

        <!-- 描述 -->
        <div class="dl-section">
          <div class="dl-label">描述</div>
          <div class="dl-value">{{ toolData.description || '暂无描述' }}</div>
        </div>

        <!-- 标签 -->
        <div class="dl-section" v-if="tagList.length > 0">
          <div class="dl-label">标签</div>
          <div class="dl-tags">
            <el-tag
              v-for="tag in tagList"
              :key="tag"
              size="small"
              class="dl-tag-item"
            >
              {{ tag }}
            </el-tag>
          </div>
        </div>

        <!-- 版本历史 -->
        <div class="dl-section">
          <div class="dl-label">版本历史</div>
          <el-timeline>
            <el-timeline-item
              v-for="ver in versionList"
              :key="ver.id"
              :timestamp="formatDate(ver.created_at)"
              placement="top"
              :color="ver.version === toolData.current_version ? '#34c759' : undefined"
            >
              <div class="ver-item">
                <span class="ver-number">
                  v{{ ver.version }}
                  <el-tag v-if="ver.version === toolData.current_version" size="small" type="success" class="ver-badge">当前</el-tag>
                </span>
                <div v-if="ver.change_log" class="ver-log">{{ ver.change_log }}</div>
                <div class="ver-file">{{ ver.file_name || '' }}</div>
              </div>
            </el-timeline-item>
          </el-timeline>
          <div v-if="versionList.length === 0" class="dl-empty">暂无版本记录</div>
        </div>

        <!-- 操作文档 -->
        <div class="dl-section">
          <div class="dl-label">操作文档</div>
          <ToolboxDocPreview
            :tool-id="toolId"
            :versions="toolData.versions || []"
            :current-version="toolData.current_version"
          />
        </div>
      </div>
    </template>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="handleClose">关闭</el-button>
        <el-button type="primary" @click="handleDownload">
          <el-icon><Download /></el-icon> 下载工具
        </el-button>
        <el-button v-if="canDelete" type="danger" @click="handleDelete">
          <el-icon><Delete /></el-icon> 删除
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Delete } from '@element-plus/icons-vue'
import { getToolDetail, deleteTool, downloadTool } from '@/api/toolbox'
import ToolboxDocPreview from '@/components/toolbox/ToolboxDocPreview.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  toolId: { type: [Number, String], default: null },
})

const emit = defineEmits(['close', 'deleted'])

const toolData = ref(null)
const loading = ref(false)
const tagList = computed(() => {
  if (!toolData.value) return []
  const tags = toolData.value.tags
  if (Array.isArray(tags)) return tags
  if (typeof tags === 'string') {
    try {
      return JSON.parse(tags)
    } catch {
      return tags.split(',').map((t) => t.trim()).filter(Boolean)
    }
  }
  return []
})

const versionList = computed(() => {
  return (toolData.value?.versions || []).slice().reverse()
})

// Simple check: if current user is admin or uploader — use auth store
const canDelete = computed(() => {
  // Default to true for now; real auth check can be done via store
  return true
})

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

async function loadDetail() {
  if (!props.toolId) return
  loading.value = true
  try {
    const res = await getToolDetail(props.toolId)
    if (res.code === 0 && res.data) {
      toolData.value = res.data
    }
  } catch {
    toolData.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => props.toolId,
  (id) => {
    if (id) {
      loadDetail()
    } else {
      toolData.value = null
    }
  },
  { immediate: true }
)

function handleClose() {
  emit('close')
}

function handleDownload() {
  if (props.toolId) {
    downloadTool(props.toolId)
  }
}

async function handleDelete() {
  try {
    await ElMessageBox.confirm(
      '确定要删除此工具吗？该操作将同时删除所有版本文件和下载记录，不可恢复。',
      '确认删除',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
    const res = await deleteTool(props.toolId)
    if (res.code === 0) {
      ElMessage.success('工具已删除')
      emit('deleted')
    }
  } catch (err) {
    if (err !== 'cancel') {
      // 实际错误由 request.js 拦截器处理
    }
  }
}
</script>

<style scoped>
.drawer-loading {
  padding: 24px;
}
.drawer-body {
  padding: 0 4px;
}
.dl-section {
  margin-bottom: 24px;
}
.dl-section:last-child {
  margin-bottom: 0;
}
.dl-label {
  font-size: 11px;
  color: var(--color-fg-muted, #86868b);
  margin-bottom: 8px;
  letter-spacing: 0.4px;
  text-transform: uppercase;
}
.dl-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--color-fg-default, #1d1d1f);
}
.dl-meta-item {
  white-space: nowrap;
}
.dl-meta-v {
  font-weight: 600;
}
.dl-value {
  font-size: 13px;
  color: var(--color-fg-default, #1d1d1f);
  line-height: 1.6;
}
.dl-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.dl-tag-item {
  margin-right: 4px;
}
.dl-empty {
  font-size: 13px;
  color: var(--color-fg-muted, #86868b);
  padding: 12px 0;
}
.ver-item {
  padding: 4px 0;
}
.ver-number {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-fg-default, #1d1d1f);
}
.ver-badge {
  margin-left: 6px;
}
.ver-log {
  font-size: 12px;
  color: var(--color-fg-muted, #515154);
  margin-top: 2px;
}
.ver-file {
  font-size: 11px;
  color: var(--color-fg-muted, #86868b);
  margin-top: 1px;
}
.drawer-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
</style>
