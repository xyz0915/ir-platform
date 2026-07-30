<template>
  <div class="doc-preview">
    <div v-if="loading" class="doc-loading">
      <el-skeleton :rows="4" animated />
    </div>

    <div v-else-if="errorMsg" class="doc-error">
      <el-icon :size="20"><WarningFilled /></el-icon>
      <span>{{ errorMsg }}</span>
    </div>

    <!-- Markdown 渲染 -->
    <div
      v-else-if="fileType === 'md' && renderedHtml"
      class="doc-content markdown-body"
      v-html="renderedHtml"
    />

    <!-- HTML 渲染 -->
    <div
      v-else-if="fileType === 'html' && renderedHtml"
      class="doc-content"
      v-html="renderedHtml"
    />

    <!-- PDF 预览 -->
    <div v-else-if="fileType === 'pdf'" class="doc-pdf-wrap">
      <iframe
        :src="pdfUrl"
        class="doc-pdf-iframe"
        frameborder="0"
      />
    </div>

    <!-- 无文档 -->
    <div v-else class="doc-empty">
      <el-icon :size="24"><DocumentDelete /></el-icon>
      <span>暂无操作文档，仅提供工具文件</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { WarningFilled, DocumentDelete } from '@element-plus/icons-vue'
import { getDocContent } from '@/api/toolbox'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps({
  toolId: { type: [Number, String], default: null },
  versions: { type: Array, default: () => [] },
  currentVersion: { type: String, default: '' },
})

const loading = ref(false)
const errorMsg = ref('')
const fileType = ref('')
const rawContent = ref('')

const renderedHtml = computed(() => {
  if (!rawContent.value) return ''
  if (fileType.value === 'md') {
    return sanitizeHtml(renderMarkdown(rawContent.value))
  }
  if (fileType.value === 'html') {
    return sanitizeHtml(rawContent.value)
  }
  return ''
})

const pdfUrl = computed(() => {
  if (fileType.value !== 'pdf' || !props.toolId) return ''
  const token = localStorage.getItem('ir_token')
  const base = import.meta.env.VITE_API_BASE || ''
  return `${base}/api/tools/${props.toolId}/doc?token=${token}`
})

/**
 * Simple HTML sanitization to prevent XSS (DOMPurify alternative)
 */
function sanitizeHtml(html) {
  if (!html) return ''
  // Remove script tags and event handlers
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
    .replace(/\son\w+\s*=\s*[^\s>]+/gi, '')
    .replace(/javascript\s*:/gi, '')
}

async function loadDoc() {
  if (!props.toolId) {
    resetState()
    return
  }

  loading.value = true
  errorMsg.value = ''
  fileType.value = ''
  rawContent.value = ''

  try {
    const res = await getDocContent(props.toolId)
    if (res.code === 0 && res.data) {
      if (res.data.file_type === 'pdf') {
        // PDF is handled via direct URL / iframe
        fileType.value = 'pdf'
      } else {
        rawContent.value = res.data.content || ''
        fileType.value = res.data.file_type || 'md'
      }
    } else {
      // No doc available — not an error
      fileType.value = ''
    }
  } catch (err) {
    // If doc endpoint returns 404 or error, show empty state
    errorMsg.value = ''
    fileType.value = ''
  } finally {
    loading.value = false
  }
}

function resetState() {
  loading.value = false
  errorMsg.value = ''
  fileType.value = ''
  rawContent.value = ''
}

watch(
  () => props.toolId,
  (id) => {
    if (id) {
      loadDoc()
    } else {
      resetState()
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.doc-preview {
  min-height: 60px;
}
.doc-loading {
  padding: 8px 0;
}
.doc-error {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-danger-fg, #dc2626);
  padding: 8px 0;
}
.doc-content {
  background: var(--color-canvas-subtle, #fafafa);
  border-radius: 8px;
  padding: 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-fg-default, #1d1d1f);
  border: 1px solid var(--color-border-default, #e8e8ed);
  max-height: 320px;
  overflow-y: auto;
}
.doc-content :deep(h1) {
  font-size: 16px;
  margin: 10px 0 8px;
  font-weight: 600;
}
.doc-content :deep(h2) {
  font-size: 14px;
  margin: 8px 0 6px;
  font-weight: 600;
}
.doc-content :deep(code) {
  background: var(--color-canvas-default, #f2f2f7);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-fg-default, #515154);
}
.doc-content :deep(pre) {
  background: #1d1d1f;
  color: #f5f5f5;
  padding: 12px 14px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12px;
  margin: 10px 0;
  line-height: 1.6;
}
.doc-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}
.doc-content :deep(ul),
.doc-content :deep(ol) {
  padding-left: 20px;
  margin: 6px 0;
}
.doc-content :deep(li) {
  margin: 2px 0;
}
.doc-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin: 8px 0;
}
.doc-content :deep(th),
.doc-content :deep(td) {
  border: 1px solid var(--color-border-default, #e8e8ed);
  padding: 6px 10px;
}
.doc-content :deep(a) {
  color: var(--el-color-primary, #0071e3);
}
.doc-pdf-wrap {
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--color-border-default, #e8e8ed);
}
.doc-pdf-iframe {
  width: 100%;
  height: 400px;
  border: none;
}
.doc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px 0;
  color: var(--color-fg-muted, #86868b);
  font-size: 13px;
}
</style>
