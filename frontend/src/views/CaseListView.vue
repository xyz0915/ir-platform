<template>
  <div class="page">
    <!-- Page Header -->
    <div class="page-header">
      <div class="page-header-left">
        <div class="page-title">
          案件管理
          <span class="danger-pill">应急核心</span>
        </div>
        <div class="page-sub">管理所有应急响应案件的生命周期</div>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" @click="showCreateDialog">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新建案件
        </button>
      </div>
    </div>

    <!-- Metrics Bar -->
    <div class="metrics">
      <div class="metric">
        <div class="metric-top"><div class="metric-dot blue"></div><div class="metric-label">总案件数</div></div>
        <div class="metric-value">{{ total }}</div>
        <div class="metric-sub">已创建案件总数</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot green"></div><div class="metric-label">进行中</div></div>
        <div class="metric-value">{{ activeCount }}</div>
        <div class="metric-sub">进行中的案件</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot amber"></div><div class="metric-label">本周新建</div></div>
        <div class="metric-value">{{ weekNewCount }}</div>
        <div class="metric-sub">本周新增案件</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot gray"></div><div class="metric-label">已归档</div></div>
        <div class="metric-value">{{ archivedCount }}</div>
        <div class="metric-sub">已归档案件</div>
      </div>
    </div>

    <!-- Main Card -->
    <div class="card">
      <!-- Toolbar -->
      <div class="toolbar">
        <div class="search-input">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input
            v-model="searchQuery"
            placeholder="搜索案件名称或编号"
            @keyup.enter="loadCases"
          />
        </div>

        <div
          v-for="chip in filterChips"
          :key="chip.value"
          class="filter-chip"
          :class="{ active: statusFilter === chip.value }"
          @click="statusFilter = chip.value; loadCases()"
        >{{ chip.label }}</div>

        <div class="toolbar-spacer"></div>

        <select class="select" style="width: 130px;" v-model="timeRange" @change="loadCases">
          <option value="7">最近 7 天</option>
          <option value="30">最近 30 天</option>
          <option value="90">最近 90 天</option>
          <option value="">全部时间</option>
        </select>

        <button class="btn btn-ghost btn-sm">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>
          排序
        </button>
        <button class="btn btn-ghost btn-sm">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
          筛选
        </button>
      </div>

      <!-- Table -->
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th style="width: 32px;"><input type="checkbox" class="checkbox" :checked="allSelected" @change="toggleAll" /></th>
              <th class="sortable" @click="toggleSort('name')">案件 <span class="sort-icon">{{ sortField === 'name' && sortOrder === 'desc' ? '↓' : '↕' }}</span></th>
              <th>案件编号</th>
              <th>描述</th>
              <th>优先级</th>
              <th>主机</th>
              <th>状态</th>
              <th class="sortable" :class="{ active: sortField === 'created_at' }" @click="toggleSort('created_at')">创建时间 <span class="sort-icon">{{ sortField === 'created_at' && sortOrder === 'desc' ? '↓' : '↕' }}</span></th>
              <th style="width: 120px;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="9" style="text-align: center; padding: 40px 16px; color: var(--color-fg-subtle); font-size: 13px;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 18px; height: 18px; vertical-align: middle; margin-right: 8px; animation: spin 1s linear infinite;"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
                加载中...
              </td>
            </tr>
            <tr v-else-if="cases.length === 0">
              <td colspan="9" style="text-align: center; padding: 40px 16px; color: var(--color-fg-subtle); font-size: 13px;">暂无数据</td>
            </tr>
            <tr v-for="item in cases" :key="item.id" :class="{ 'row-selected': selectedIds.has(item.id) }">
              <td><input type="checkbox" class="checkbox" :checked="selectedIds.has(item.id)" @change="toggleRow(item.id)" /></td>
              <td>
                <div class="case-name">
                  <div class="case-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7"/><path d="M3 7l9 6 9-6"/><path d="M3 7l9-4 9 4"/></svg>
                  </div>
                  <div class="case-name-text">
                    <div class="title">{{ item.name || '—' }}</div>
                    <div class="sub" v-if="item.host_count != null">{{ item.host_count }} 台主机{{ item.log_count != null ? ' · ' + item.log_count + ' 日志' : '' }}</div>
                    <div class="sub" v-else-if="item.description">{{ item.description.substring(0, 20) }}{{ item.description.length > 20 ? '...' : '' }}</div>
                  </div>
                </div>
              </td>
              <td class="td-mono">{{ item.case_number || '—' }}</td>
              <td class="td-muted" style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ item.description || '—' }}</td>
              <td>
                <div class="priority" v-if="item.priority">
                  <div class="priority-dot" :class="'p-' + (item.priority || '')"></div>
                  {{ priorityLabel(item.priority) }}
                </div>
                <span v-else class="td-muted">—</span>
              </td>
              <td>{{ item.host_count != null ? item.host_count : '—' }}</td>
              <td>
                <span class="badge" :class="statusBadgeClass(item.status)">
                  <span class="badge-dot"></span>{{ statusLabel(item.status) }}
                </span>
              </td>
              <td class="td-mono">{{ item.created_at || '—' }}</td>
              <td>
                <div class="row-actions">
                  <button class="icon-btn" title="查看" @click="goToDetail(item.id)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  </button>
                  <button class="icon-btn" title="编辑" @click="goToDetail(item.id)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button class="icon-btn" title="导出">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                  </button>
                  <button class="icon-btn danger" title="删除" @click="handleDelete(item.id)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pagination">
        <div class="pagination-info">显示 {{ pageStart }}-{{ pageEnd }} 条，共 {{ total }} 条</div>
        <div class="pagination-buttons">
          <button class="page-btn" :disabled="currentPage <= 1" @click="goPage(currentPage - 1)">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
          </button>
          <button
            v-for="p in pageButtons"
            :key="p"
            class="page-btn"
            :class="{ active: p === currentPage }"
            @click="goPage(p)"
          >{{ p }}</button>
          <button class="page-btn" :disabled="currentPage >= totalPages" @click="goPage(currentPage + 1)">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Create Case Modal -->
    <div v-if="createDialogVisible" class="modal-overlay" @click.self="createDialogVisible = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">新建案件</div>
          <button class="icon-btn" @click="createDialogVisible = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">案件名称 <span class="required">*</span></label>
            <input class="input" v-model="createForm.name" placeholder="请输入案件名称" />
          </div>
          <div class="form-group">
            <label class="form-label">案件编号</label>
            <input class="input" v-model="createForm.case_number" placeholder="可选，自动分配" />
          </div>
          <div class="form-group">
            <label class="form-label">优先级</label>
            <select class="input" v-model="createForm.priority">
              <option value="">请选择优先级</option>
              <option value="critical">严重</option>
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">描述</label>
            <textarea class="input textarea" v-model="createForm.description" :rows="3" placeholder="案件描述"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="createDialogVisible = false">取消</button>
          <button class="btn btn-primary" :disabled="creating" @click="handleCreate">
            <svg v-if="creating" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px; animation: spin 1s linear infinite;"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
            创建
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import casesApi from '@/api/cases'

