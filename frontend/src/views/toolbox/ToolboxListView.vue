<template>
  <div class="toolbox-view">
    <!-- ===== Header ===== -->
    <header class="page-header">
      <div class="title-block">
        <h1>应急工具箱</h1>
        <p class="subtitle">统一管理应急响应工具与操作文档</p>
      </div>
      <div class="header-actions">
        <div class="search-box">
          <el-icon class="search-icon"><Search /></el-icon>
          <input
            v-model="searchQuery"
            placeholder="搜索工具名称或描述"
            class="search-input-native"
            @input="onSearch"
            @keydown.enter="onSearch"
          />
          <button v-if="searchQuery" class="clear-btn" @click="clearSearch">×</button>
        </div>
        <button class="primary-btn" @click="openUpload">
          <span class="btn-icon">+</span> 上传工具
        </button>
      </div>
    </header>

    <!-- ===== Stats ===== -->
    <section class="stats-section">
      <div class="stat-block">
        <div class="stat-label">工具总数</div>
        <div class="stat-value">{{ stats.total_tools ?? '—' }}</div>
        <div class="stat-trend">已收录到平台</div>
      </div>
      <div class="stat-divider" />
      <div class="stat-block">
        <div class="stat-label">累计下载</div>
        <div class="stat-value">{{ stats.total_downloads ?? '—' }}</div>
        <div class="stat-trend">来自全团队的下载</div>
      </div>
      <div class="stat-divider" />
      <div class="stat-block">
        <div class="stat-label">今日新增</div>
        <div class="stat-value">{{ stats.today_new ?? '—' }}</div>
        <div class="stat-trend">今天被收录的工具</div>
      </div>
      <div class="stat-divider" />
      <div class="stat-block">
        <div class="stat-label">分类数</div>
        <div class="stat-value">{{ stats.category_count ?? '—' }}</div>
        <div class="stat-trend">当前分类总数</div>
      </div>
    </section>

    <!-- ===== Filter + Sort ===== -->
    <section class="filter-section">
      <div class="cat-group">
        <button
          v-for="cat in categoryList"
          :key="cat.name"
          :class="['cat-btn', { active: activeCategory === cat.name }]"
          @click="onCategoryChange(cat.name)"
        >
          <span class="cat-name">{{ cat.name }}</span>
          <span class="cat-count">{{ cat.count }}</span>
        </button>
      </div>
      <div class="filter-spacer" />
      <div class="sort-row">
        <span class="sort-text">排序</span>
        <select v-model="sortBy" class="sort-select" @change="loadTools">
          <option value="created_at">最新上传</option>
          <option value="download_count">下载最多</option>
        </select>
      </div>
    </section>

    <!-- ===== Tool Grid ===== -->
    <section v-loading="loading" class="grid-section">
      <div v-if="tools.length === 0 && !loading" class="empty-state">
        <div class="empty-icon">—</div>
        <div class="empty-title">暂无工具</div>
        <div class="empty-desc">点击右上角"上传工具"开始收录</div>
      </div>
      <div v-else class="tool-grid">
        <article
          v-for="tool in tools"
          :key="tool.id"
          class="tool-card"
          @click="openDetail(tool.id)"
        >
          <div class="card-header">
            <div class="card-icon" :style="{ background: getIconBg(tool.name) }">
              <span>{{ tool.name.charAt(0).toUpperCase() }}</span>
            </div>
            <div class="card-titles">
              <h3 class="card-name" :title="tool.name">{{ tool.name }}</h3>
              <div class="card-meta">
                <span class="version-tag">v{{ tool.current_version }}</span>
                <span class="cat-tag">{{ tool.category }}</span>
              </div>
            </div>
          </div>

          <p v-if="tool.description" class="card-desc">{{ tool.description }}</p>

          <div v-if="tool.tags && tool.tags.length" class="card-tags">
            <span v-for="tag in tool.tags.slice(0, 4)" :key="tag" class="tag-chip">{{ tag }}</span>
            <span v-if="tool.tags.length > 4" class="tag-more">+{{ tool.tags.length - 4 }}</span>
          </div>

          <div class="card-footer">
            <div class="footer-left">
              <span class="download-count">{{ tool.download_count || 0 }} 次下载</span>
              <span class="dot-sep">·</span>
              <span class="updated-date">{{ formatDate(tool.updated_at) }}</span>
            </div>
            <button class="dl-btn" @click.stop="handleDownload(tool.id)">
              下载
            </button>
          </div>
        </article>
      </div>

      <div v-if="total > pageSize" class="pagination">
        <button
          v-for="p in paginationRange"
          :key="p"
          :class="['page-btn', { active: p === currentPage, ellipsis: p === '...' }]"
          :disabled="p === '...'"
          @click="p !== '...' && onPageChange(p)"
        >
          {{ p }}
        </button>
      </div>
    </section>

    <!-- ===== Detail Drawer ===== -->
    <ToolboxDetailDrawer
      :visible="detailDrawerVisible"
      :tool-id="selectedToolId"
      @close="detailDrawerVisible = false"
      @deleted="onToolDeleted"
    />

    <!-- ===== Upload Drawer ===== -->
    <ToolboxUploadDrawer
      :visible="uploadDrawerVisible"
      @close="uploadDrawerVisible = false"
      @success="onUploadSuccess"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { getToolList, getToolStats, getToolCategories, downloadTool } from '@/api/toolbox'
