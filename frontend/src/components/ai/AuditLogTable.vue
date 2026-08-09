<template>
  <div class="audit-log-table">
    <!-- 表格 -->
    <el-table
      :data="logs"
      v-loading="loading"
      stripe
      border
      class="log-table"
      @sort-change="handleSort"
    >
      <el-table-column prop="created_at" label="时间" width="170" sortable="custom">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column prop="host_name" label="主机名" min-width="140" show-overflow-tooltip />
      <el-table-column prop="model_name" label="模型" width="150" show-overflow-tooltip />
      <el-table-column prop="total_tokens" label="Token数" width="100" align="right" sortable="custom">
        <template #default="{ row }">
          {{ formatNumber(row.total_tokens) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="latency_ms" label="延迟" width="90" align="right">
        <template #default="{ row }">
          {{ row.latency_ms != null ? row.latency_ms + 'ms' : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" align="center" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="openDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-row">
      <span class="total-hint">共 {{ pagination.total }} 条记录</span>
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :total="pagination.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @change="loadData"
        small
      />
    </div>

    <!-- 详情 Dialog -->
    <el-dialog
      v-model="detailVisible"
      title="审计日志详情"
      width="750px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-if="detail" class="audit-detail-body">
        <el-descriptions :column="2" border size="small" class="mb-20">
          <el-descriptions-item label="时间">
            {{ formatTime(detail.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="主机名">
            {{ detail.host_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="模型">
            {{ detail.model_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(detail.status)" size="small">
              {{ statusLabel(detail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Prompt Tokens">
            {{ formatNumber(detail.prompt_tokens) }}
          </el-descriptions-item>
          <el-descriptions-item label="Completion Tokens">
            {{ formatNumber(detail.completion_tokens) }}
          </el-descriptions-item>
          <el-descriptions-item label="总 Token 数">
            {{ formatNumber(detail.total_tokens) }}
          </el-descriptions-item>
          <el-descriptions-item label="延迟">
            {{ detail.latency_ms != null ? detail.latency_ms + 'ms' : '-' }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 错误信息 -->
        <div v-if="detail.error_message" class="detail-section mb-15">
          <h4 class="section-subtitle error-title">错误信息</h4>
          <div class="error-content">
            <pre>{{ detail.error_message }}</pre>
          </div>
        </div>

        <!-- 请求 Prompt -->
        <div class="detail-section mb-15">
          <h4 class="section-subtitle">请求 Prompt</h4>
          <div class="code-block" :class="{ collapsed: !promptExpanded }">
            <pre>{{ detail.prompt || '(无)' }}</pre>
          </div>
          <el-button
            v-if="isLongText(detail.prompt)"
            type="primary"
            link
            size="small"
            @click="promptExpanded = !promptExpanded"
            class="mt-5"
          >
            {{ promptExpanded ? '收起' : '展开全部' }}
          </el-button>
        </div>

        <!-- AI 回复 -->
        <div class="detail-section">
          <h4 class="section-subtitle">AI 回复</h4>
          <div class="code-block" :class="{ collapsed: !responseExpanded }">
            <pre>{{ detail.response || '(无)' }}</pre>
          </div>
          <el-button
            v-if="isLongText(detail.response)"
            type="primary"
            link
            size="small"
            @click="responseExpanded = !responseExpanded"
            class="mt-5"
          >
            {{ responseExpanded ? '收起' : '展开全部' }}
          </el-button>
        </div>
      </div>
      <div v-else v-loading="detailLoading" style="min-height:200px;" />
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { getAiAuditLogs, getAiAuditLogDetail } from '@/api/ai'
import { formatServerTime } from '@/utils/time'

// ============================================================
// State
// ============================================================
const logs = ref([])
const loading = ref(false)
const pagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
})
const sortState = reactive({
  field: '',
  order: '',
})

// 详情 Dialog
const detailVisible = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const promptExpanded = ref(false)
const responseExpanded = ref(false)

// ============================================================
// Lifecycle
// ============================================================
onMounted(() => {
  loadData()
})

// ============================================================
// Data Loading
// ============================================================
async function loadData() {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
    }
    if (sortState.field) {
      params.sort_by = sortState.field
      params.sort_order = sortState.order === 'ascending' ? 'asc' : 'desc'
    }
    const res = await getAiAuditLogs(params)
    const data = res.data
    logs.value = data?.items || data?.list || data || []
    pagination.total = data?.total || logs.value.length
  } catch {
    logs.value = []
    pagination.total = 0
  } finally {
    loading.value = false
  }
}

// ============================================================
// Sort
// ============================================================
function handleSort({ prop, order }) {
  sortState.field = prop || ''
  sortState.order = order || ''
  pagination.page = 1
  loadData()
}

// ============================================================
// Detail
// ============================================================
async function openDetail(row) {
  detailVisible.value = true
  detail.value = null
  promptExpanded.value = false
  responseExpanded.value = false
  detailLoading.value = true
  try {
    const res = await getAiAuditLogDetail(row.id)
    detail.value = res.data
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

// ============================================================
// Helpers
// ============================================================
function formatTime(t) {
  if (!t) return '-'
  return formatServerTime(t)
}

function formatNumber(n) {
  if (n == null) return '0'
  return Number(n).toLocaleString()
}

function statusTagType(status) {
  const map = {
    success: 'success',
    completed: 'success',
    error: 'danger',
    failed: 'danger',
    cancelled: 'info',
    running: 'warning',
  }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = {
    success: '成功',
    completed: '成功',
    error: '失败',
    failed: '失败',
    cancelled: '已取消',
    running: '运行中',
  }
  return map[status] || status || '-'
}

function isLongText(text) {
  return text && text.length > 300
}
</script>

<style scoped>
.audit-log-table {
  width: 100%;
}

.log-table {
  width: 100%;
}

.pagination-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 15px;
}

.total-hint {
  font-size: 13px;
  color: #909399;
}

/* ============================================================
   Detail Dialog
   ============================================================ */
.audit-detail-body {
  max-height: 65vh;
  overflow-y: auto;
}

.section-subtitle {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.error-title {
  color: #f56c6c;
}

.code-block {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  max-height: 400px;
  overflow-y: auto;
  transition: max-height 0.3s;
}

.code-block.collapsed {
  max-height: 200px;
  overflow: hidden;
}

.code-block pre {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
  font-family: Consolas, 'Courier New', monospace;
}

.error-content {
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 6px;
  padding: 12px;
  max-height: 200px;
  overflow-y: auto;
}

.error-content pre {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 13px;
  line-height: 1.7;
  color: #f56c6c;
  font-family: Consolas, 'Courier New', monospace;
}

.mb-15 {
  margin-bottom: 15px;
}

.mb-20 {
  margin-bottom: 20px;
}

.mt-5 {
  margin-top: 5px;
}

.detail-section {
  margin-top: 12px;
}
</style>
