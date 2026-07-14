<template>
  <div class="analysis-center">
    <!-- Layer 1: 智能筛选器 -->
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
      <span>事件总数: {{ store.total }}</span>
    </div>
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'
import SmartSearchBar from '@/components/analysis/SmartSearchBar.vue'
import AttackChainTimeline from '@/components/analysis/AttackChainTimeline.vue'
import EventTable from '@/components/analysis/EventTable.vue'
import EventDetailPanel from '@/components/analysis/EventDetailPanel.vue'

const store = useAnalysisStore()

// 初始加载
onMounted(() => {
  store.fetchEvents()
  store.fetchTimeline()
})

// 筛选条件变更 → 自动刷新
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

// 时间轴选中事件
function onTimelineSelectEvent(eventId) {
  store.fetchEventDetail(eventId)
}

// 事件表选中
function onTableSelectEvent(event) {
  store.fetchEventDetail(event.id)
}

// 多选变更
function onSelectionChange(ids) {
  store.selectedEventIds = ids
}

// 分页变更
function onPageChange(page, pageSize) {
  store.pagination.page = page
  store.pagination.pageSize = pageSize
  store.fetchEvents()
}

// 排序变更
function onSortChange(field, order) {
  store.sortField = field
  store.sortOrder = order
  store.fetchEvents()
}

// 状态变更
function onUpdateStatus({ id, status, comment }) {
  store.updateStatus(id, status, comment)
}

// 指派
function onAssign({ id, assignee }) {
  store.assign(id, assignee)
}

// 查看关联事件
function onViewRelated(relatedIds) {
  // 在筛选条件中设置以关联事件 ID 为关键字
  if (relatedIds && relatedIds.length > 0) {
    store.setFilters({ keyword: relatedIds.join(',') })
    store.fetchEvents()
    store.fetchTimeline()
  }
}

// 关闭详情
function onCloseDetail() {
  store.selectedEvent = null
  store.detailVisible = false
}
</script>

<style scoped>
.analysis-center {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);
  background: var(--color-canvas-subtle, #f5f5f5);
}

.layer-filter {
  flex-shrink: 0;
  background: var(--color-canvas-default, #fff);
  border-bottom: 1px solid var(--color-border-default, #e5e7eb);
}

.layer-timeline {
  flex-shrink: 0;
  height: 140px;
  background: var(--color-canvas-default, #fff);
  border-bottom: 1px solid var(--color-border-default, #e5e7eb);
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
  border-left: 1px solid var(--color-border-default, #e5e7eb);
  background: var(--color-canvas-default, #fff);
  overflow-y: auto;
}

.layer-footer {
  flex-shrink: 0;
  height: 32px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  font-size: 12px;
  color: var(--color-fg-muted, #6b7280);
  background: var(--color-canvas-default, #fff);
  border-top: 1px solid var(--color-border-default, #e5e7eb);
}
</style>
