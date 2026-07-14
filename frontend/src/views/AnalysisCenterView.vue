<template>
  <div class="analysis-center">
    <!-- Main area -->
    <div class="main-area">
      <!-- Topbar -->
      <div class="topbar">
        <div class="breadcrumbs">
          <span class="breadcrumb-item">分析中心</span>
        </div>
      </div>

      <!-- Metrics bar -->
      <div class="metrics-bar">
        <div class="metric-card">
          <div class="metric-value">{{ store.total }}</div>
          <div class="metric-label">事件总数</div>
        </div>
        <div class="metric-card">
          <div class="metric-value metric-danger">{{ highPriorityCount }}</div>
          <div class="metric-label">高优先级</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ hostCount }}</div>
          <div class="metric-label">涉及主机</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">{{ completionRate }}%</div>
          <div class="metric-label">完成率</div>
        </div>
      </div>

      <!-- Content -->
      <!-- Layer 1: 筛选器 -->
      <div class="layer-filter">
        <SmartSearchBar
          :filters="store.filters"
          @update:filters="onFiltersChanged"
          @reset="onReset"
        />
      </div>

      <!-- Layer 3 + 4: 事件表 + 详情面板 -->
      <div class="layer-main">
        <div class="layer-table">
          <EventTable
            :events="store.events"
            :total="store.total"
            :loading="store.loading"
            :pagination="store.pagination"
            :selected-ids="store.selectedEventIds"
            @select-event="onTableSelectEvent"
            @selection-change="onSelectionChange"
            @page-change="onPageChange"
            @sort-change="onSortChange"
            @update-status="onUpdateStatus"
          />
        </div>
        <div class="layer-detail" v-if="store.detailVisible">
          <EventDetailPanel
            :event="store.selectedEvent"
            @close="onCloseDetail"
            @update-status="onUpdateStatus"
            @assign="onAssign"
            @view-related="onViewRelated"
          />
        </div>
      </div>

      <!-- 状态栏 -->
      <div class="layer-footer">
        <span>事件总数: {{ store.total }} | 高优先级: {{ highPriorityCount }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'
import SmartSearchBar from '@/components/analysis/SmartSearchBar.vue'
import EventTable from '@/components/analysis/EventTable.vue'
import EventDetailPanel from '@/components/analysis/EventDetailPanel.vue'

const store = useAnalysisStore()

const highPriorityCount = computed(() => {
  if (!store.events) return 0
  return store.events.filter(e => e.severity === 'critical' || e.severity === 'high').length
})

const hostCount = computed(() => {
  if (!store.events) return 0
  const hosts = new Set(store.events.map(e => e.host_id))
  return hosts.size
})

const completionRate = computed(() => {
  if (!store.total) return 0
  const resolved = store.events ? store.events.filter(e => e.status === 'resolved' || e.status === 'rejected').length : 0
  return Math.round((resolved / store.total) * 100)
})

// 初始加载
onMounted(() => {
  store.fetchEvents()
})

// 筛选条件变更
let debounceTimer = null
function onFiltersChanged(newFilters) {
  store.setFilters(newFilters)
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    store.fetchEvents()
  }, 500)
}

function onReset() {
  store.resetFilters()
  store.fetchEvents()
}

function onTableSelectEvent(event) {
  store.fetchEventDetail(event.id)
}

function onSelectionChange(ids) {
  store.selectedEventIds = ids
}

function onPageChange(page, pageSize) {
  store.pagination.page = page
  store.pagination.pageSize = pageSize
  store.fetchEvents()
}

function onSortChange(field, order) {
  store.sortField = field
  store.sortOrder = order
  store.fetchEvents()
}

function onUpdateStatus({ id, status, comment }) {
  store.updateStatus(id, status, comment)
}

function onAssign({ id, assignee }) {
  store.assign(id, assignee)
}

function onViewRelated(relatedIds) {
  if (relatedIds && relatedIds.length > 0) {
    store.setFilters({ keyword: relatedIds.join(',') })
    store.fetchEvents()
  }
}

function onCloseDetail() {
  store.selectedEvent = null
  store.detailVisible = false
}
</script>

<style scoped>
.analysis-center {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 52px);
  background: var(--color-canvas-subtle);
  overflow: hidden;
}

/* ===== Main Area ===== */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* ===== Topbar ===== */
.topbar {
  flex-shrink: 0;
  padding: 12px 20px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
  position: sticky;
  top: 0;
  z-index: 10;
}

.breadcrumbs {
  display: flex;
  align-items: center;
  gap: 8px;
}

.breadcrumb-item {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle);
}

.breadcrumb-item.active {
  color: var(--color-fg-default);
  font-weight: 500;
}

.breadcrumb-sep {
  font-size: 12px;
  color: var(--color-fg-light);
}

/* ===== Metrics Bar ===== */
.metrics-bar {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-default);
}

.metric-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-card);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.metric-value {
  font-size: 20px;
  font-weight: 500;
  color: var(--color-fg-default);
}

.metric-value.metric-danger {
  color: var(--color-danger-fg);
}

.metric-label {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle);
}

/* ===== Layers ===== */
.layer-filter {
  flex-shrink: 0;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.layer-table {
  flex: 1;
  overflow: auto;
}

.layer-detail {
  width: 340px;
  flex-shrink: 0;
  border-left: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-default);
  overflow-y: auto;
}

.layer-footer {
  flex-shrink: 0;
  height: 32px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle);
  background: var(--color-canvas-default);
  border-top: 0.5px solid var(--color-border-default);
}
</style>
