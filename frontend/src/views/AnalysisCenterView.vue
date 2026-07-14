<template>
  <div class="analysis-center">
    <!-- Main area -->
    <div class="main-area">
      <!-- Topbar -->
      <div class="topbar">
        <div class="breadcrumbs">
          <span class="breadcrumb-item">分析中心</span>
          <span class="breadcrumb-sep">/</span>
          <span class="breadcrumb-item active">规则匹配降噪</span>
        </div>
      </div>

      <!-- 案件 / 主机级联选择 -->
      <div class="layer-chs">
        <CaseHostSelector
          :cases="store.filterMeta.cases"
          :hosts="store.filterMeta.hosts"
          :selectedCaseId="store.ruleFilters.caseId"
          :selectedHostId="store.ruleFilters.hostId"
          @update:caseId="onCaseChange"
          @update:hostId="store.setFilter('hostId', $event)"
        />
      </div>

      <!-- 统计卡片 -->
      <div class="layer-metrics">
        <MetricsBar :stats="store.stats" />
      </div>

      <!-- 视图切换 + 高级筛选 -->
      <div class="layer-controls">
        <ViewFilter
          :active="store.ruleFilters.viewFilter"
          :counts="{
            all: store.stats.totalEvents,
            matched: store.stats.matchedEvents,
            unmatched: store.stats.unmatchedEvents,
          }"
          @switch="onViewSwitch"
        />
        <AdvancedFilter
          :filters="store.ruleFilters"
          :meta="store.filterMeta"
          @update="store.setFilter"
          @reset="store.resetRuleFilters"
        />
      </div>

      <!-- 规则名称筛选 (仅已匹配模式) -->
      <div class="layer-rule-filter" v-if="store.ruleFilters.viewFilter === 'matched'">
        <RuleNameFilter
          :rules="store.filterMeta.hitRules"
          :selected="store.ruleFilters.ruleId"
          @select="store.setFilter('ruleId', $event)"
        />
      </div>

      <!-- Content: 事件表格 + 详情 -->
      <div class="layer-main">
        <div class="layer-table">
          <!-- 结果工具栏 -->
          <div class="rt">
            <div class="rt-l">
              <span class="rt-stat">共 <strong>{{ store.total }}</strong> 条</span>
              <span class="rt-d"></span>
              <span class="rt-stat">耗时 <strong>{{ store.elapsedMs }}</strong>ms</span>
              <span class="rt-d"></span>
              <span class="rt-stat">案件 <strong>{{ currentCaseName }}</strong></span>
              <span class="rt-d"></span>
              <span class="rt-stat">主机 <strong>{{ currentHostName }}</strong></span>
            </div>
          </div>
          <EventTable
            :events="store.items"
            :total="store.total"
            :loading="store.loading"
            :pagination="{ page: store.ruleFilters.page, pageSize: store.ruleFilters.pageSize }"
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
        <span>事件总数: {{ store.total }} | 已匹配: {{ store.stats.matchedEvents }} | 未匹配: {{ store.stats.unmatchedEvents }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useAnalysisStore } from '@/stores/analysis'
import CaseHostSelector from '@/components/analysis/CaseHostSelector.vue'
import MetricsBar from '@/components/analysis/MetricsBar.vue'
import ViewFilter from '@/components/analysis/ViewFilter.vue'
import AdvancedFilter from '@/components/analysis/AdvancedFilter.vue'
import RuleNameFilter from '@/components/analysis/RuleNameFilter.vue'
import EventTable from '@/components/analysis/EventTable.vue'
import EventDetailPanel from '@/components/analysis/EventDetailPanel.vue'

const store = useAnalysisStore()

const currentCaseName = computed(() => {
  if (!store.ruleFilters.caseId) return '全部'
  const c = store.filterMeta.cases.find(c => c.id === store.ruleFilters.caseId)
  return c ? (c.name || ('#' + c.id)) : '全部'
})

const currentHostName = computed(() => {
  if (!store.ruleFilters.hostId) return '全部'
  const h = store.filterMeta.hosts.find(h => h.id === store.ruleFilters.hostId)
  return h ? (h.hostname || ('#' + h.id)) : '全部'
})

// 初始加载
onMounted(async () => {
  await Promise.all([
    store.fetchFilterMeta(),
    store.fetchStats(),
    store.fetchRuleEvents(),
  ])
})

// 案件切换（级联）
function onCaseChange(caseId) {
  if (caseId !== store.ruleFilters.caseId) {
    store.ruleFilters.caseId = caseId
    store.ruleFilters.hostId = null
    store.ruleFilters.page = 1
    // 刷新筛选元数据（主机列表按案件过滤）
    store.fetchFilterMeta()
    store.fetchRuleEvents()
    store.fetchStats()
  }
}

// 视图切换
function onViewSwitch(view) {
  store.ruleFilters.viewFilter = view
  store.ruleFilters.page = 1
  store.fetchRuleEvents()
  store.fetchStats()
}

function onTableSelectEvent(event) {
  store.fetchEventDetail(event.id)
}

function onSelectionChange(ids) {
  store.selectedEventIds = ids
}

function onPageChange(page, pageSize) {
  store.ruleFilters.page = page
  store.ruleFilters.pageSize = pageSize
  store.fetchRuleEvents()
}

function onSortChange(field, order) {
  store.sortField = field
  store.sortOrder = order
  store.fetchRuleEvents()
}

function onUpdateStatus({ id, status, comment }) {
  store.updateStatus(id, status, comment)
}

function onAssign({ id, assignee }) {
  store.assign(id, assignee)
}

function onViewRelated(relatedIds) {
  if (relatedIds && relatedIds.length > 0) {
    store.ruleFilters.keyword = relatedIds.join(',')
    store.ruleFilters.page = 1
    store.fetchRuleEvents()
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

.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* Topbar */
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

/* Layers */
.layer-chs {
  flex-shrink: 0;
  padding: 12px 20px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-metrics {
  flex-shrink: 0;
  padding: 12px 20px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-controls {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 20px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-rule-filter {
  flex-shrink: 0;
  padding: 8px 20px;
  background: var(--color-canvas-subtle);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.layer-table {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-canvas-default);
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

/* 结果工具栏 */
.rt {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-subtle);
}

.rt-l {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rt-stat {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle);
}

.rt-stat strong {
  font-weight: 500;
  color: var(--color-fg-default);
}

.rt-d {
  width: 1px;
  height: 10px;
  background: var(--color-border-default);
}
</style>