import ToolboxDetailDrawer from './ToolboxDetailDrawer.vue'
import ToolboxUploadDrawer from './ToolboxUploadDrawer.vue'
import { formatServerTime } from '@/utils/time'

// ── Data ──
const tools = ref([])
const stats = ref({})
const categoryList = ref([])
const total = ref(0)
const loading = ref(false)
const searchQuery = ref('')
const activeCategory = ref('全部')
const sortBy = ref('created_at')
const currentPage = ref(1)
const pageSize = 20

// ── Drawer states ──
const detailDrawerVisible = ref(false)
const uploadDrawerVisible = ref(false)
const selectedToolId = ref(null)

// ── Icon backgrounds (muted, professional palette) ──
const palette = [
  '#2c3e50', '#34495e', '#7f8c8d', '#95a5a6',
  '#16a085', '#27ae60', '#2980b9', '#8e44ad',
  '#d35400', '#c0392b',
]

function getIconBg(name) {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return palette[Math.abs(hash) % palette.length]
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return formatServerTime(dateStr, 'MM-DD')
}

const paginationRange = computed(() => {
  const total_ = Math.ceil(total.value / pageSize)
  if (total_ <= 5) {
    return Array.from({ length: total_ }, (_, i) => i + 1)
  }
  const cur = currentPage.value
  const pages = [1]
  if (cur > 3) pages.push('...')
  for (let i = Math.max(2, cur - 1); i <= Math.min(total_ - 1, cur + 1); i++) {
    pages.push(i)
  }
  if (cur < total_ - 2) pages.push('...')
  pages.push(total_)
  return pages
})

// ── Data Loading ──
async function loadTools() {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize,
      sort_by: sortBy.value,
      sort_order: 'desc',
    }
    if (searchQuery.value) params.keyword = searchQuery.value
    if (activeCategory.value && activeCategory.value !== '全部') {
      params.category = activeCategory.value
    }
    const res = await getToolList(params)
    if (res.code === 0 && res.data) {
      tools.value = res.data.items || []
      total.value = res.data.total || 0
    }
  } catch {
    // request.js interceptor handles error messages
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const res = await getToolStats()
    if (res.code === 0 && res.data) {
      stats.value = res.data
    }
  } catch { /* silent */ }
}

async function loadCategories() {
  try {
    const res = await getToolCategories()
    if (res.code === 0 && res.data) {
      const cats = Array.isArray(res.data) ? res.data : (res.data.categories || [])
      const totalCount = cats.reduce((sum, c) => sum + c.count, 0)
      categoryList.value = [
        { name: '全部', count: totalCount },
        ...cats,
      ]
    }
  } catch { /* silent */ }
}

// ── Event Handlers ──
function onSearch() {
  currentPage.value = 1
  loadTools()
}

function clearSearch() {
  searchQuery.value = ''
  onSearch()
}

function onCategoryChange(cat) {
  activeCategory.value = cat
  currentPage.value = 1
  loadTools()
}

function onPageChange(page) {
  currentPage.value = page
  loadTools()
}

function openDetail(id) {
  selectedToolId.value = id
  detailDrawerVisible.value = true
}

function openUpload() {
  uploadDrawerVisible.value = true
}

function handleDownload(id) {
  downloadTool(id)
}

function onToolDeleted() {
  detailDrawerVisible.value = false
  loadTools()
  loadStats()
  loadCategories()
}

function onUploadSuccess() {
  uploadDrawerVisible.value = false
  loadTools()
  loadStats()
  loadCategories()
}

onMounted(() => {
  loadStats()
  loadCategories()
  loadTools()
})
</script>

