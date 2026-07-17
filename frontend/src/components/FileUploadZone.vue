<template>
  <div class="upload-zone" @drop.prevent="handleDrop" @dragover.prevent
    :class="{ dragging: isDragging }" @dragenter="isDragging = true" @dragleave="isDragging = false">
    <input ref="fileInput" type="file" accept=".evtx,.csv,.txt,.log,.json,.png,.jpg" style="display:none" @change="handleFileSelect" />
    <span v-if="!uploadedFile" class="uz-hint" @click="fileInput.click()">
      + 拖拽文件或点击上传
    </span>
    <span v-else class="uz-file">
      {{ uploadedFile.name }} ({{ formatSize(uploadedFile.size) }})
      <el-button size="small" text @click="clearFile">×</el-button>
    </span>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const emit = defineEmits(['file-selected', 'file-cleared'])
const isDragging = ref(false)
const uploadedFile = ref(null)
const fileInput = ref(null)

function handleDrop(e) {
  isDragging.value = false
  const file = e.dataTransfer.files[0]
  if (file) selectFile(file)
}

function handleFileSelect(e) {
  const file = e.target.files[0]
  if (file) selectFile(file)
}

function selectFile(file) {
  const maxSize = 10 * 1024 * 1024
  if (file.size > maxSize) { alert('文件超过 10MB 限制'); return }
  uploadedFile.value = file
  emit('file-selected', file)
}

function clearFile() {
  uploadedFile.value = null
  fileInput.value.value = ''
  emit('file-cleared')
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + 'KB'
  return (bytes/(1024*1024)).toFixed(1) + 'MB'
}
</script>

<style scoped>
.upload-zone { display: flex; align-items: center; padding: 0 4px; flex-shrink: 0; }
.uz-hint { font-size: 11px; color: var(--color-fg-subtle, #888); cursor: pointer; padding: 0 8px; border: 0.5px dashed var(--color-border-default, #ddd); border-radius: 4px; line-height: 24px; transition: all .15s; white-space: nowrap; }
.uz-hint:hover { border-color: var(--color-accent-fg, #2563eb); color: var(--color-accent-fg, #2563eb); }
.uz-file { font-size: 11px; color: var(--color-accent-fg, #2563eb); display: flex; align-items: center; gap: 4px; }
.dragging .uz-hint { border-color: var(--color-accent-fg, #2563eb); background: var(--color-accent-subtle, #eff6ff); }
</style>
