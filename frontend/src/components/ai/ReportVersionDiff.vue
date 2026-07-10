<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="onVisibleChange"
    title="报告版本对比"
    width="1100px"
    :close-on-click-modal="false"
    destroy-on-close
    @open="onOpen"
  >
    <!-- 版本选择 -->
    <div class="diff-controls mb-20">
      <div class="version-select-group">
        <span class="version-label">版本 1：</span>
        <el-select
          v-model="version1"
          placeholder="选择版本1"
          class="version-select"
          @change="onVersion1Change"
          :loading="versionLoading"
        >
          <el-option
            v-for="v in versions"
            :key="v.version || v.id"
            :label="versionLabel(v)"
            :value="v.version || v.id"
          />
        </el-select>
      </div>
      <div class="version-select-group">
        <span class="version-label">版本 2：</span>
        <el-select
          v-model="version2"
          placeholder="选择版本2"
          class="version-select"
          @change="onVersion2Change"
          :loading="versionLoading"
        >
          <el-option
            v-for="v in versions"
            :key="v.version || v.id"
            :label="versionLabel(v)"
            :value="v.version || v.id"
          />
        </el-select>
      </div>
    </div>

    <!-- 对比内容区域 -->
    <div class="diff-content" v-loading="contentLoading">
      <!-- 空状态 -->
      <el-empty
        v-if="!report1 && !report2 && !contentLoading"
        description="请选择两个版本进行对比"
        :image-size="60"
      />

      <!-- 左右分栏对比 -->
      <el-row v-if="report1 || report2" :gutter="16" class="diff-row">
        <!-- 左侧：版本 1 -->
        <el-col :span="12">
          <div class="diff-panel">
            <div class="diff-panel-header">
              <el-tag type="primary" size="small">版本 1</el-tag>
              <span class="diff-panel-version" v-if="version1">{{ version1 }}</span>
            </div>
            <div class="diff-panel-body" v-if="report1">
              <!-- 风险评估 -->
              <div class="diff-section" v-if="report1.risk_assessment">
                <h5 class="diff-section-title">🛡️ 风险评估</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report1.risk_assessment)" />
              </div>
              <!-- 威胁分析 -->
              <div class="diff-section" v-if="report1.threat_analysis">
                <h5 class="diff-section-title">🔍 威胁分析</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report1.threat_analysis)" />
              </div>
              <!-- 时间线解读 -->
              <div class="diff-section" v-if="report1.timeline_analysis">
                <h5 class="diff-section-title">⏱️ 时间线解读</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report1.timeline_analysis)" />
              </div>
              <!-- 处置建议 -->
              <div class="diff-section" v-if="report1.recommendations">
                <h5 class="diff-section-title">💡 处置建议</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report1.recommendations)" />
              </div>
              <!-- 无内容 -->
              <el-empty v-if="!hasAnyContent(report1)" description="该版本无报告内容" :image-size="50" />
            </div>
            <el-empty v-else-if="version1" description="加载中..." :image-size="50" />
          </div>
        </el-col>

        <!-- 右侧：版本 2 -->
        <el-col :span="12">
          <div class="diff-panel">
            <div class="diff-panel-header">
              <el-tag type="success" size="small">版本 2</el-tag>
              <span class="diff-panel-version" v-if="version2">{{ version2 }}</span>
            </div>
            <div class="diff-panel-body" v-if="report2">
              <!-- 风险评估 -->
              <div class="diff-section" v-if="report2.risk_assessment">
                <h5 class="diff-section-title">🛡️ 风险评估</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report2.risk_assessment)" />
              </div>
              <!-- 威胁分析 -->
              <div class="diff-section" v-if="report2.threat_analysis">
                <h5 class="diff-section-title">🔍 威胁分析</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report2.threat_analysis)" />
              </div>
              <!-- 时间线解读 -->
              <div class="diff-section" v-if="report2.timeline_analysis">
                <h5 class="diff-section-title">⏱️ 时间线解读</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report2.timeline_analysis)" />
              </div>
              <!-- 处置建议 -->
              <div class="diff-section" v-if="report2.recommendations">
                <h5 class="diff-section-title">💡 处置建议</h5>
                <div class="diff-section-content markdown-body" v-html="renderPlainText(report2.recommendations)" />
              </div>
              <!-- 无内容 -->
              <el-empty v-if="!hasAnyContent(report2)" description="该版本无报告内容" :image-size="50" />
            </div>
            <el-empty v-else-if="version2" description="加载中..." :image-size="50" />
          </div>
        </el-col>
      </el-row>
    </div>

    <template #footer>
      <el-button @click="onClose">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import dayjs from 'dayjs'
import { getAiReportVersions, getAiReportByVersion } from '@/api/ai'

