<template>
  <div class="whitelist-view">
    <div class="page">

      <!-- Header -->
      <div class="page-header">
        <div class="page-header-left">
          <div class="page-title">
            白名单配置
            <span class="title-badge">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              信任列表
            </span>
          </div>
          <div class="page-sub">系统内置 + 用户自定义白名单 — 命中后跳过检测引擎告警</div>
        </div>
        <div class="page-actions">
          <button class="btn btn-default">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
            重置默认
          </button>
          <button class="btn btn-primary" @click="showAddDialog = true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            添加白名单
          </button>
        </div>
      </div>

      <!-- Metrics -->
      <div class="metrics">
        <div class="metric">
          <div class="metric-top"><div class="metric-dot green"></div><div class="metric-label">总白名单</div></div>
          <div class="metric-value">{{ metrics.total }}</div>
          <div class="metric-sub">{{ metrics.builtinCount }} 内置 + {{ metrics.userCount }} 用户</div>
        </div>
        <div class="metric">
          <div class="metric-top"><div class="metric-dot green"></div><div class="metric-label">已启用</div></div>
          <div class="metric-value">{{ metrics.enabled }}</div>
          <div class="metric-sub up">{{ metrics.enabledPercent }}% 激活率</div>
        </div>
        <div class="metric">
          <div class="metric-top"><div class="metric-dot blue"></div><div class="metric-label">路径规则</div></div>
          <div class="metric-value">{{ metrics.paths }}</div>
          <div class="metric-sub">文件系统路径白名单</div>
        </div>
        <div class="metric">
          <div class="metric-top"><div class="metric-dot amber"></div><div class="metric-label">进程名规则</div></div>
          <div class="metric-value">{{ metrics.processes }}</div>
          <div class="metric-sub">进程名称白名单</div>
        </div>
      </div>

      <!-- Main Card -->
      <div class="card">

        <!-- Toolbar -->
        <div class="toolbar">
          <div class="search-bar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input v-model="searchQuery" placeholder="搜索匹配值或描述" />
          </div>

          <span class="filter-chip" :class="{ active: categoryFilter === '' }" @click="categoryFilter = ''; loadWhitelist()">全部</span>
          <span class="filter-chip" :class="{ active: categoryFilter === 'path' }" @click="categoryFilter = 'path'; loadWhitelist()">路径</span>
          <span class="filter-chip" :class="{ active: categoryFilter === 'process_name' }" @click="categoryFilter = 'process_name'; loadWhitelist()">进程名</span>
          <span class="filter-chip" :class="{ active: categoryFilter === 'signature' }" @click="categoryFilter = 'signature'; loadWhitelist()">签名</span>

          <div class="toolbar-spacer"></div>

          <select v-model="sourceFilter" class="select" style="width:120px;">
            <option value="">全部来源</option>
            <option value="default">内置默认</option>
            <option value="user">用户规则</option>
          </select>
          <select v-model="statusFilter" class="select" style="width:90px;">
            <option value="">全部</option>
            <option value="1">已启用</option>
            <option value="0">已禁用</option>
          </select>
          <button class="btn btn-ghost btn-sm">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
            高级筛选
          </button>
        </div>

        <!-- Loading bar -->
        <div v-if="loading" class="table-loading-bar">
          <div class="table-loading-track"></div>
        </div>

        <!-- Table -->
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th style="width:28px;"><input type="checkbox" class="cbx" /></th>
                <th style="width:50px;">ID</th>
                <th style="width:84px;">类别</th>
                <th>匹配值</th>
                <th style="width:100px;">来源</th>
                <th>描述</th>
                <th style="width:90px;">命中统计</th>
                <th style="width:52px;">启用</th>
                <th style="width:62px;">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in filteredData" :key="row.id" :class="{ disabled: row.enabled !== 1 }">
                <td><input type="checkbox" class="cbx" :disabled="row.enabled !== 1" /></td>
                <td class="td-mono td-muted">{{ row.id }}</td>
                <td>
                  <div class="cat-cell">
                    <div class="cat-icon" :class="categoryIconClass(row.category)">
                      <svg v-if="row.category === 'path'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7"/><path d="M3 7l9 6 9-6"/><path d="M3 7l9-4 9 4"/></svg>
                      <svg v-else-if="row.category === 'process_name'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
                      <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
                    </div>
                    <span class="badge" :class="categoryBadgeClass(row.category)">{{ categoryLabel(row.category) }}</span>
                  </div>
                </td>
                <td>
                  <div class="pattern-text">
                    <div class="main" :class="{ 'td-disabled': row.enabled !== 1 }">{{ row.pattern }}</div>
                    <div class="hint" :class="{ 'td-disabled': row.enabled !== 1 }">{{ patternHint(row.category) }}</div>
                  </div>
                </td>
                <td>
                  <span class="badge" :class="row.source === 'default' ? 'badge-builtin' : 'badge-user'">{{ row.source === 'default' ? '内置默认' : '用户规则' }}</span>
                </td>
                <td :class="{ 'td-disabled': row.enabled !== 1 }" class="td-muted">{{ row.description || '-' }}</td>
                <td class="td-mono td-muted" :class="{ 'td-disabled': row.enabled !== 1 }">-</td>
                <td>
                  <label class="toggle">
                    <input type="checkbox" :checked="row.enabled === 1" @change="row.enabled = row.enabled === 1 ? 0 : 1; handleToggle(row)" />
                    <div class="toggle-slider"></div>
                  </label>
                </td>
                <td>
                  <div class="row-actions">
                    <button v-if="row.source === 'default'" class="icon-btn" title="编辑" disabled>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button v-else class="icon-btn" title="编辑">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <span v-if="row.source === 'default'" class="delete-text" style="opacity:0.4">删除</span>
                    <span v-else class="delete-text" @click="confirmDelete(row)">删除</span>
                  </div>
                </td>
              </tr>
              <tr v-if="!loading && filteredData.length === 0">
                <td colspan="9" style="text-align:center;padding:32px 14px;color:var(--color-fg-subtle);font-size:12px;">暂无白名单数据</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <div class="pagination">
          <div class="pg-info">显示 1-{{ filteredData.length }} 条，共 {{ filteredData.length }} 条</div>
          <div class="pg-btns">
            <button class="pg-btn" disabled>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
            </button>
            <button class="pg-btn active">1</button>
            <button class="pg-btn" disabled>
              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
            </button>
          </div>
        </div>

      </div>
    </div>

    <!-- Add Modal -->
    <div v-if="showAddDialog" class="modal-overlay" @click.self="showAddDialog = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">添加白名单</div>
          <button class="modal-close" @click="showAddDialog = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="fg">
              <label class="fl">类别 <span class="fl-hint">必填</span></label>
              <select v-model="addForm.category" class="fs">
                <option value="path">路径</option>
                <option value="process_name">进程名</option>
                <option value="signature">签名</option>
              </select>
            </div>
            <div class="fg">
              <label class="fl">匹配类型</label>
              <select v-model="addForm.matchType" class="fs">
                <option value="prefix">前缀</option>
                <option value="exact">精确</option>
                <option value="regex">正则</option>
                <option value="wildcard">通配</option>
              </select>
            </div>
          </div>
          <div class="fg">
            <label class="fl">匹配值 <span class="fl-hint">必填</span></label>
            <input v-model="addForm.pattern" class="fi" placeholder="如 C:\Windows\System32\ 或 svchost.exe" style="font-family:var(--font-mono);" />
          </div>
          <div class="fg">
            <label class="fl">描述</label>
            <input v-model="addForm.description" class="fi" placeholder="为什么需要加入白名单" />
          </div>
          <div class="fg" style="margin-bottom:0;">
            <label class="fl">备注 <span class="fl-hint">选填</span></label>
            <textarea v-model="addForm.remark" class="fta" rows="2" placeholder="补充说明..."></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showAddDialog = false">取消</button>
          <button class="btn btn-primary" @click="handleAdd">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import whitelistApi from '@/api/whitelist'