const router = useRouter()

const cases = ref([])
const loading = ref(false)
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

const createDialogVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  name: '',
  case_number: '',
  description: '',
  priority: ''
})

// New UI state
const statusFilter = ref('')
const timeRange = ref('30')
const selectedIds = ref(new Set())
const sortField = ref('created_at')
const sortOrder = ref('desc')

const filterChips = [
  { label: '全部状态', value: '' },
  { label: '进行中', value: 'open' },
  { label: '已暂停', value: 'paused' },
  { label: '已归档', value: 'closed' }
]

const activeCount = computed(() => cases.value.filter(c => c.status === 'open' || c.status === 'active').length)
const archivedCount = computed(() => cases.value.filter(c => c.status === 'closed' || c.status === 'archived').length)
const weekNewCount = computed(() => {
  const now = new Date()
  const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
  return cases.value.filter(c => {
    if (!c.created_at) return false
    const d = new Date(c.created_at)
    return d >= weekAgo && d <= now
  }).length
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const pageStart = computed(() => (currentPage.value - 1) * pageSize.value + 1)
const pageEnd = computed(() => Math.min(currentPage.value * pageSize.value, total.value))
const allSelected = computed(() => cases.value.length > 0 && cases.value.every(c => selectedIds.value.has(c.id)))
const pageButtons = computed(() => {
  const pages = []
  const tp = totalPages.value
  const cp = currentPage.value
  let start = Math.max(1, cp - 1)
  let end = Math.min(tp, cp + 1)
  if (end - start < 2) {
    if (start === 1) end = Math.min(tp, start + 2)
    else start = Math.max(1, end - 2)
  }
  for (let i = start; i <= end; i++) pages.push(i)
  return pages
})

onMounted(() => {
  loadCases()
})

async function loadCases() {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value
    }
    if (searchQuery.value) params.search = searchQuery.value
    if (statusFilter.value) params.status = statusFilter.value
    // Note: timeRange and sort are prepared for future API support
    const res = await casesApi.list(currentPage.value, pageSize.value, searchQuery.value)
    cases.value = res.data.items
    total.value = res.data.total
  } catch (error) {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

function showCreateDialog() {
  createForm.name = ''
  createForm.case_number = ''
  createForm.description = ''
  createForm.priority = ''
  createDialogVisible.value = true
}

async function handleCreate() {
  if (!createForm.name) {
    ElMessage.warning('请输入案件名称')
    return
  }
  creating.value = true
  try {
    await casesApi.create({
      name: createForm.name,
      case_number: createForm.case_number || null,
      description: createForm.description || null,
      priority: createForm.priority || null
    })
    ElMessage.success('案件创建成功')
    createDialogVisible.value = false
    loadCases()
  } catch (error) {
    // handled
  } finally {
    creating.value = false
  }
}

function goToDetail(id) {
  router.push(`/cases/${id}`)
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定要删除此案件吗？删除后不可恢复。', '确认删除', {
      type: 'warning'
    })
    await casesApi.delete(id)
    ElMessage.success('删除成功')
    loadCases()
  } catch (error) {
    // cancelled or error
  }
}

