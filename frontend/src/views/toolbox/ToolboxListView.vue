<template>
  <div class="toolbox-view">
    <!-- ===== Page Header ===== -->
    <div class="page-header">
      <div>
        <h1 class="page-title">应急工具箱</h1>
        <p class="page-subtitle">统一管理应急响应工具与操作文档</p>
      </div>
      <div class="header-actions">
        <el-input
          v-model="searchQuery"
          placeholder="搜索工具名称或描述…"
          clearable
          :prefix-icon="Search"
          class="search-input"
          @input="onSearch"
          @clear="onSearch"
        />
        <el-button type="primary" @click="openUpload">
          <el-icon><Upload /></el-icon> 上传工具
        </el-button>
      </div>
    </div>

    <!-- ===== Stats Row ===== -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon stat-icon-total"><el-icon size="22"><FolderOpened /></el-icon></div>
        <div>
          <div class="stat-num">{{ stats.total_tools ?? '-' }}</div>
          <div class="stat-label">工具总数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-dl"><el-icon size="22"><Download /></el-icon></div>
        <div>
          <div class="stat-num">{{ stats.total_downloads ?? '-' }}</div>
          <div class="stat-label">累计下载</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-new"><el-icon size="22"><CircleCheck /></el-icon></div>
        <div>
          <div class="stat-num">{{ stats.today_new ?? '-' }}</div>
          <div class="stat-label">今日新增</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon-cat"><el-icon size="22"><Collection /></el-icon></div>
        <div>
          <div class="stat-num">{{ stats.category_count ?? '-' }}</div>
          <div class="stat-label">分类</div>
        </div>
      </div>
    </div>

    <!-- ===== Filter Bar ===== -->
    <div class="filter-bar">
      <div class="cat-group">
        <span
          v-for="cat in categoryList"
          :key="cat.name"
          :class="['cat-chip', { active: activeCategory === cat.name }]"
          @click="onCategoryChange(cat.name)"
        >
          {{ cat.name }}
          <span class="cat-cnt">{{ cat.count }}</span>
        </span>
      </div>
      <div class="filter-spacer" />
      <div class="sort-selector">
        <span class="sort-label">排序：</span>
        <el-select v-model="sortBy" size="small" style="width: 120px" @change="loadTools">
          <el-option label="最新上传" value="created_at" />
          <el-option label="下载最多" value="download_count" />
        </el-select>
      </div>
    </div>

    <!-- ===== Tool Grid ===== -->
    <div v-loading="loading" class="tool-grid-wrap">
      <div v-if="tools.length === 0 && !loading" class="empty-state">
        <el-icon :size="48"><FolderDelete /></el-icon>
        <p>暂无匹配的工具</p>
      </div>
      <div v-else class="tool-grid">
        <div
          v-for="tool in tools"
          :key="tool.id"
          class="tool-card"
          @click="openDetail(tool.id)"
        >
          <div class="card-top">
            <div :class="['card-icon', getIconColor(tool.name)]">
              {{ tool.name.charAt(0).toUpperCase() }}
            </div>
            <div class="card-info">
              <div class="card-name">{{ tool.name }}</div>
              <div class="card-meta">
                <span class="card-version">v{{ tool.current_version }}</span>
                <span class="card-cat-tag">{{ tool.category }}</span>
                <span :class="['doc-badge', tool.has_doc ? 'yes' : 'no']">
                  ● {{ tool.has_doc ? '有文档' : '仅工具' }}
                </span>
              </div>
            </div>
          </div>
          <div class="card-desc">{{ tool.description || '暂无描述' }}</div>
          <div class="card-footer">
            <div class="card-stats">
              <span>{{ tool.download_count }} 次下载</span>
              <span>{{ formatDate(tool.updated_at) }}</span>
            </div>
            <el-button
              size="small"
              text
              class="dl-btn-inline"
              @click.stop="handleDownload(tool.id)"
            >
              <el-icon><Download /></el-icon> 下载
            </el-button>
          </div>
        </div>
      </div>

      <!-- ===== Pagination ===== -->
      <div v-if="total > pageSize" class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="onPageChange"
        />
      </div>
    </div>

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
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Search, Upload, Download, FolderOpened, CircleCheck, Collection, FolderDelete,
} from '@element-plus/icons-vue'
import { getToolList, getToolStats, getToolCategories, downloadTool } from '@/api/toolbox'
import ToolboxDetailDrawer from './ToolboxDetailDrawer.vue'
import ToolboxUploadDrawer from './ToolboxUploadDrawer.vue'

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

// ── Category colors for icon backgrounds ──
const iconColors = ['#5856d6', '#007aff', '#ff3b30', '#ff9500', '#34c759', '#8e8e93', '#af52de', '#ff2d55']

