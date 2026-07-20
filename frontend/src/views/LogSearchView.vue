<template>
  <div class="log-search-page">
    <!-- ═══ Page Header ═══ -->
    <div class="pg-hdr">
      <div class="pg-hdr-l">
        <div class="pg-hdr-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          日志检索
        </div>
        <div class="pg-hdr-sub">
          {{ currentCaseName }} · {{ currentHostName }}
          <span v-if="store.total > 0" style="color:var(--color-fg-subtle)">共 {{ store.total }} 条</span>
        </div>
      </div>
      <div class="pg-hdr-actions">
        <button class="btn btn-default btn-sm" @click="exportResults('json')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          导出 JSON
        </button>
        <button class="btn btn-default btn-sm" @click="exportResults('csv')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          导出 CSV
        </button>
        <button class="btn btn-default btn-sm" @click="showSaveDialog = true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
          保存搜索条件
        </button>
      </div>
    </div>

    <!-- ═══ Case Strip (Layer 0) ═══ -->
    <CaseHostSelector
      v-model="store.selectedHostId"
      :cases="store.casesWithHosts"
      @select-host="onSelectHost"
      @switch-case="onSwitchCase"
    />

    <!-- ═══ NL 检索面板（T-C2）═══ -->
    <NlSearchPanel />

    <!-- ═══ Search Bar (Layer 1) ═══ -->
    <LogSearchBar
      v-model="store.keyword"
      :total="store.total"
      :elapsed-ms="store.elapsedMs"
      :trend-data="store.trendData"
      :current-case-name="currentCaseName"
      :current-host-name="currentHostName"
      @search="onSearch"
      @quick-filter="onQuickFilter"
    />

    <!-- ═══ Result Area (Layer 2) ═══ -->
    <LogResultList
      :items="store.items"
      :total="store.total"
      :page="store.page"
      :page-size="store.pageSize"
      :loading="store.loading"
      @view-detail="showDetail"
      @generate-event="onGenerateEvent"
      @update:page="store.page = $event; fetchData()"
      @update:pageSize="store.pageSize = $event; fetchData()"
    />

    <!-- ═══ Detail Panel ═══ -->
    <LogDetailPanel
      v-model="showDetailPanel"
      :record="detailRecord"
    />

    <!-- ═══ Save Search Modal ═══ -->
    <div v-if="showSaveDialog" class="modal-overlay" @click.self="showSaveDialog = false">
      <div class="modal" style="max-width: 420px;">
        <div class="modal-header">
          <div class="modal-title">保存搜索条件</div>
          <button class="modal-close" @click="showSaveDialog = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="fg">
            <label class="fl">名称</label>
            <input class="fi" v-model="saveForm.name" placeholder="输入搜索条件名称" />
          </div>
          <div class="fg">
            <label class="fl">搜索条件</label>
            <textarea class="fi" v-model="saveForm.query" rows="3" disabled placeholder="当前搜索关键字"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showSaveDialog = false">取消</button>
          <button class="btn btn-primary" @click="saveSearchCondition">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useLogSearchStore } from '@/stores/logSearch'
import { exportSearch } from '@/api/logs'
import CaseHostSelector from '@/components/logs/CaseHostSelector.vue'
import LogSearchBar from '@/components/logs/LogSearchBar.vue'
import LogResultList from '@/components/logs/LogResultList.vue'
import LogDetailPanel from '@/components/logs/LogDetailPanel.vue'
import NlSearchPanel from '@/components/logs/NlSearchPanel.vue'

const route = useRoute()
const store = useLogSearchStore()

// 详情弹窗
const showDetailPanel = ref(false)
const detailRecord = ref(null)

// 保存搜索条件
const showSaveDialog = ref(false)
const saveForm = ref({ name: '', query: '' })

// 当前选中的案件名/主机名
const currentCaseName = computed(() => {
  const c = store.casesWithHosts.find(c => c.id === store.selectedCaseId)
  return c?.name || c?.case_id || ''
})

const currentHostName = computed(() => {
  for (const c of store.casesWithHosts) {
    const h = (c.hosts || []).find(h => h.id === store.selectedHostId)
    if (h) return h.hostname || ''
  }
  return ''
})

// 初始化
onMounted(async () => {
  // 从 URL 参数初始化
  const caseId = route.query.case_id ? Number(route.query.case_id) : null
  const hostId = route.query.host_id ? Number(route.query.host_id) : null
  const importId = route.query.import_id ? Number(route.query.import_id) : null

  await store.loadCasesWithHosts()

  if (caseId) store.selectedCaseId = caseId
  if (hostId) store.selectedHostId = hostId

  // 默认选中第一个有主机的案件
  if (!store.selectedCaseId && store.casesWithHosts.length > 0) {
    store.selectedCaseId = store.casesWithHosts[0].id
  }

  // 默认选中第一个主机
  if (!store.selectedHostId) {
    const caseData = store.casesWithHosts.find(c => c.id === store.selectedCaseId)
    if (caseData?.hosts?.length > 0) {
      store.selectedHostId = caseData.hosts[0].id
    }
  }

  // 加载趋势数据
  await store.loadTrendData()
  // 自动搜索
  await fetchData()
})