// ============================================================
// Props & Emits
// ============================================================
const props = defineProps({
  /** 主机 ID */
  hostId: {
    type: Number,
    required: true,
  },
  /** Dialog 可见性 */
  visible: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:visible', 'close'])

// ============================================================
// State
// ============================================================
const versions = ref([])
const versionLoading = ref(false)
const version1 = ref('')
const version2 = ref('')
const report1 = ref(null)
const report2 = ref(null)
const contentLoading = ref(false)

// ============================================================
// Lifecycle
// ============================================================

/** Dialog 打开时加载版本列表 */
function onOpen() {
  resetState()
  loadVersions()
}

/** Dialog 关闭时清理 */
function onClose() {
  emit('close')
  emit('update:visible', false)
}

function onVisibleChange(val) {
  if (!val) {
    onClose()
  }
}

function resetState() {
  versions.value = []
  version1.value = ''
  version2.value = ''
  report1.value = null
  report2.value = null
}

// ============================================================
// Version Loading
// ============================================================
async function loadVersions() {
  versionLoading.value = true
  try {
    const res = await getAiReportVersions(props.hostId)
    versions.value = (res.data && Array.isArray(res.data) ? res.data : []) || []
  } catch {
    versions.value = []
  } finally {
    versionLoading.value = false
  }
}

// ============================================================
// Version Selection
// ============================================================
async function onVersion1Change(ver) {
  if (!ver) {
    report1.value = null
    return
  }
  contentLoading.value = true
  try {
    const res = await getAiReportByVersion(props.hostId, ver)
    report1.value = res.data || res
  } catch {
    report1.value = null
  } finally {
    contentLoading.value = false
  }
}

async function onVersion2Change(ver) {
  if (!ver) {
    report2.value = null
    return
  }
  contentLoading.value = true
  try {
    const res = await getAiReportByVersion(props.hostId, ver)
    report2.value = res.data || res
  } catch {
    report2.value = null
  } finally {
    contentLoading.value = false
  }
}

// ============================================================
// Helpers
// ============================================================

/** 格式化版本标签 */
function versionLabel(v) {
  const ver = v.version || v.id
  const time = v.created_at ? dayjs(v.created_at).format('MM-DD HH:mm') : ''
  let label = `v${ver}`
  if (time) label += ` - ${time}`
  if (v.model_used) label += ` (${v.model_used})`
  return label
}

/** 检查报告是否有任何内容 */
function hasAnyContent(report) {
  if (!report) return false
  return !!(report.risk_assessment || report.threat_analysis || report.timeline_analysis || report.recommendations)
}

/**
 * 将 Markdown/纯文本转为简单 HTML（无 marked 依赖时的降级方案）
 * 做基本的换行和段落处理
 */
function renderPlainText(text) {
  if (!text) return ''
  // 将换行转为 <br>，双换行为段落
  const escaped = escapeHtml(text)
  // 将连续的换行作为段落分隔
  const paragraphs = escaped.split('\n\n')
  return paragraphs
    .map((p) => {
      const lines = p.split('\n').join('<br>')
      return `<p style="margin:4px 0;">${lines}</p>`
    })
    .join('')
}

/** 基本 HTML 转义 */
function escapeHtml(str) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }
  return str.replace(/[&<>"']/g, (ch) => map[ch] || ch)
}
</script>

<style scoped>
/* ============================================================
   Controls
   ============================================================ */
.diff-controls {
  display: flex;
  gap: 24px;
  align-items: center;
}

.version-select-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.version-label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}

.version-select {
  width: 280px;
}

/* ============================================================
   Diff Content
   ============================================================ */
.diff-content {
  min-height: 300px;
}

.diff-row {
  min-height: 400px;
}

/* ============================================================
   Diff Panel
   ============================================================ */
.diff-panel {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.diff-panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}

.diff-panel-version {
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}

.diff-panel-body {
  flex: 1;
  padding: 12px 14px;
  overflow-y: auto;
  max-height: 55vh;
}

/* ============================================================
   Sections
   ============================================================ */
.diff-section {
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px dashed #e4e7ed;
}

.diff-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
}

.diff-section-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px;
}

.diff-section-content {
  font-size: 13px;
  line-height: 1.8;
  color: #606266;
}

/* ============================================================
   Markdown 简单样式
   ============================================================ */
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 4px 0;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #e4e7ed;
  padding: 6px 10px;
  text-align: left;
  font-size: 12px;
}

.markdown-body :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

.markdown-body :deep(pre) {
  background: #1e1e1e;
  border-radius: 6px;
  padding: 10px;
  overflow-x: auto;
  margin: 4px 0;
}

.markdown-body :deep(code) {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}

.markdown-body :deep(p code) {
  background: #f0f0f0;
  padding: 2px 5px;
  border-radius: 3px;
  color: #e74c3c;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 10px 0 4px;
  color: #303133;
}

.markdown-body :deep(blockquote) {
  border-left: 3px solid #409eff;
  padding: 2px 10px;
  color: #606266;
  background: #f0f7ff;
  margin: 4px 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 18px;
}

/* ============================================================
   Utility
   ============================================================ */
.mb-20 {
  margin-bottom: 20px;
}
</style>
