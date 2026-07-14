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
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="2" y="2" width="10" height="10" rx="2" stroke="currentColor" stroke-width="1.2"/>
              <path d="M2 5h10" stroke="currentColor" stroke-width="1.2"/>
            </svg>
            {{ (currentCase?.hosts || []).length }} 主机
          </span>
          <span class="stat-item">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
              <circle cx="7" cy="7" r="3" stroke="currentColor" stroke-width="1.2"/>
            </svg>
            {{ currentCase?.event_count || 0 }} 事件
          </span>
          <span class="stat-item">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 4h10M2 7h10M2 10h10" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
            </svg>
            {{ currentCase?.log_count || 0 }} 日志
          </span>
        </div>
      </div>
      <button class="btn btn-outline btn-sm" @click="showCaseSelector = true">
        切换案件
      </button>
    </div>

    <!-- 主机网格 -->
    <div class="host-grid">
      <div
        v-for="host in hosts"
        :key="host.id"
        :class="['host-cell', { selected: selectedHostId === host.id }]"
        @click="selectHost(host)"
      >
        <!-- 严重度色条顶部 -->
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
    <div v-if="showCaseSelector" class="modal-overlay" @click.self="showCaseSelector = false">
      <div class="modal">
        <div class="modal-header">
          <span class="modal-title">选择案件</span>
          <button class="modal-close" @click="showCaseSelector = false">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </button>
        </div>
        <div class="modal-body">
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
                <span class="stat-sep">|</span>
                <span>{{ c.log_count || 0 }} 日志</span>
                <span class="stat-sep">|</span>
                <span>{{ c.event_count || 0 }} 事件</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

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
  const map = { critical: '#dc2626', high: '#dc2626', medium: '#d97706', low: '#2563eb', info: '#a3a3a3' }
  return map[severity] || '#a3a3a3'
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
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  overflow: hidden;
}

/* ===== 案件条带 ===== */
.case-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: var(--color-canvas-subtle, #fafafa);
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}

.case-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.case-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.case-id-label {
  font-weight: 500;
  font-size: 14px;
  color: var(--color-fg-default, #111111);
}

.case-desc {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
}

.case-stats {
  display: flex;
  gap: 16px;
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-muted, #555555);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stat-item svg {
  color: var(--color-fg-subtle, #888888);
}

/* ===== Buttons ===== */
.btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.4;
}

.btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
}

.btn-outline {
  background: transparent;
  border-color: var(--color-border-default, #e5e5e5);
}

.btn-sm {
  padding: 4px 8px;
  font-size: 11px;
}

/* ===== 主机网格 ===== */
.host-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 16px 20px;
}

.host-cell {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.15s;
  background: var(--color-canvas-default, #ffffff);
}

.host-cell:hover {
  border-color: var(--color-accent-fg, #2563eb);
}

.host-cell.selected {
  border-color: var(--color-accent-fg, #2563eb);
  border-width: 1px;
  background: var(--color-accent-subtle, #eff6ff);
}

.severity-bar {
  height: 2px;
  flex-shrink: 0;
}

.host-content {
  flex: 1;
  padding: 10px 12px;
  position: relative;
}

.host-name {
  font-weight: 500;
  font-size: 13px;
  color: var(--color-fg-default, #111111);
  margin-bottom: 2px;
}

.host-ip {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  font-family: monospace;
}

.host-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
}

.selected-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  background: var(--color-accent-fg, #2563eb);
  color: #fff;
  font-size: 10px;
  font-weight: 400;
  padding: 1px 6px;
  border-radius: 4px;
}

.host-empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 24px;
  color: var(--color-fg-subtle, #888888);
  font-size: 13px;
  font-weight: 400;
}

/* ===== Modal ===== */
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
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-container, 12px);
  width: 500px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}

.modal-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}

.modal-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle, #888888);
  cursor: pointer;
  border-radius: var(--r-btn, 6px);
  transition: all 0.15s;
}

.modal-close:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-default, #111111);
}

.modal-body {
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
}

/* ===== Case List ===== */
.case-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.case-item {
  padding: 12px 16px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  cursor: pointer;
  transition: all 0.1s;
}

.case-item:hover {
  background: var(--color-canvas-subtle, #fafafa);
}

.case-item.active {
  border-color: var(--color-accent-fg, #2563eb);
  background: var(--color-accent-subtle, #eff6ff);
}

.case-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.case-item-id {
  font-weight: 500;
  font-size: 13px;
  color: var(--color-fg-default, #111111);
}

.case-item-desc {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-accent-fg, #2563eb);
  background: var(--color-accent-subtle, #eff6ff);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.case-item-stats {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  display: flex;
  gap: 8px;
}

.stat-sep {
  color: var(--color-border-default, #e5e5e5);
}
</style>