const whitelistData = ref([])
const loading = ref(false)
const categoryFilter = ref('')
const showAddDialog = ref(false)
const addForm = ref({
  category: 'path',
  pattern: '',
  description: '',
  matchType: 'prefix',
  remark: ''
})

// New UI state
const searchQuery = ref('')
const sourceFilter = ref('')
const statusFilter = ref('')

onMounted(() => {
  loadWhitelist()
})

async function loadWhitelist() {
  loading.value = true
  try {
    const params = {}
    if (categoryFilter.value) {
      params.category = categoryFilter.value
    }
    const res = await whitelistApi.getWhitelist(params)
    whitelistData.value = res.data || []
  } catch (error) {
    // handled
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  if (!addForm.value.category || !addForm.value.pattern) {
    ElMessage.warning('请填写类别和匹配值')
    return
  }
  try {
    await whitelistApi.createWhitelist({
      category: addForm.value.category,
      pattern: addForm.value.pattern,
      description: addForm.value.description
    })
    ElMessage.success('添加成功')
    showAddDialog.value = false
    addForm.value = { category: 'path', pattern: '', description: '', matchType: 'prefix', remark: '' }
    loadWhitelist()
  } catch (error) {
    // handled
  }
}

async function handleDelete(row) {
  try {
    await whitelistApi.deleteWhitelist(row.id)
    ElMessage.success('删除成功')
    loadWhitelist()
  } catch (error) {
    // handled
  }
}

async function handleToggle(row) {
  try {
    await whitelistApi.updateWhitelist(row.id, { enabled: row.enabled === 1 })
  } catch (error) {
    // revert on error
    row.enabled = row.enabled === 1 ? 0 : 1
  }
}

function categoryLabel(category) {
  const map = { path: '路径', process_name: '进程名', signature: '签名' }
  return map[category] || category
}

function categoryTagType(category) {
  const map = { path: 'primary', process_name: 'success', signature: 'warning' }
  return map[category] || 'info'
}

// New helper functions
function categoryIconClass(category) {
  const map = { path: 'path', process_name: 'process', signature: 'signature' }
  return map[category] || 'path'
}

function categoryBadgeClass(category) {
  const map = { path: 'badge-path', process_name: 'badge-process', signature: 'badge-signature' }
  return map[category] || 'badge-path'
}

function patternHint(category) {
  const map = { path: '文件路径', process_name: '进程名称', signature: '数字签名' }
  return map[category] || ''
}

function confirmDelete(row) {
  if (confirm('确认删除该白名单项？')) {
    handleDelete(row)
  }
}

const metrics = computed(() => {
  const data = whitelistData.value
  const total = data.length
  const enabled = data.filter(d => d.enabled === 1 || d.enabled === true).length
  const paths = data.filter(d => d.category === 'path').length
  const processes = data.filter(d => d.category === 'process_name').length
  const builtinCount = data.filter(d => d.source === 'default').length
  const userCount = data.filter(d => d.source !== 'default').length
  const enabledPercent = total ? Math.round((enabled / total) * 100) : 0
  return { total, enabled, enabledPercent, paths, processes, builtinCount, userCount }
})

const filteredData = computed(() => {
  let data = whitelistData.value
  if (sourceFilter.value) {
    data = data.filter(d => sourceFilter.value === 'default' ? d.source === 'default' : d.source !== 'default')
  }
  if (statusFilter.value !== '') {
    const val = parseInt(statusFilter.value)
    data = data.filter(d => d.enabled === val)
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    data = data.filter(d =>
      (d.pattern && d.pattern.toLowerCase().includes(q)) ||
      (d.description && d.description.toLowerCase().includes(q))
    )
  }
  return data
})
</script>

<style scoped>
.whitelist-view {
  padding: 0;
}
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 28px 24px;
}

