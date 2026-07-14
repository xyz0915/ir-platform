<template>
  <div class="log-result-list">
    <!-- 加载态 - 骨架屏 -->
    <div v-if="loading" class="skeleton-list">
      <div v-for="n in 3" :key="n" class="skeleton-card">
        <div class="skeleton-body">
          <div class="skeleton-line skeleton-line-40" />
          <div class="skeleton-line skeleton-line-60" />
          <div class="skeleton-line skeleton-line-30" />
        </div>
      </div>
    </div>

    <!-- 空结果 -->
    <div v-else-if="items.length === 0" class="empty-state">
      <div class="empty-icon">
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
          <rect x="8" y="6" width="24" height="28" rx="3" stroke="currentColor" stroke-width="1.5" fill="none"/>
          <path d="M16 16h8M16 21h8M16 26h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="empty-title">未找到匹配的日志记录</div>
    </div>

    <!-- 结果卡片列表 -->
    <div v-else class="card-list">
      <div
        v-for="item in items"
        :key="item.id"
        :class="['log-card', severityCardClass(item.severity)]"
      >
        <!-- 跳转主机详情 -->
        <div class="card-top-right">
          <button class="btn btn-link btn-xs" @click="goToHost(item)">
            跳转主机详情
          </button>
        </div>

        <div class="card-header">
          <div class="card-meta">
            <span class="meta-tag">{{ item.case_name || `案件 #${item.case_id}` }}</span>
            <span class="meta-tag">{{ item.hostname || `主机 #${item.host_id}` }}</span>
            <span class="meta-tag">{{ item.collector_type }}</span>
            <span class="card-time">{{ formatTime(item.imported_at) }}</span>
          </div>
          <div class="card-severity">
            <span
              class="severity-badge"
              :class="'badge-' + (item.severity || 'info')"
            >
              {{ item.severity || 'info' }}
            </span>
            <!-- IOC 命中标记 -->
            <span v-if="item.ioc_hit" class="ioc-hit-tag">IOC</span>
          </div>
        </div>

        <!-- JSON 预览（IOC 高亮） -->
        <div class="card-preview">
          <pre class="json-preview" v-html="highlightIoc(item.raw_json)" />
        </div>

        <!-- 操作按钮 -->
        <div class="card-actions">
          <button class="btn btn-text" @click="$emit('view-detail', item)">查看详情</button>
          <button class="btn btn-text" @click="copyJson(item)">复制 JSON</button>

          <template v-if="item.event_created && item.event_id">
            <button class="btn btn-text btn-disabled" disabled>
              已生成事件
            </button>
            <button class="btn btn-link" @click="goToAnalysis(item)">
              查看分析中心
            </button>
          </template>
          <template v-else>
            <button class="btn btn-primary btn-sm" @click="$emit('generate-event', item)">
              一键生成事件
            </button>
          </template>
        </div>
      </div>
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
  const map = { critical: '#dc2626', high: '#dc2626', medium: '#d97706', low: '#2563eb', info: '#a3a3a3' }
  return map[severity] || '#a3a3a3'
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

/* ===== 骨架屏 ===== */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-card {
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  padding: 16px;
  background: var(--color-canvas-default, #ffffff);
}

.skeleton-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skeleton-line {
  height: 12px;
  background: var(--color-canvas-inset, #f5f5f5);
  border-radius: 4px;
  animation: skeleton-pulse 1.5s infinite;
}

.skeleton-line-40 { width: 40%; }
.skeleton-line-60 { width: 60%; }
.skeleton-line-30 { width: 30%; }

@keyframes skeleton-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* ===== 空状态 ===== */
.empty-state {
  text-align: center;
  padding: 48px 20px;
  color: var(--color-fg-subtle, #888888);
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
  opacity: 0.4;
}

.empty-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-fg-muted, #555555);
}

/* ===== 卡片列表 ===== */
.card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.log-card {
  position: relative;
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  padding: 16px;
  transition: border-color 0.15s;
}

.log-card:hover {
  border-color: var(--color-accent-fg, #2563eb);
}

.log-card.card-high {
  border-left: 3px solid var(--color-risk-critical, #dc2626);
}

.log-card.card-medium {
  border-left: 3px solid var(--color-risk-medium, #d97706);
}

.log-card.card-low {
  border-left: 3px solid var(--color-risk-low, #2563eb);
}

.card-top-right {
  position: absolute;
  top: 8px;
  right: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 400;
  border-radius: 4px;
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-muted, #555555);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
}

.card-time {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  font-family: monospace;
}

.card-severity {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

/* ===== Severity Badges ===== */
.severity-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 400;
  border-radius: 4px;
  line-height: 1.4;
}

.severity-badge.badge-critical,
.severity-badge.badge-high {
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-risk-critical, #dc2626);
  border: 0.5px solid rgba(220, 38, 38, 0.2);
}

.severity-badge.badge-medium {
  background: var(--color-warning-subtle, #fffbeb);
  color: var(--color-risk-medium, #d97706);
  border: 0.5px solid rgba(217, 119, 6, 0.2);
}

.severity-badge.badge-low {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-risk-low, #2563eb);
  border: 0.5px solid rgba(37, 99, 235, 0.2);
}

.severity-badge.badge-info {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-subtle, #888888);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
}

.ioc-hit-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 500;
  border-radius: 4px;
  background: var(--color-danger-fg, #dc2626);
  color: #ffffff;
}

/* ===== JSON 预览 ===== */
.card-preview {
  background: var(--color-canvas-inset, #f5f5f5);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  padding: 8px 12px;
  max-height: 80px;
  overflow: hidden;
  margin-bottom: 12px;
}

.json-preview {
  margin: 0;
  font-size: 11px;
  font-weight: 400;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  color: var(--color-fg-default, #111111);
}

:deep(.ioc-highlight) {
  background: var(--color-danger-subtle, #fef2f2);
  font-weight: 500;
  color: var(--color-danger-fg, #dc2626);
  padding: 0 2px;
  border-radius: 2px;
}

/* ===== 操作按钮 ===== */
.card-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

/* ===== Buttons ===== */
.btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.4;
  font-family: inherit;
}

.btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
}

.btn-text {
  border: none;
  background: transparent;
  color: var(--color-accent-fg, #2563eb);
  padding: 4px 8px;
}

.btn-text:hover {
  background: var(--color-accent-subtle, #eff6ff);
}

.btn-link {
  border: none;
  background: transparent;
  color: var(--color-accent-fg, #2563eb);
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
}

.btn-link:hover {
  text-decoration: underline;
}

.btn-primary {
  background: var(--color-accent-fg, #2563eb);
  color: #ffffff;
  border-color: var(--color-accent-fg, #2563eb);
}

.btn-primary:hover {
  opacity: 0.9;
  background: var(--color-accent-fg, #2563eb);
}

.btn-sm {
  padding: 4px 8px;
  font-size: 11px;
}

.btn-xs {
  padding: 2px 6px;
  font-size: 11px;
}

.btn-disabled {
  opacity: 0.5;
  cursor: not-allowed;
  color: var(--color-fg-subtle, #888888);
}

/* ===== 分页器 ===== */
.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 16px 0;
}

/* ===== 复制提示 ===== */
.copy-toast {
  position: fixed;
  bottom: 40px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--color-fg-default, #111111);
  color: var(--color-canvas-default, #ffffff);
  padding: 8px 16px;
  border-radius: var(--r-btn, 6px);
  font-size: 12px;
  font-weight: 400;
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
