<template>
  <div class="log-result-list">
    <!-- 加载态 - 骨架屏 -->
    <div v-if="loading" class="skeleton-list">
      <div v-for="n in 3" :key="n" class="skeleton-card">
        <el-skeleton animated>
          <template #template>
            <div class="skeleton-body">
              <el-skeleton-item variant="text" style="width: 40%; height: 16px; margin-bottom: 8px;" />
              <el-skeleton-item variant="text" style="width: 60%; height: 12px; margin-bottom: 4px;" />
              <el-skeleton-item variant="text" style="width: 30%; height: 12px;" />
            </div>
          </template>
        </el-skeleton>
      </div>
    </div>

    <!-- 空结果 -->
    <div v-else-if="items.length === 0" class="empty-state">
      <el-empty description="未找到匹配的日志记录" />
    </div>

    <!-- 结果卡片列表 -->
    <div v-else class="card-list">
      <el-card
        v-for="item in items"
        :key="item.id"
        :class="['log-card', severityCardClass(item.severity)]"
        shadow="hover"
      >
        <!-- 跳转主机详情 -->
        <div class="card-top-right">
          <el-button
            link
            size="small"
            type="primary"
            @click="goToHost(item)"
          >
            跳转主机详情
          </el-button>
        </div>

        <div class="card-header">
          <div class="card-meta">
            <el-tag size="small" effect="plain" type="info">
              {{ item.case_name || `案件 #${item.case_id}` }}
            </el-tag>
            <el-tag size="small" effect="plain" type="info">
              {{ item.hostname || `主机 #${item.host_id}` }}
            </el-tag>
            <el-tag size="small" effect="plain">
              {{ item.collector_type }}
            </el-tag>
            <span class="card-time">{{ formatTime(item.imported_at) }}</span>
          </div>
          <div class="card-severity">
            <span class="severity-dot" :style="{ backgroundColor: severityDotColor(item.severity) }" />
            <el-tag
              :type="severityTagType(item.severity)"
              size="small"
            >
              {{ item.severity || 'info' }}
            </el-tag>
            <!-- IOC 命中标记 -->
            <el-tag v-if="item.ioc_hit" size="small" type="danger" effect="dark" class="ioc-hit-tag">
              IOC
            </el-tag>
          </div>
        </div>

        <!-- JSON 预览（IOC 高亮） -->
        <div class="card-preview">
          <pre class="json-preview" v-html="highlightIoc(item.raw_json)" />
        </div>

        <!-- 操作按钮 -->
        <div class="card-actions">
          <el-button size="small" text @click="$emit('view-detail', item)">查看详情</el-button>
          <el-button size="small" text @click="copyJson(item)">复制 JSON</el-button>

          <template v-if="item.event_created && item.event_id">
            <el-button size="small" type="success" disabled>
              已生成事件
            </el-button>
            <el-button size="small" link type="primary" @click="goToAnalysis(item)">
              · 查看分析中心
            </el-button>
          </template>
          <template v-else>
            <el-button
              size="small"
              type="primary"
              @click="$emit('generate-event', item)"
            >
              + 一键生成事件
            </el-button>
          </template>
        </div>
      </el-card>
    </div>

    <!-- 分页器 -->
    <div class="pagination-bar" v-if="total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="currentPageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        background
        small
        @change="onPageChange"
      />
    </div>

    <!-- 全局复制通知 -->
    <div v-if="copied" class="copy-toast">已复制到剪贴板</div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits([
  'view-detail',
  'generate-event',
  'update:page',
  'update:pageSize',
  'change',
])

const currentPage = ref(props.page)
const currentPageSize = ref(props.pageSize)
const copied = ref(false)

watch(() => props.page, (v) => { currentPage.value = v })
watch(() => props.pageSize, (v) => { currentPageSize.value = v })

function severityCardClass(severity) {
  if (severity === 'critical' || severity === 'high') return 'card-high'
  if (severity === 'medium') return 'card-medium'
  if (severity === 'low') return 'card-low'
  return ''
}

function severityDotColor(severity) {
  const map = { critical: '#DC2626', high: '#EF4444', medium: '#EAB308', low: '#3B82F6', info: '#9CA3AF' }
  return map[severity] || '#9CA3AF'
}

function severityTagType(severity) {
  const map = { critical: 'danger', high: 'danger', medium: 'warning', low: 'primary', info: 'info' }
  return map[severity] || 'info'
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function highlightIoc(rawJson) {
  if (!rawJson) return '{}'
  try {
    const formatted = JSON.stringify(JSON.parse(rawJson), null, 2)
    // 简单 IOC 高亮：匹配 IP 地址
    const highlighted = formatted.replace(
      /(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?)/g,
      '<span class="ioc-highlight">$1</span>',
    )
    return highlighted.substring(0, 300) + (highlighted.length > 300 ? '...' : '')
  } catch {
    return String(rawJson).substring(0, 300)
  }
}

function copyJson(item) {
  const text = item.raw_json || '{}'
  navigator.clipboard.writeText(text).then(() => {
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

function goToHost(item) {
  window.open(`/hosts/${item.host_id}`, '_blank')
}

function goToAnalysis(item) {
  window.open(`/analysis-center?event_id=${item.event_id}`, '_blank')
}

function onPageChange() {
  emit('update:page', currentPage.value)
  emit('update:pageSize', currentPageSize.value)
  emit('change', { page: currentPage.value, pageSize: currentPageSize.value })
}
</script>

<style scoped>
.log-result-list {
  position: relative;
}

/* 骨架屏 */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-card {
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  padding: 16px;
}

.skeleton-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 空状态 */
.empty-state {
  padding: 40px 0;
}

/* 卡片列表 */
.card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.log-card {
  position: relative;
  border-left: 3px solid transparent;
}

.log-card.card-high {
  border-left-color: #EF4444;
  background: #FFF8F8;
}

.log-card.card-medium {
  border-left-color: #EAB308;
}

.log-card.card-low {
  border-left-color: #3B82F6;
}

.card-top-right {
  position: absolute;
  top: 8px;
  right: 8px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.card-time {
  font-size: 11px;
  color: var(--color-fg-muted);
  font-family: monospace;
}

.card-severity {
  display: flex;
  align-items: center;
  gap: 4px;
}

.severity-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.ioc-hit-tag {
  margin-left: 2px;
}

/* JSON 预览 */
.card-preview {
  background: var(--color-canvas-subtle);
  border: 1px solid var(--color-border-default);
  border-radius: 4px;
  padding: 8px 10px;
  max-height: 80px;
  overflow: hidden;
  margin-bottom: 8px;
}

.json-preview {
  margin: 0;
  font-size: 10px;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  color: var(--color-fg-muted);
}

:deep(.ioc-highlight) {
  background: #FEE2E2;
  font-weight: 700;
  color: #DC2626;
  padding: 0 2px;
  border-radius: 2px;
}

/* 操作按钮 */
.card-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

/* 分页器 */
.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 16px 0;
}

/* 复制提示 */
.copy-toast {
  position: fixed;
  bottom: 40px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--color-fg-default);
  color: var(--color-canvas-default);
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 12px;
  z-index: 9999;
  animation: fadeInOut 2s ease;
}

@keyframes fadeInOut {
  0% { opacity: 0; transform: translateX(-50%) translateY(10px); }
  15% { opacity: 1; transform: translateX(-50%) translateY(0); }
  85% { opacity: 1; transform: translateX(-50%) translateY(0); }
  100% { opacity: 0; transform: translateX(-50%) translateY(-10px); }
}
</style>