// 监听路由参数变化
watch(() => route.query, (q) => {
  if (q.import_id) {
    // 定位到特定导入记录，打开详情
    const importId = Number(q.import_id)
    const item = store.items.find(i => i.id === importId)
    if (item) {
      showDetailPanel.value = true
      detailRecord.value = item
    }
  }
})

async function fetchData() {
  await store.search()
}

function onSelectHost({ host, caseId }) {
  store.selectedHostId = host.id
  store.selectedCaseId = caseId
  store.page = 1
  fetchData()
}

function onSwitchCase(c) {
  store.selectedCaseId = c.id
  store.selectedHostId = null
  store.page = 1
}

function onSearch(keyword) {
  store.keyword = keyword
  store.page = 1
  fetchData()
}

function onQuickFilter(tag) {
  store.keyword = tag.query || ''
  store.page = 1
  fetchData()
}

function showDetail(item) {
  detailRecord.value = item
  showDetailPanel.value = true
}

async function onGenerateEvent(item) {
  try {
    const { data } = await import('@/api/logs').then(m => m.toEvent(item.id))
    ElMessage.success(`事件已生成: ${data.event_id}`)
    // 刷新当前记录状态
    await fetchData()
    // 跳转分析中心
    window.open(`/analysis-center?event_id=${data.event_id}`, '_blank')
  } catch (err) {
    ElMessage.error('事件生成失败: ' + (err.message || '未知错误'))
  }
}

async function exportResults(format) {
  try {
    const blob = await exportSearch({
      keyword: store.keyword,
      case_id: store.selectedCaseId,
      host_id: store.selectedHostId,
      format,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `log_export_${Date.now()}.${format}`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (err) {
    ElMessage.error('导出失败')
  }
}

function saveSearchCondition() {
  const saved = JSON.parse(localStorage.getItem('ir_saved_searches') || '[]')
  saved.push({
    name: saveForm.value.name,
    query: store.keyword,
    caseId: store.selectedCaseId,
    hostId: store.selectedHostId,
    savedAt: new Date().toISOString(),
  })
  localStorage.setItem('ir_saved_searches', JSON.stringify(saved))
  showSaveDialog.value = false
  saveForm.value = { name: '', query: '' }
  ElMessage.success('搜索条件已保存')
}
</script>

<style scoped>
/* ═══════ IR Design System — Log Search View ═══════ */
.log-search-page {
  max-width: 1540px;
  margin: 0 auto;
  padding: 20px 24px 40px;
}

/* ── Page Header ── */
.pg-hdr {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 16px;
}
.pg-hdr-l {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pg-hdr-title {
  font-size: 20px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-fg-default);
}
.pg-hdr-title svg {
  width: 18px;
  height: 18px;
  color: var(--color-fg-muted);
}
.pg-hdr-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle);
  display: flex;
  align-items: center;
  gap: 6px;
}
.pg-hdr-actions {
  display: flex;
  gap: 6px;
}

/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  border-radius: var(--r-btn, 6px);
  cursor: pointer;
  border: 0.5px solid transparent;
  transition: all 0.12s;
  white-space: nowrap;
  font-family: inherit;
  line-height: 1;
}
.btn-default {
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  border-color: var(--color-border-default);
}
.btn-default:hover {
  background: var(--color-canvas-inset);
  border-color: var(--color-fg-light);
}
.btn-primary {
  background: var(--color-accent-fg);
  color: white;
  border-color: var(--color-accent-fg);
}
.btn-primary:hover {
  background: #1d4ed8;
}
.btn-ghost {
  background: transparent;
  color: var(--color-fg-muted);
  border-color: transparent;
}
.btn-ghost:hover {
  background: var(--color-canvas-inset);
}
.btn-sm {
  height: 26px;
  padding: 0 10px;
  font-size: 11px;
}
.btn svg {
  width: 12px;
  height: 12px;
}
.btn:disabled {
  opacity: 0.4;
  pointer-events: none;
}

/* ── Modal ── */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-container, 12px);
  width: 100%;
  max-width: 520px;
}
.modal-header {
  padding: 20px 24px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--color-fg-default);
}
.modal-close {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-fg-muted);
}
.modal-close:hover {
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
}
.modal-close svg {
  width: 14px;
  height: 14px;
}
.modal-body {
  padding: 16px 24px 20px;
}
.modal-footer {
  padding: 12px 24px;
  border-top: 0.5px solid var(--color-border-default);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* ── Form Group ── */
.fg {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.fg:last-child {
  margin-bottom: 0;
}
.fl {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-muted);
}
.fi {
  height: 32px;
  padding: 0 12px;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default);
  font-size: 13px;
  font-weight: 400;
  outline: none;
  transition: border-color 0.12s;
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  font-family: inherit;
}
.fi:focus {
  border-color: var(--color-accent-fg);
}
.fi::placeholder {
  color: var(--color-fg-light);
}
textarea.fi {
  height: auto;
  padding: 8px 12px;
  resize: vertical;
  line-height: 1.6;
}
.fi:disabled {
  background: var(--color-canvas-subtle);
  color: var(--color-fg-muted);
  cursor: not-allowed;
}

/* ── Responsive ── */
@media (max-width: 760px) {
  .log-search-page {
    padding: 12px;
  }
  .pg-hdr {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .pg-hdr-actions {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