<style scoped>
.toolbox-view {
  padding: 32px 40px;
  max-width: 1280px;
  margin: 0 auto;
  color: #1f2937;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* ===== Header ===== */
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 28px;
}
.title-block h1 {
  font-size: 22px;
  font-weight: 600;
  color: #111827;
  margin: 0;
  letter-spacing: -0.2px;
}
.title-block .subtitle {
  font-size: 13px;
  color: #6b7280;
  margin: 6px 0 0;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.search-box {
  position: relative;
  width: 280px;
  height: 36px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  display: flex;
  align-items: center;
  padding: 0 12px;
  transition: border-color 0.15s;
}
.search-box:focus-within {
  border-color: #111827;
}
.search-icon {
  font-size: 14px;
  color: #9ca3af;
  margin-right: 8px;
}
.search-input-native {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: #111827;
}
.search-input-native::placeholder {
  color: #9ca3af;
}
.clear-btn {
  border: none;
  background: transparent;
  font-size: 16px;
  color: #9ca3af;
  cursor: pointer;
  padding: 0 4px;
}
.clear-btn:hover {
  color: #374151;
}
.primary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  background: #111827;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.primary-btn:hover {
  background: #1f2937;
}
.btn-icon {
  font-size: 16px;
  line-height: 1;
  margin-top: -2px;
}

/* ===== Stats ===== */
.stats-section {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
}
.stat-block {
  flex: 1;
  padding: 0 8px;
}
.stat-label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 6px;
  font-weight: 500;
}
.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #111827;
  line-height: 1.1;
  letter-spacing: -0.5px;
}
.stat-trend {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 4px;
}
.stat-divider {
  width: 1px;
  height: 36px;
  background: #f3f4f6;
  margin: 0 12px;
}

/* ===== Filter ===== */
.filter-section {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
  gap: 12px;
}
.cat-group {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  flex: 1;
}
.cat-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  font-size: 12px;
  color: #4b5563;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
}
.cat-btn:hover {
  border-color: #d1d5db;
  background: #f9fafb;
}
.cat-btn.active {
  background: #111827;
  color: #fff;
  border-color: #111827;
}
.cat-name {
  font-weight: 500;
}
.cat-count {
  font-size: 11px;
  opacity: 0.65;
}
.cat-btn.active .cat-count {
  opacity: 0.85;
}
.filter-spacer { flex: 1; }
.sort-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #6b7280;
}
.sort-select {
  height: 32px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 0 28px 0 10px;
  font-size: 12px;
  color: #111827;
  background: #fff url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10"><path fill="none" stroke="%236b7280" stroke-width="1.5" d="M2 4l3 3 3-3"/></svg>') no-repeat right 10px center;
  appearance: none;
  cursor: pointer;
}
.sort-select:focus {
  outline: none;
  border-color: #111827;
}

/* ===== Grid ===== */
.grid-section {
  min-height: 280px;
}
.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 80px 0;
  color: #9ca3af;
}
.empty-icon {
  font-size: 32px;
  margin-bottom: 16px;
  font-weight: 200;
  letter-spacing: 4px;
}
.empty-title {
  font-size: 15px;
  color: #374151;
  margin-bottom: 6px;
}
.empty-desc {
  font-size: 13px;
  color: #9ca3af;
}

/* ===== Tool Card ===== */
.tool-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.18s;
  display: flex;
  flex-direction: column;
  position: relative;
}
.tool-card:hover {
  border-color: #d1d5db;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}
.card-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}
.card-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.card-icon span {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0;
}
.card-titles {
  flex: 1;
  min-width: 0;
}
.card-name {
  font-size: 15px;
  font-weight: 600;
  color: #111827;
  margin: 0;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.version-tag {
  font-size: 11px;
  color: #6b7280;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
.cat-tag {
  font-size: 11px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 1px 8px;
  border-radius: 4px;
}
.card-desc {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.5;
  margin: 0 0 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 38px;
}
.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 12px;
}
.tag-chip {
  font-size: 11px;
  color: #6b7280;
  background: #f9fafb;
  border: 1px solid #f3f4f6;
  padding: 1px 8px;
  border-radius: 4px;
}
.tag-more {
  font-size: 11px;
  color: #9ca3af;
}
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid #f3f4f6;
}
.footer-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #9ca3af;
}
.dot-sep {
  opacity: 0.5;
}
.dl-btn {
  height: 28px;
  padding: 0 14px;
  background: #fff;
  color: #111827;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.dl-btn:hover {
  background: #111827;
  color: #fff;
  border-color: #111827;
}

/* ===== Pagination ===== */
.pagination {
  display: flex;
  justify-content: center;
  gap: 4px;
  padding: 32px 0;
}
.page-btn {
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  color: #4b5563;
  cursor: pointer;
  transition: all 0.15s;
}
.page-btn:hover:not(:disabled) {
  border-color: #d1d5db;
}
.page-btn.active {
  background: #111827;
  color: #fff;
  border-color: #111827;
}
.page-btn.ellipsis {
  border: none;
  background: transparent;
  cursor: default;
}
</style>