function goPage(p) {
  if (p < 1 || p > totalPages.value) return
  currentPage.value = p
  loadCases()
}

function toggleSort(field) {
  if (sortField.value === field) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortField.value = field
    sortOrder.value = 'desc'
  }
  loadCases()
}

function toggleAll() {
  if (allSelected.value) {
    selectedIds.value = new Set()
  } else {
    selectedIds.value = new Set(cases.value.map(c => c.id))
  }
}

function toggleRow(id) {
  const newSet = new Set(selectedIds.value)
  if (newSet.has(id)) {
    newSet.delete(id)
  } else {
    newSet.add(id)
  }
  selectedIds.value = newSet
}

function statusBadgeClass(status) {
  if (status === 'open' || status === 'active') return 'badge-active'
  if (status === 'paused') return 'badge-paused'
  if (status === 'closed' || status === 'archived') return 'badge-closed'
  return 'badge-closed'
}

function statusLabel(status) {
  if (status === 'open' || status === 'active') return '进行中'
  if (status === 'paused') return '已暂停'
  if (status === 'closed' || status === 'archived') return '已归档'
  return status || '—'
}

function priorityClass(priority) {
  const p = (priority || '').toLowerCase()
  if (p === '高' || p === 'high' || p === 'critical' || p === '严重') return 'p-high'
  if (p === '中' || p === 'medium') return 'p-medium'
  if (p === '低' || p === 'low') return 'p-low'
  return 'p-low'
}

function priorityLabel(p) {
  const map = { critical: '严重', high: '高', medium: '中', low: '低' }
  return map[p] || p || '—'
}
</script>

<style scoped>
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 32px 24px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Noto Sans SC', sans-serif;
  color: var(--color-fg-default, #111111);
}

