<template>
  <div class="analysis-center">
    <!-- Main area -->
    <div class="main-area">
      <!-- ===== 折叠吸顶条（滚动后可见） ===== -->
      <div class="compact-bar" v-show="collapsed">
        <div class="cb-inner">
          <span class="cb-title">分析中心</span>
          <span class="cb-sep"></span>
          <span class="cb-stat">共 <strong>{{ store.total }}</strong> 条</span>
          <span class="cb-dot"></span>
          <span class="cb-stat">已匹配 <strong>{{ store.stats.matchedEvents }}</strong></span>
          <span class="cb-dot"></span>
          <span class="cb-stat">案件 {{ store.ruleFilters.caseId ? '#'+store.ruleFilters.caseId : '全部' }}</span>
          <span class="cb-dot"></span>
          <span class="cb-stat">主机 {{ store.ruleFilters.hostId ? '#'+store.ruleFilters.hostId : '全部' }}</span>
          <span class="cb-spacer"></span>
          <button class="cb-expand" @click="collapsed = false" title="展开工具栏">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 9L7 5L11 9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            展开
          </button>
        </div>
      </div>

      <!-- ===== 可折叠头部（初始全部可见） ===== -->
      <div class="collapsible-header" :class="{ 'is-collapsed': collapsed }">
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
            @update:hostId="onHostChange"
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
            :aiCounts="{
              recommended: store.stats.aiRecommended || 0,
              suspicious: store.stats.aiSuspicious || 0,
              false_positive: store.stats.aiFalsePositive || 0,
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
              <span v-if="store.selectedEventIds.length" class="rt-d"></span>
              <span v-if="store.selectedEventIds.length" class="rt-stat">
                已选中 <strong style="color:var(--color-accent-fg,#2563eb)">{{ store.selectedEventIds.length }}</strong> 条
              </span>
            </div>
            <div class="rt-r">
              <el-dropdown
                trigger="click"
                :disabled="store.selectedEventIds.length === 0 || store.aiLoading || store.aiVerdictLoading"
                @command="onAiDropdown"
              >
                <button class="ai-trigger-btn" :class="{ disabled: store.selectedEventIds.length === 0 }">
                  <svg v-if="!store.aiLoading && !store.aiVerdictLoading" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 2l2 7h7l-5.5 4 2 7L12 17l-5.5 4 2-7L3 9h7z"/>
                  </svg>
                  <span v-else class="ai-spinner"></span>
                  {{ store.aiLoading || store.aiVerdictLoading ? '处理中...' : 'AI 操作' }}
                  <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="noise" :disabled="store.aiLoading">
                      降噪研判
                    </el-dropdown-item>
                    <el-dropdown-item command="verdict" :disabled="store.aiVerdictLoading">
                      研判打标
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
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
            @scroll-change="onTableScrollChange"
          />
        </div>
        <div class="layer-detail" v-if="store.detailVisible">
          <EventDetailPanel
            :event="store.selectedEvent"
            :display="store.eventDisplay"
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
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { useAnalysisStore } from '@/stores/analysis'
import CaseHostSelector from '@/components/analysis/CaseHostSelector.vue'
import MetricsBar from '@/components/analysis/MetricsBar.vue'
import ViewFilter from '@/components/analysis/ViewFilter.vue'
import AdvancedFilter from '@/components/analysis/AdvancedFilter.vue'
import RuleNameFilter from '@/components/analysis/RuleNameFilter.vue'
import EventTable from '@/components/analysis/EventTable.vue'
import EventDetailPanel from '@/components/analysis/EventDetailPanel.vue'

const store = useAnalysisStore()

// ===== 表格滚动折叠 =====
const collapsed = ref(false)

function onTableScrollChange(scrolled) {
  collapsed.value = scrolled
}

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

// 主机切换
function onHostChange(hostId) {
  if (hostId !== store.ruleFilters.hostId) {
    store.ruleFilters.hostId = hostId
    store.ruleFilters.page = 1
    store.fetchFilterMeta()
    store.fetchRuleEvents()
    store.fetchStats()
  }
}

// 视图切换
function onViewSwitch(view) {
  store.ruleFilters.viewFilter = view
  store.ruleFilters.page = 1
  store.fetchFilterMeta()
  store.fetchRuleEvents()
  store.fetchStats()
}

