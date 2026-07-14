<template>
  <div class="case-host-selector">
    <!-- 案件条带 -->
    <div class="case-strip">
      <div class="case-info">
        <div class="case-header">
          <span class="case-id-label">{{ currentCase?.name || currentCase?.label || '选择案件' }}</span>
          <span v-if="currentCase?.case_number" class="case-desc">{{ currentCase.case_number }}</span>
        </div>
        <div class="case-stats">
          <span class="stat-item">
            <el-icon :size="14"><Monitor /></el-icon>
            {{ (currentCase?.hosts || []).length }} 主机
          </span>
          <span class="stat-item">
            <el-icon :size="14"><WarningFilled /></el-icon>
            {{ currentCase?.event_count || 0 }} 事件
          </span>
          <span class="stat-item">
            <el-icon :size="14"><Document /></el-icon>
            {{ currentCase?.log_count || 0 }} 日志
          </span>
        </div>
      </div>
      <el-button size="small" @click="showCaseSelector = true">
        切换案件
      </el-button>
    </div>

    <!-- 主机网格 -->
    <div class="host-grid">
      <div
        v-for="host in hosts"
        :key="host.id"
        :class="['host-cell', { selected: selectedHostId === host.id }]"
        @click="selectHost(host)"
      >
        <!-- 严重度色条 -->
        <div class="severity-bar" :style="{ backgroundColor: severityColor(host.severity) }" />
        <div class="host-content">
          <div class="host-name">{{ host.hostname }}</div>
          <div class="host-ip">{{ host.ip || host.ip_address }}</div>
          <div class="host-meta">
            <span class="host-os">{{ host.os || host.os_type || '—' }}</span>
            <span class="host-log-count">{{ host.log_count || 0 }} 日志</span>
          </div>
          <div v-if="selectedHostId === host.id" class="selected-badge">选中</div>
        </div>
      </div>
      <div v-if="hosts.length === 0" class="host-empty">
        该案件下暂无主机
      </div>
    </div>

    <!-- 案件选择弹窗 -->
    <el-dialog v-model="showCaseSelector" title="选择案件" width="500px">
      <div class="case-list">
        <div
          v-for="c in cases"
          :key="c.id"
          :class="['case-item', { active: currentCaseId === c.id }]"
          @click="switchCase(c)"
        >
          <div class="case-item-header">
            <span class="case-item-id">{{ c.name || c.label || ('案件 #' + c.value) }}</span>
            <span v-if="c.case_number" class="case-item-desc">{{ c.case_number }}</span>
          </div>
          <div class="case-item-stats">
            <span>{{ (c.hosts || []).length }} 主机</span>
            <span>|</span>
            <span>{{ c.log_count || 0 }} 日志</span>
            <span>|</span>
            <span>{{ c.event_count || 0 }} 事件</span>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Monitor, WarningFilled, Document } from '@element-plus/icons-vue'

const props = defineProps({
  cases: { type: Array, default: () => [] },
  modelValue: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue', 'select-host', 'switch-case'])

const showCaseSelector = ref(false)
const currentCaseId = ref(props.modelValue)

// 当前选中的案件
const currentCase = computed(() => {
  if (!currentCaseId.value) return props.cases[0] || null
  return props.cases.find(c => c.id === currentCaseId.value) || props.cases[0] || null
})

// 当前案件下的主机列表
const hosts = computed(() => currentCase.value?.hosts || [])

// 选中的主机 ID
const selectedHostId = computed(() => props.modelValue)

function severityColor(severity) {
  const map = { critical: '#DC2626', high: '#EF4444', medium: '#EAB308', low: '#3B82F6', info: '#9CA3AF' }
  return map[severity] || '#9CA3AF'
}

function selectHost(host) {
  emit('update:modelValue', host.id)
  emit('select-host', { host, caseId: currentCase.value?.id })
}

function switchCase(c) {
  currentCaseId.value = c.id
  showCaseSelector.value = false
  emit('switch-case', c)
  // 默认选中第一个主机
  if (c.hosts && c.hosts.length > 0) {
    selectHost(c.hosts[0])
  }
}
</script>

<style scoped>
.case-host-selector {
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  overflow: hidden;
}

/* 案件条带 */
.case-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--color-canvas-subtle);
  border-bottom: 1px solid var(--color-border-default);
}

.case-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.case-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.case-id-label {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-fg-default);
}

.case-desc {
  font-size: 12px;
  color: var(--color-fg-muted);
}

.case-stats {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--color-fg-muted);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 3px;
}

/* 主机网格 */
.host-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 12px 16px;
}

.host-cell {
  position: relative;
  display: flex;
  border: 1px solid var(--color-border-default);
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  transition: box-shadow 0.15s, border-color 0.15s;
}

.host-cell:hover {
  border-color: var(--color-accent-fg);
  box-shadow: 0 0 0 1px var(--color-accent-subtle);
}

.host-cell.selected {
  border-color: var(--color-accent-fg);
  background: var(--color-accent-subtle);
}

.severity-bar {
  width: 3px;
  flex-shrink: 0;
}

.host-content {
  flex: 1;
  padding: 8px 10px;
  position: relative;
}

.host-name {
  font-weight: 600;
  font-size: 12px;
  color: var(--color-fg-default);
  margin-bottom: 2px;
}

.host-ip {
  font-size: 11px;
  color: var(--color-fg-muted);
  font-family: monospace;
}

.host-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 10px;
  color: var(--color-fg-muted);
}

.selected-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  background: var(--color-accent-fg);
  color: #fff;
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 600;
}

.host-empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 20px;
  color: var(--color-fg-muted);
  font-size: 12px;
}

/* 案件选择弹窗 */
.case-list {
  max-height: 400px;
  overflow-y: auto;
}

.case-item {
  padding: 10px 14px;
  border: 1px solid var(--color-border-default);
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: background 0.1s;
}

.case-item:hover {
  background: var(--color-canvas-subtle);
}

.case-item.active {
  border-color: var(--color-accent-fg);
  background: var(--color-accent-subtle);
}

.case-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.case-item-id {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-fg-default);
}

.case-item-desc {
  font-size: 11px;
  color: var(--color-accent-fg);
  background: var(--color-canvas-subtle);
  padding: 1px 6px;
  border-radius: 3px;
  font-family: monospace;
}

.case-item-stats {
  font-size: 11px;
  color: var(--color-fg-muted);
  display: flex;
  gap: 6px;
}
</style>
