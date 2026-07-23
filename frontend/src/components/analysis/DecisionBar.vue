<template>
  <div class="decision-bar">
    <div class="db-left-group">
      <!-- 严重度徽章 -->
      <span class="severity-badge" :class="'badge-' + (event.severity || 'info')">{{ event.severity }}</span>

      <!-- 风险评分 -->
      <span class="db-risk-score" :style="{ color: riskScoreColor }">{{ riskScore }}</span>

      <!-- 类别标签 -->
      <span v-if="categoryLabel" class="db-cat-tag">{{ categoryLabel }}</span>

      <!-- ATT&CK 阶段标签 -->
      <span v-if="event.attack_stage" class="db-stage-tag">{{ stageLabel(event.attack_stage) }}</span>

      <!-- 状态标签 -->
      <span class="db-status-tag" :class="'st-' + (event.status || 'pending')">{{ statusLabel(event.status) }}</span>
    </div>

    <div class="db-right-group">
      <!-- 状态流转按钮 -->
      <button v-if="event.status === 'pending'" class="btn btn-xs btn-primary" @click="onStatusChange('triaging')">分诊</button>
      <button v-if="event.status === 'triaging'" class="btn btn-xs btn-warning" @click="onStatusChange('investigating')">调查</button>
      <button v-if="event.status === 'investigating'" class="btn btn-xs btn-success" @click="onStatusChange('resolved')">解决</button>
      <button v-if="event.status === 'resolved'" class="btn btn-xs btn-warning" @click="onStatusChange('investigating')">重开</button>
      <button v-if="event.status !== 'rejected' && event.status !== 'resolved'" class="btn btn-xs btn-danger" @click="onStatusChange('rejected')">误报</button>

      <!-- 深度调查按钮 -->
      <button class="btn btn-xs btn-primary" @click="$emit('deep-investigation')">
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="margin-right:2px">
          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.3"/>
          <path d="M8 5V11M5 8H11" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
        </svg>
        深度调查
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  event: { type: Object, default: () => ({}) },
  riskScore: { type: Number, default: 0 },
})

const emit = defineEmits(['update-status', 'deep-investigation'])

const CATEGORY_LABELS = {
  process: '进程', network: '网络', persistence: '持久化', startup: '启动项',
  behavior: '行为', ioc: '情报', credential: '凭据', discovery: '发现',
  execution: '执行', lateral: '横向', c2: 'C2', impact: '影响',
  defense_evasion: '防御规避', privilege_escalation: '提权', exfiltration: '数据外泄',
  webshell: 'WebShell', memory_shell: '内存马', attack_chain: '攻击链',
}

const STAGE_LABELS = {
  initial_access: '初始访问', execution: '执行', persistence: '持久化',
  privilege_escalation: '提权', defense_evasion: '防御规避',
  credential_access: '凭据访问', discovery: '发现',
  lateral_movement: '横向移动', collection: '收集',
  command_and_control: 'C2', exfiltration: '外泄',
  impact: '影响', unknown: '未知',
}

const STATUS_LABELS = {
  pending: '待处理', triaging: '分诊中', investigating: '调查中',
  resolved: '已解决', rejected: '已误报',
}

const categoryLabel = computed(() => {
  return CATEGORY_LABELS[props.event?.category] || props.event?.category || ''
})

function stageLabel(s) {
  return STAGE_LABELS[s] || s
}

function statusLabel(s) {
  return STATUS_LABELS[s] || s
}

const riskScoreColor = computed(() => {
  const s = props.riskScore
  if (s >= 70) return '#dc2626'
  if (s >= 50) return '#d97706'
  if (s >= 30) return '#2563eb'
  return '#a3a3a3'
})

function onStatusChange(status) {
  emit('update-status', status)
}
</script>

<style scoped>
.decision-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 16px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
}
.db-left-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.db-right-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.severity-badge {
  padding: 2px 10px;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  font-weight: 500;
}
.badge-critical, .badge-high { background: #dc2626; }
.badge-medium { background: #d97706; }
.badge-low { background: #2563eb; }
.badge-info { background: #a3a3a3; }

.db-risk-score {
  font-size: 18px;
  font-weight: 600;
  min-width: 28px;
}
.db-cat-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
}
.db-stage-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
}
.db-status-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}
.st-pending { background: var(--color-accent-subtle); color: var(--color-accent-fg); }
.st-triaging, .st-investigating { background: #fef3c7; color: #d97706; }
.st-resolved { background: #dcfce7; color: #16a34a; }
.st-rejected { background: #fef2f2; color: #dc2626; }

.btn {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  font-size: 11px;
  border-radius: 6px;
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn:hover { opacity: 0.9; }
.btn-xs { padding: 3px 8px; font-size: 10px; line-height: 1.5; }
.btn-primary { background: var(--color-accent-fg, #2563eb); color: #fff; border-color: var(--color-accent-fg); }
.btn-warning { background: var(--color-warning-fg, #d97706); color: #fff; border-color: var(--color-warning-fg); }
.btn-success { background: var(--color-success-fg, #16a34a); color: #fff; border-color: var(--color-success-fg); }
.btn-danger { background: transparent; color: var(--color-danger-fg, #dc2626); border-color: var(--color-danger-fg); }
.btn-danger:hover { background: var(--color-danger-subtle); }
</style>