// AI 降噪研判
async function onAiNoiseReduce() {
  const caseId = store.ruleFilters.caseId
  if (!caseId) {
    ElMessage.warning('请先选择一个案件')
    return
  }
  try {
    const result = await store.triggerNoiseReduce(caseId)
    ElMessage.success(`AI 研判完成：攻击 ${result.attack || 0} 条，可疑 ${result.suspicious || 0} 条，误报 ${result.false_positive || 0} 条`)
    // 刷新数据
    store.fetchRuleEvents()
    store.fetchStats()
    store.ruleFilters.viewFilter = 'recommended'
  } catch (e) {
    ElMessage.error('AI 降噪研判失败：' + (e.message || '未知错误'))
  }
}

// AI 研判打标（生产者）：对勾选事件批量研判，写回 ai_verdict
async function onAiVerdict() {
  const ids = store.selectedEventIds
  if (!ids || ids.length === 0) {
    ElMessage.warning('请先勾选要研判的事件')
    return
  }
  const result = await store.analyzeEvents(ids)
  if (result) {
    // 研判完成后清空选择
    store.selectedEventIds = []
  }
}

// AI 操作下拉菜单路由
function onAiDropdown(command) {
  if (command === 'noise') onAiNoiseReduce()
  else if (command === 'verdict') onAiVerdict()
}

function onTableSelectEvent(event) {
  store.fetchEventDetail(event.id)
  store.fetchEventDisplay(event.id)
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


/* ===== 折叠吸顶条 ===== */
.compact-bar {
  flex-shrink: 0;
  z-index: 20;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
  padding: 6px 16px;
  min-height: 34px;
  display: flex;
  align-items: center;
}
.cb-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  font-size: 12px;
  color: var(--color-fg-subtle);
}
.cb-title {
  font-weight: 500;
  color: var(--color-fg-default);
  white-space: nowrap;
}
.cb-sep {
  width: 1px;
  height: 14px;
  background: var(--color-border-default);
  flex-shrink: 0;
}
.cb-stat {
  white-space: nowrap;
  font-size: 11px;
}
.cb-stat strong {
  font-weight: 500;
  color: var(--color-fg-default);
}
.cb-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--color-border-default);
  flex-shrink: 0;
}
.cb-spacer {
  flex: 1;
}
.cb-expand {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 8px;
  font-size: 11px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  background: var(--color-canvas-subtle);
  color: var(--color-accent-fg);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}
.cb-expand:hover {
  background: var(--color-accent-subtle);
}

/* ===== 可折叠头部 ===== */
.collapsible-header {
  overflow: hidden;
  transition: max-height 0.35s ease, opacity 0.3s ease, padding 0.3s ease;
  max-height: 500px;
  opacity: 1;
}
.collapsible-header.is-collapsed {
  max-height: 0;
  opacity: 0;
  padding: 0;
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
  padding: 6px 16px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
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
  padding: 6px 16px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-metrics {
  flex-shrink: 0;
  padding: 6px 16px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-controls {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 16px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}

/* AI 操作按钮 — 工具栏右侧幽灵按钮 */
.ai-trigger-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 400;
  border: 0.5px solid var(--color-border-default, #d1d5db);
  border-radius: var(--r-btn, 6px);
  background: var(--color-canvas-default, #fff);
  color: var(--color-fg-default, #111);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.ai-trigger-btn:hover {
  background: var(--color-canvas-subtle, #f3f4f6);
  border-color: var(--color-border-secondary, #9ca3af);
}
.ai-trigger-btn.disabled,
.ai-trigger-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}
.ai-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-border-default, #d1d5db);
  border-top-color: var(--color-fg-default, #111);
  border-radius: 50%;
  animation: ai-spin 0.6s linear infinite;
}
@keyframes ai-spin {
  to { transform: rotate(360deg); }
}

.layer-rule-filter {
  flex-shrink: 0;
  padding: 4px 16px;
  background: var(--color-canvas-subtle);
  border-bottom: 0.5px solid var(--color-border-default);
}

.layer-main {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.layer-table {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
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
  padding: 4px 12px;
  border-bottom: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-subtle);
}

.rt-l {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rt-r {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
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