/* Header */
.page-header {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 24px;
}
.page-header-left {
  flex: 1;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: 500;
  margin: 0;
}
.title-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--color-success-subtle, #f0fdf4);
  color: var(--color-success-fg, #16a34a);
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.title-badge svg {
  width: 10px;
  height: 10px;
}
.page-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  margin-top: 3px;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s;
  white-space: nowrap;
  border: 0.5px solid transparent;
  font-family: inherit;
}
.btn:disabled {
  opacity: 0.4;
  pointer-events: none;
}
.btn-default {
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  border-color: var(--color-border-default, #e5e5e5);
}
.btn-default:hover {
  background: var(--color-canvas-subtle, #fafafa);
  border-color: var(--color-fg-light, #a3a3a3);
}
.btn-primary {
  background: var(--color-accent-fg, #2563eb);
  color: white;
  border-color: var(--color-accent-fg, #2563eb);
}
.btn-primary:hover {
  background: #1d4ed8;
}
.btn-ghost {
  background: transparent;
  color: var(--color-fg-muted, #555555);
  border-color: transparent;
}
.btn-ghost:hover {
  background: var(--color-canvas-inset, #f5f5f5);
}
.btn-sm {
  height: 26px;
  padding: 0 8px;
  font-size: 11px;
}
.btn svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

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
  border-radius: 10px;
  padding: 14px 18px;
}
.metric-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.metric-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.metric-dot.green { background: var(--color-success-fg, #16a34a); }
.metric-dot.amber { background: var(--color-warning-fg, #d97706); }
.metric-dot.blue { background: var(--color-accent-fg, #2563eb); }
.metric-dot.red { background: var(--color-danger-fg, #dc2626); }
.metric-label {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
}
.metric-value {
  font-size: 20px;
  font-weight: 500;
  line-height: 1.2;
}
.metric-sub {
  font-size: 11px;
  color: var(--color-fg-subtle, #888888);
  margin-top: 4px;
}
.metric-sub.up {
  color: var(--color-success-fg, #16a34a);
}

/* Card */
.card {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 10px;
}

/* Toolbar */
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 14px 20px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 12px;
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  width: 280px;
  transition: border-color 0.12s;
}
.search-bar:focus-within {
  border-color: var(--color-accent-fg, #2563eb);
}
.search-bar svg {
  width: 13px;
  height: 13px;
  color: var(--color-fg-light, #a3a3a3);
  flex-shrink: 0;
}
.search-bar input {
  border: none;
  outline: none;
  flex: 1;
  font-size: 12px;
  background: transparent;
  color: var(--color-fg-default, #111111);
}
.search-bar input::placeholder {
  color: var(--color-fg-light, #a3a3a3);
}
.select {
  height: 30px;
  padding: 0 28px 0 10px;
  font-size: 12px;
  color: var(--color-fg-default, #111111);
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  outline: none;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23888' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
}
.toolbar-spacer {
  flex: 1;
}

/* Filter Chips */
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
  user-select: none;
}
.filter-chip:hover {
  border-color: var(--color-fg-light, #a3a3a3);
}
.filter-chip.active {
  background: var(--color-accent-subtle, #eff6ff);
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
  font-weight: 500;
}

/* Toggle */
.toggle {
  position: relative;
  display: inline-block;
  width: 28px;
  height: 16px;
  cursor: pointer;
}
.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}
.toggle-slider {
  position: absolute;
  inset: 0;
  background: var(--color-border-default, #e5e5e5);
  border-radius: 999px;
  transition: 0.15s;
}
.toggle-slider::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 2px;
  width: 12px;
  height: 12px;
  background: white;
  border-radius: 50%;
  transition: 0.15s;
}
.toggle input:checked + .toggle-slider {
  background: var(--color-success-fg, #16a34a);
}
.toggle input:checked + .toggle-slider::before {
  transform: translateX(12px);
}
.toggle input:disabled + .toggle-slider {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Badge */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 6px;
  font-size: 10px;
  font-weight: 500;
  border-radius: 3px;
  white-space: nowrap;
}
.badge-path {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
}
.badge-process {
  background: #f0fdf4;
  color: #16a34a;
}
.badge-signature {
  background: var(--color-warning-subtle, #fffbeb);
  color: var(--color-warning-fg, #d97706);
}
.badge-builtin {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-subtle, #888888);
}
.badge-user {
  background: #e0f2fe;
  color: #0369a1;
}

/* Table */
.table-wrap {
  overflow: hidden;
}
table {
  width: 100%;
  border-collapse: collapse;
}
thead {
  background: var(--color-canvas-subtle, #fafafa);
}
th {
  padding: 9px 14px;
  font-size: 10px;
  font-weight: 500;
  color: var(--color-fg-subtle, #888888);
  text-align: left;
  white-space: nowrap;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}
td {
  padding: 11px 14px;
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  border-bottom: 0.5px solid var(--color-canvas-inset, #f5f5f5);
  vertical-align: middle;
}
tr:last-child td {
  border-bottom: none;
}
tr:hover td {
  background: var(--color-canvas-subtle, #fafafa);
}
.td-mono {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 11px;
}
.td-muted {
  color: var(--color-fg-subtle, #888888);
}
.td-disabled {
  color: var(--color-fg-light, #a3a3a3);
}
tr.disabled td {
  background: var(--color-canvas-subtle, #fafafa);
}
tr.disabled:hover td {
  background: var(--color-canvas-inset, #f5f5f5);
}

/* Category Cell */
.cat-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.cat-icon {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.cat-icon.path {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
}
.cat-icon.process {
  background: #f0fdf4;
  color: var(--color-success-fg, #16a34a);
}
.cat-icon.signature {
  background: var(--color-warning-subtle, #fffbeb);
  color: var(--color-warning-fg, #d97706);
}
.cat-icon svg {
  width: 12px;
  height: 12px;
}

/* Pattern Cell */
.pattern-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pattern-text .main {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: var(--color-fg-default, #111111);
}
.pattern-text .hint {
  font-size: 10px;
  color: var(--color-fg-subtle, #888888);
}

/* Row Actions */
.row-actions {
  display: flex;
  gap: 2px;
  justify-content: flex-end;
}
.icon-btn {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-fg-muted, #555555);
}
.icon-btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-default, #111111);
}
.icon-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.icon-btn svg {
  width: 13px;
  height: 13px;
}
.delete-text {
  color: var(--color-danger-fg, #dc2626);
  font-size: 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
}
.delete-text:disabled {
  color: var(--color-fg-light, #a3a3a3);
  cursor: not-allowed;
}

/* Checkbox */
.cbx {
  width: 14px;
  height: 14px;
  accent-color: var(--color-accent-fg, #2563eb);
  cursor: pointer;
}

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
}
.pg-info {
  font-size: 11px;
  color: var(--color-fg-subtle, #888888);
}
.pg-btns {
  display: flex;
  gap: 3px;
}
.pg-btn {
  min-width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 4px;
  font-size: 11px;
  color: var(--color-fg-muted, #555555);
  cursor: pointer;
  background: var(--color-canvas-default, #ffffff);
}
.pg-btn:hover {
  border-color: var(--color-fg-light, #a3a3a3);
}
.pg-btn.active {
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
  font-weight: 500;
  background: var(--color-accent-subtle, #eff6ff);
}
.pg-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

/* Modal */
.modal-overlay {
  background: rgba(0,0,0,0.18);
  border-radius: 12px;
  padding: 32px 24px;
  margin-top: 24px;
}
.modal {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 12px;
  max-width: 540px;
  margin: 0 auto;
}
.modal-header {
  padding: 18px 22px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.modal-title {
  font-size: 14px;
  font-weight: 500;
}
.modal-close {
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  color: var(--color-fg-light, #a3a3a3);
  display: flex;
  align-items: center;
  justify-content: center;
}
.modal-close:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-default, #111111);
}
.modal-body {
  padding: 14px 22px 18px;
}
.modal-footer {
  padding: 10px 22px;
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

/* Form */
.fg {
  margin-bottom: 12px;
}
.fl {
  display: block;
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
  margin-bottom: 5px;
}
.fl-hint {
  font-size: 10px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  margin-left: 6px;
}
.fi {
  width: 100%;
  height: 30px;
  padding: 0 10px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  font-size: 12px;
  outline: none;
  color: var(--color-fg-default, #111111);
  background: var(--color-canvas-default, #ffffff);
}
.fi:focus {
  border-color: var(--color-accent-fg, #2563eb);
}
.fta {
  width: 100%;
  padding: 8px 10px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  font-size: 11px;
  outline: none;
  resize: vertical;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  line-height: 1.5;
  color: var(--color-fg-default, #111111);
  background: var(--color-canvas-default, #ffffff);
}
.fta:focus {
  border-color: var(--color-accent-fg, #2563eb);
}
.fs {
  width: 100%;
  height: 30px;
  padding: 0 28px 0 10px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  font-size: 12px;
  outline: none;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23888' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  background-color: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
}
.fs:focus {
  border-color: var(--color-accent-fg, #2563eb);
}

/* Loading bar */
.table-loading-bar {
  height: 2px;
  background: var(--color-accent-subtle, #eff6ff);
  overflow: hidden;
}
.table-loading-track {
  width: 30%;
  height: 100%;
  background: var(--color-accent-fg, #2563eb);
  animation: loading-slide 1.5s infinite ease-in-out;
}

@keyframes loading-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }
}

</style>
