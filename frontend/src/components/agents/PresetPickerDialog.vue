<template>
  <el-dialog
    :model-value="visible"
    class="preset-picker-dialog"
    width="780px"
    :close-on-click-modal="false"
    @update:model-value="(v) => { if (!v) emit('close') }"
    @close="emit('close')"
  >
    <template #header>
      <div class="picker-header">
        <div class="picker-title">加载预设</div>
        <div class="picker-subtitle">选择一个已保存的工作流模板，加载到画布</div>
      </div>
    </template>

    <!-- 搜索 + 分类筛选 -->
    <div class="toolbar">
      <div class="search-box">
        <el-icon class="search-icon"><Search /></el-icon>
        <input
          v-model="keyword"
          class="search-input"
          placeholder="搜索名称 / 描述 / 标签"
        />
        <button v-if="keyword" class="clear-btn" @click="keyword = ''">×</button>
      </div>
      <el-select
        v-model="activeCategory"
        class="category-select"
        placeholder="全部分类"
      >
        <el-option label="全部分类" value="__all__" />
        <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
      </el-select>
    </div>

    <!-- 预设卡片区 -->
    <div v-loading="loading" class="card-area">
      <div v-if="!loading && filteredPresets.length === 0" class="empty-state">
        <div class="empty-icon">—</div>
        <div class="empty-title">{{ presets.length === 0 ? '暂无预设' : '无匹配预设' }}</div>
        <div class="empty-desc">
          {{
            presets.length === 0
              ? '可在画布中设计流程后通过「另存为」创建预设'
              : '试试调整搜索关键词或分类'
          }}
        </div>
      </div>

      <div v-else class="card-grid">
        <article
          v-for="preset in filteredPresets"
          :key="preset.id"
          :class="['preset-card', { selected: selectedId === preset.id }]"
          @click="onSelect(preset)"
        >
          <div class="card-top">
            <div class="card-icon" :style="{ background: getIconBg(preset.name) }">
              {{ getInitial(preset.name) }}
            </div>
            <div class="card-main">
              <div class="card-name-row">
                <h4 class="card-name" :title="preset.name">{{ preset.name }}</h4>
                <span v-if="selectedId === preset.id" class="selected-check">✓</span>
              </div>
              <div class="card-meta">
                <span class="node-count">{{ preset.nodeCount }} 节点</span>
                <span v-if="preset.typeSummary" class="dot-sep">·</span>
                <span v-if="preset.typeSummary" class="type-summary" :title="preset.typeSummary">
                  {{ preset.typeSummary }}
                </span>
              </div>
            </div>
          </div>

          <p v-if="preset.description" class="card-desc">{{ preset.description }}</p>

          <div v-if="preset.tags && preset.tags.length" class="card-tags">
            <span v-for="tag in preset.tags.slice(0, 4)" :key="tag" class="tag-chip">{{ tag }}</span>
            <span v-if="preset.tags.length > 4" class="tag-more">+{{ preset.tags.length - 4 }}</span>
          </div>

          <div class="card-footer">
            <span class="footer-text">创建于 {{ formatDate(preset.created_at) }}</span>
            <span class="dot-sep">·</span>
            <span class="footer-text">使用 {{ preset.usage_count || 0 }} 次</span>
            <span v-if="preset.author" class="footer-text">· {{ preset.author }}</span>
          </div>
        </article>
      </div>
    </div>

    <!-- 选中预览区 -->
    <div v-if="selectedPreset" class="preview-bar">
      <span class="preview-label">已选</span>
      <span class="preview-name">{{ selectedPreset.name }}</span>
      <span class="preview-detail">
        {{ selectedPreset.nodeCount }} 个节点{{ selectedPreset.typeSummary ? ' · ' + selectedPreset.typeSummary : '' }}
      </span>
    </div>

    <template #footer>
      <el-button @click="emit('close')">取消</el-button>
      <el-button type="primary" :disabled="!selectedPreset" @click="onConfirm">
        加载选中
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import agentApi from '@/api/agent'

/**
 * 产品级「加载预设」卡片选择器。
 *
 * 替代 PipelineRedesignView 中基于 ElMessageBox 的简陋列表：
 *  - 搜索（名称/描述/标签）+ 分类下拉
 *  - 卡片网格：图标、节点数、类型分布摘要、描述（2 行截断）、标签、创建时间、使用次数
 *  - 点击选中（蓝色描边 + ✓）、底部选中预览、加载后调用 recordPresetUse 统计热度
 */
const props = defineProps({
  visible: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'selected'])

const presets = ref([])
const loading = ref(false)
const keyword = ref('')
const activeCategory = ref('__all__')
const selectedId = ref(null)

const selectedPreset = computed(
  () => presets.value.find((p) => p.id === selectedId.value) || null,
)