function getIconColor(name) {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  const idx = Math.abs(hash) % iconColors.length
  return { '--icon-bg': iconColors[idx] }
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

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
  } catch (err) {
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
  } catch {
    // silent
  }
}

async function loadCategories() {
  try {
    const res = await getToolCategories()
    if (res.code === 0 && res.data) {
      const cats = res.data.categories || []
      const totalCount = cats.reduce((sum, c) => sum + c.count, 0)
      categoryList.value = [
        { name: '全部', count: totalCount },
        ...cats,
      ]
    }
  } catch {
    // silent
  }
}

// ── Event Handlers ──
function onSearch() {
  currentPage.value = 1
  loadTools()
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
  ElMessage.success('上传成功')
}

// ── Init ──
onMounted(() => {
  loadStats()
  loadCategories()
  loadTools()
})
</script>

<style scoped>
.toolbox-view {
  padding: 24px 28px;
  max-width: 1280px;
  margin: 0 auto;
}

/* ── Page Header ── */
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 24px;
}
.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-fg-default, #1d1d1f);
  margin: 0;
}
.page-subtitle {
  font-size: 13px;
  color: var(--color-fg-muted, #86868b);
  margin-top: 4px;
}
.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.search-input {
  width: 280px;
}

/* ── Stats Row ── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--color-canvas-default, #fff);
  border-radius: 10px;
  border: 1px solid var(--color-border-default, #e8e8ed);
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-icon-total { background: #eef0ff; color: #5856d6; }
.stat-icon-dl { background: #e8f5e9; color: #34c759; }
.stat-icon-new { background: #fff3e0; color: #ff9500; }
.stat-icon-cat { background: #e3f2fd; color: #007aff; }
.stat-num {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-fg-default, #1d1d1f);
  line-height: 1.2;
}
.stat-label {
  font-size: 12px;
  color: var(--color-fg-muted, #86868b);
  line-height: 1.4;
}

/* ── Filter Bar ── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.cat-group {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  flex: 1;
}
.cat-chip {
  padding: 0 14px;
  height: 30px;
  line-height: 30px;
  border-radius: 15px;
  font-size: 12px;
  border: 1px solid var(--color-border-default, #e8e8ed);
  background: var(--color-canvas-default, #fff);
  color: var(--color-fg-muted, #515154);
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;
  white-space: nowrap;
}
.cat-chip:hover {
  border-color: var(--color-border-hover, #d2d2d7);
  background: var(--color-canvas-subtle, #f5f5f5);
}
.cat-chip.active {
  background: var(--el-color-primary, #0071e3);
  color: #fff;
  border-color: var(--el-color-primary, #0071e3);
}
.cat-cnt {
  opacity: 0.55;
  margin-left: 4px;
  font-size: 11px;
}
.filter-spacer { flex: 1; }
.sort-selector {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-fg-muted, #86868b);
}

/* ── Tool Grid ── */
.tool-grid-wrap {
  min-height: 200px;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 0;
  color: var(--color-fg-muted, #86868b);
  gap: 12px;
}
.empty-state p {
  font-size: 14px;
}
.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}

/* ── Tool Card ── */
.tool-card {
  background: var(--color-canvas-default, #fff);
  border-radius: 10px;
  border: 1px solid var(--color-border-default, #e8e8ed);
  padding: 20px;
  cursor: pointer;
  transition: all 0.18s;
  display: flex;
  flex-direction: column;
}
.tool-card:hover {
  border-color: var(--color-border-hover, #d2d2d7);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.card-top {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 8px;
}
.card-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  flex-shrink: 0;
  background: var(--icon-bg, #8e8e93);
}
.card-info {
  flex: 1;
  min-width: 0;
}
.card-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-fg-default, #1d1d1f);
}
.card-meta {
  font-size: 12px;
  color: var(--color-fg-muted, #86868b);
  margin-top: 2px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.card-cat-tag {
  background: var(--color-canvas-subtle, #f5f5f5);
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--color-fg-muted, #515154);
}
.doc-badge { font-size: 11px; }
.doc-badge.yes { color: #34c759; }
.doc-badge.no { color: #ff9500; }
.card-desc {
  font-size: 13px;
  color: var(--color-fg-muted, #515154);
  line-height: 1.5;
  margin-bottom: 12px;
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-subtle, #f2f2f7);
}
.card-stats {
  font-size: 12px;
  color: var(--color-fg-muted, #86868b);
  display: flex;
  gap: 14px;
}
.dl-btn-inline {
  font-size: 12px;
}

/* ── Pagination ── */
.pagination-wrap {
  display: flex;
  justify-content: center;
  padding: 16px 0 40px;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .toolbox-view { padding: 16px; }
  .tool-grid { grid-template-columns: 1fr; }
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .search-input { width: 100%; }
  .page-header { flex-direction: column; align-items: stretch; }
  .header-actions { flex-direction: column; }
}
</style>