/* Page Header */
.page-header {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 24px;
}
.page-header-left { flex: 1; }
.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 20px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}
.page-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  margin-top: 4px;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Danger Pill */
.danger-pill {
  font-size: 10px;
  color: var(--color-danger-fg, #dc2626);
  background: var(--color-danger-subtle, #fef2f2);
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 500;
  line-height: 1.6;
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 500;
  border-radius: var(--r-btn, 6px);
  cursor: pointer;
  transition: all 0.12s;
  white-space: nowrap;
  border: 0.5px solid transparent;
  font-family: inherit;
  line-height: 1;
}
.btn:disabled { opacity: 0.4; pointer-events: none; }
.btn-default {
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  border-color: var(--color-border-default, #e5e5e5);
}
.btn-default:hover { background: var(--color-canvas-subtle, #fafafa); }
.btn-primary {
  background: var(--color-accent-fg, #2563eb);
  color: white;
  border-color: var(--color-accent-fg, #2563eb);
}
.btn-primary:hover { background: #1d4ed8; }
.btn-ghost {
  background: transparent;
  color: var(--color-fg-muted, #555555);
  border-color: transparent;
}
.btn-ghost:hover { background: var(--color-canvas-inset, #f5f5f5); color: var(--color-fg-default, #111111); }
.btn-sm { height: 26px; padding: 0 10px; font-size: 12px; }
.btn svg { width: 14px; height: 14px; flex-shrink: 0; }

/* Metrics */
.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.metric {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  padding: 16px 20px;
}
.metric-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.metric-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.metric-dot.blue { background: var(--color-accent-fg, #2563eb); }
.metric-dot.green { background: var(--color-success-fg, #16a34a); }
.metric-dot.amber { background: var(--color-warning-fg, #d97706); }
.metric-dot.gray { background: var(--color-fg-light, #a3a3a3); }
.metric-label { font-size: 12px; font-weight: 400; color: var(--color-fg-subtle, #888888); }
.metric-value { font-size: 22px; font-weight: 500; color: var(--color-fg-default, #111111); line-height: 1.2; }
.metric-sub { font-size: 11px; font-weight: 400; color: var(--color-fg-subtle, #888888); margin-top: 4px; }

/* Card */
.card {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
}

/* Toolbar */
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 20px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}
.search-input {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 12px;
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  width: 320px;
  transition: border-color 0.12s;
}
.search-input:focus-within { border-color: var(--color-accent-fg, #2563eb); }
.search-input svg {
  width: 14px;
  height: 14px;
  color: var(--color-fg-light, #a3a3a3);
  flex-shrink: 0;
}
.search-input input {
  border: none;
  outline: none;
  flex: 1;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  background: transparent;
}
.search-input input::placeholder { color: var(--color-fg-light, #a3a3a3); }
.toolbar-spacer { flex: 1; }

/* Filter Chip */
.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-muted, #555555);
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}
.filter-chip:hover { border-color: var(--color-fg-light, #a3a3a3); }
.filter-chip.active {
  background: var(--color-canvas-inset, #f5f5f5);
  border-color: var(--color-fg-light, #a3a3a3);
  color: var(--color-fg-default, #111111);
  font-weight: 500;
}

/* Select */
.select {
  height: 32px;
  padding: 0 32px 0 12px;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  outline: none;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23888' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
}

/* Table */
.table-wrap {
  border-radius: var(--r-card, 10px);
  overflow: hidden;
}
table { width: 100%; border-collapse: collapse; }
thead { background: var(--color-canvas-subtle, #fafafa); }
th {
  padding: 10px 16px;
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle, #888888);
  text-align: left;
  white-space: nowrap;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--color-fg-default, #111111); }
th .sort-icon { display: inline-block; margin-left: 4px; opacity: 0.4; }
th.sortable.active { color: var(--color-fg-default, #111111); }
th.sortable.active .sort-icon { opacity: 1; }
td {
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  border-bottom: 0.5px solid var(--color-canvas-inset, #f5f5f5);
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--color-canvas-subtle, #fafafa); }
tr.row-selected td { background: var(--color-accent-subtle, #eff6ff); }
.td-muted { color: var(--color-fg-subtle, #888888); }
.td-mono { font-family: 'SF Mono', 'Fira Code', 'Consolas', 'Liberation Mono', monospace; font-size: 11px; color: var(--color-fg-subtle, #888888); }

/* Case Name */
.case-name {
  display: flex;
  align-items: center;
  gap: 8px;
}
.case-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: var(--color-canvas-inset, #f5f5f5);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--color-fg-muted, #555555);
}
.case-name-text { display: flex; flex-direction: column; gap: 1px; }
.case-name-text .title { font-size: 13px; font-weight: 500; }
.case-name-text .sub { font-size: 11px; color: var(--color-fg-subtle, #888888); }

/* Status Badge */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 20px;
  padding: 0 7px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 4px;
  white-space: nowrap;
}
.badge-dot { width: 5px; height: 5px; border-radius: 50%; }
.badge-active { background: var(--color-success-subtle, #f0fdf4); color: var(--color-success-fg, #16a34a); }
.badge-paused { background: var(--color-warning-subtle, #fffbeb); color: var(--color-warning-fg, #d97706); }
.badge-closed { background: var(--color-canvas-inset, #f5f5f5); color: var(--color-fg-subtle, #888888); }

/* Priority */
.priority {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-fg-muted, #555555);
}
.priority-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.priority-dot.p-critical { background: #dc2626; }
.priority-dot.p-high { background: #d97706; }
.priority-dot.p-medium { background: #2563eb; }
.priority-dot.p-low { background: #16a34a; }

/* Row Actions */
.row-actions { display: flex; align-items: center; gap: 4px; }
.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--r-btn, 6px);
  border: none;
  background: transparent;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--color-fg-muted, #555555);
  transition: all 0.12s;
}
.icon-btn:hover { background: var(--color-canvas-inset, #f5f5f5); color: var(--color-fg-default, #111111); }
.icon-btn.danger:hover { color: var(--color-danger-fg, #dc2626); background: var(--color-danger-subtle, #fef2f2); }
.icon-btn svg { width: 14px; height: 14px; }

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
}
.pagination-info { font-size: 12px; color: var(--color-fg-subtle, #888888); }
.pagination-buttons { display: flex; align-items: center; gap: 4px; }
.page-btn {
  min-width: 28px;
  height: 28px;
  padding: 0 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-fg-muted, #555555);
  cursor: pointer;
  background: var(--color-canvas-default, #ffffff);
  font-family: inherit;
}
.page-btn:hover { border-color: var(--color-fg-light, #a3a3a3); }
.page-btn.active {
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
  font-weight: 500;
  background: var(--color-accent-subtle, #eff6ff);
}
.page-btn:disabled { opacity: 0.3; cursor: default; }

/* Checkbox */
.checkbox { width: 14px; height: 14px; accent-color: var(--color-accent-fg, #2563eb); cursor: pointer; }

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-container, 12px);
  max-width: 520px;
  width: 100%;
  margin: 0 16px;
}
.modal-header {
  padding: 20px 24px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-title { font-size: 16px; font-weight: 500; }
.modal-header .icon-btn { width: 24px; height: 24px; }
.modal-body { padding: 16px 24px 20px; }
.modal-footer {
  padding: 12px 24px;
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* Form */
.form-group { margin-bottom: 16px; }
.form-group:last-child { margin-bottom: 0; }
.form-label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-muted, #555555);
  margin-bottom: 6px;
}
.form-label .required { color: var(--color-danger-fg, #dc2626); }
.input {
  height: 32px;
  padding: 0 12px;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  font-size: 13px;
  font-weight: 400;
  outline: none;
  transition: border-color 0.12s;
  width: 100%;
  font-family: inherit;
  color: var(--color-fg-default, #111111);
  background: var(--color-canvas-default, #ffffff);
  box-sizing: border-box;
}
.input:focus { border-color: var(--color-accent-fg, #2563eb); }
.input::placeholder { color: var(--color-fg-light, #a3a3a3); }
.textarea {
  height: auto;
  padding: 10px 12px;
  resize: vertical;
  line-height: 1.5;
}

/* Loading animation */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