/** 将后端预设行归一化为卡片数据：计算 nodeCount 与 typeSummary. */
function parsePreset(raw) {
  const items = (raw.nodes && Array.isArray(raw.nodes) && raw.nodes.length)
    ? raw.nodes
    : (Array.isArray(raw.agents) ? raw.agents : [])
  const nodeCount = items.length

  // 类型分布摘要：优先统计各 agent 的 type 字段；无 type 则回退统计 name/agent
  const counts = {}
  items.forEach((item) => {
    let key = ''
    if (typeof item === 'string') {
      key = item
    } else if (item && typeof item === 'object') {
      key = item.type || item.name || item.agent || ''
    }
    if (key) counts[key] = (counts[key] || 0) + 1
  })
  const entries = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
  const typeSummary = entries
    .map(([k, v]) => (v > 1 ? `${k}×${v}` : k))
    .join(' · ')

  const tags = Array.isArray(raw.tags) ? raw.tags : []
  return { ...raw, nodeCount, typeSummary, tags }
}

function loadPresets() {
  loading.value = true
  agentApi.pipeline
    .getPresets()
    .then((res) => {
      const list = (res && res.data) || res || []
      presets.value = (Array.isArray(list) ? list : []).map(parsePreset)
    })
    .catch(() => {
      // axios 拦截器已提示错误，这里仅兜底为空态
      presets.value = []
    })
    .finally(() => {
      loading.value = false
    })
}

const categoryOptions = computed(() => {
  const set = new Set()
  presets.value.forEach((p) => {
    const c = p.category || 'other'
    if (c) set.add(c)
  })
  return Array.from(set).sort()
})

const filteredPresets = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return presets.value.filter((p) => {
    if (activeCategory.value !== '__all__' && (p.category || 'other') !== activeCategory.value) {
      return false
    }
    if (!kw) return true
    const haystack = [p.name, p.description, ...(p.tags || [])].join(' ').toLowerCase()
    return haystack.includes(kw)
  })
})

function onSelect(preset) {
  selectedId.value = preset.id
}

function onConfirm() {
  const preset = selectedPreset.value
  if (!preset) return
  // 记录预设使用热度（失败不阻断加载）
  if (preset.id != null) {
    agentApi.pipeline.recordPresetUse(preset.id).catch(() => {})
  }
  emit('selected', preset)
  emit('close')
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      keyword.value = ''
      activeCategory.value = '__all__'
      selectedId.value = null
      loadPresets()
    }
  },
)

// ── 图标与日期工具（与 ToolboxListView 风格一致：克制、无渐变） ──
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

function getInitial(name) {
  return (name || '?').charAt(0).toUpperCase()
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return ''
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${m}-${day}`
}
</script>

<style scoped>
.preset-picker-dialog {
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.preset-picker-dialog :deep(.el-dialog__header) {
  padding-bottom: 8px;
}

.preset-picker-dialog :deep(.el-dialog__body) {
  padding-top: 8px;
  padding-bottom: 12px;
}

.picker-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.picker-title {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
}

.picker-subtitle {
  font-size: 12px;
  color: #6b7280;
}

/* ===== 工具栏 ===== */
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.search-box {
  position: relative;
  flex: 1;
  height: 34px;
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

.search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: #111827;
}

.search-input::placeholder {
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

.category-select {
  width: 150px;
  flex-shrink: 0;
}

/* ===== 卡片区 ===== */
.card-area {
  min-height: 200px;
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #f9fafb;
  padding: 12px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 12px;
}

/* ===== 预设卡片 ===== */
.preset-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px 14px 12px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}

.preset-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 1px 4px rgba(17, 24, 39, 0.06);
  transform: translateY(-1px);
}

.preset-card.selected {
  border-color: #2563eb;
  box-shadow: 0 0 0 1px #2563eb, 0 2px 8px rgba(37, 99, 235, 0.12);
}

.card-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.card-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  flex-shrink: 0;
  user-select: none;
}

.card-main {
  flex: 1;
  min-width: 0;
}

.card-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.card-name {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.selected-check {
  color: #2563eb;
  font-weight: 700;
  font-size: 14px;
  flex-shrink: 0;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
}

.type-summary {
  overflow: hidden;
  text-overflow: ellipsis;
}

.dot-sep {
  color: #d1d5db;
}

.card-desc {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: #4b5563;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.tag-chip {
  font-size: 11px;
  color: #1f2937;
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  padding: 2px 8px;
}

.tag-more {
  font-size: 11px;
  color: #9ca3af;
  padding: 2px 0;
}

.card-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 10px;
  font-size: 11px;
  color: #9ca3af;
  border-top: 1px solid #f3f4f6;
  padding-top: 8px;
}

/* ===== 空状态 ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 0;
  color: #9ca3af;
}

.empty-icon {
  font-size: 24px;
  margin-bottom: 8px;
}

.empty-title {
  font-size: 14px;
  font-weight: 500;
  color: #6b7280;
  margin-bottom: 4px;
}

.empty-desc {
  font-size: 12px;
  color: #9ca3af;
}

/* ===== 选中预览区 ===== */
.preview-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  font-size: 12px;
}

.preview-label {
  color: #2563eb;
  font-weight: 600;
  flex-shrink: 0;
}

.preview-name {
  color: #111827;
  font-weight: 600;
}

.preview-detail {
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
