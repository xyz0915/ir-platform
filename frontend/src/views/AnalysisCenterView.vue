<template>
  <div class="analysis-center">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <span class="sidebar-title">分析中心</span>
      </div>
      <nav class="sidebar-nav">
        <div
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-item', { active: activeNav === item.key }]"
          @click="activeNav = item.key"
        >
          <span class="nav-dot" />
          <span class="nav-label">{{ item.label }}</span>
        </div>
      </nav>
    </aside>

    <!-- Main area -->
    <div class="main-area">
      <!-- Topbar -->
      <div class="topbar">
        <div class="breadcrumbs">
          <span class="breadcrumb-item">分析中心</span>
          <span class="breadcrumb-sep">/</span>
          <span class="breadcrumb-item active">事件调查</span>
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

      <!-- Layer 2: 攻击链时间轴 -->
      <div class="layer-timeline">
        <AttackChainTimeline
          :chains="store.timelineData"
          :events="store.timelineEvents"
          @select-event="onTimelineSelectEvent"
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
import { ref, computed, onMounted } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'
import SmartSearchBar from '@/components/analysis/SmartSearchBar.vue'
import AttackChainTimeline from '@/components/analysis/AttackChainTimeline.vue'
import EventTable from '@/components/analysis/EventTable.vue'
import EventDetailPanel from '@/components/analysis/EventDetailPanel.vue'

const store = useAnalysisStore()
const activeNav = ref('events')

const navItems = [
  { key: 'events', label: '事件调查' },
  { key: 'timeline', label: '攻击链' },
  { key: 'iocs', label: 'IOC 分析' },
  { key: 'reports', label: '报告' },
]

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
  store.fetchTimeline()
})

// 筛选条件变更
let debounceTimer = null
function onFiltersChanged(newFilters) {
  store.setFilters(newFilters)
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    store.fetchEvents()
    store.fetchTimeline()
  }, 500)
}

function onReset() {
  store.resetFilters()
  store.fetchEvents()
  store.fetchTimeline()
}

function onTimelineSelectEvent(eventId) {
  store.fetchEventDetail(eventId)
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
    store.fetchTimeline()
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
  height: calc(100vh - 52px);
  background: var(--color-canvas-subtle);
}

/* ===== Sidebar ===== */
.sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--color-canvas-default);
  border-right: 0.5px solid var(--color-border-default);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 20px 16px;
  border-bottom: 0.5px solid var(--color-border-default);
}

.sidebar-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--color-fg-default);
}

.sidebar-nav {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--r-btn);
  cursor: pointer;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-muted);
  transition: all 0.15s;
  border-left: 3px solid transparent;
}

.nav-item:hover {
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
}

.nav-item.active {
  color: var(--color-accent-fg);
  font-weight: 500;
  background: var(--color-accent-subtle);
  border-left-color: var(--color-accent-fg);
}

.nav-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-border-default);
  flex-shrink: 0;
}

.nav-item.active .nav-dot {
  background: var(--color-accent-fg);
}

.nav-label {
  font-size: 13px;
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

.layer-timeline {
  flex-shrink: 0;
  height: 140px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
  overflow: hidden;
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
