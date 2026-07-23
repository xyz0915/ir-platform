<template>
  <div class="decision-bar">
    <div class="db-left-group">
      <!-- 严重度徽章 -->
      <span class="severity-badge" :class="'badge-' + (event.severity || 'info')">{{ (event.severity || 'info').toUpperCase() }}</span>

      <!-- 风险评分 -->
      <span class="db-risk-label">风险评分</span>
      <span class="db-risk-score" :style="{ color: riskScoreColor }">{{ riskScore }}</span>

      <!-- 攻击类型标签 -->
      <span v-if="categoryLabel" class="db-cat-tag">{{ categoryLabel }}</span>

      <!-- ATT&CK 阶段标签（紫色） -->
      <span v-if="event.attack_stage" class="db-attack-tag">
        <span class="db-attack-icon">ATT&CK</span>
        {{ stageLabel(event.attack_stage) }}
      </span>

      <!-- 状态标签 -->
      <span class="db-status-tag" :class="'st-' + (event.status || 'pending')">{{ statusLabel(event.status) }}</span>
    </div>

    <div class="db-right-group">
      <!-- 状态流转按钮 -->
      <button v-if="event.status === 'pending'" class="btn btn-xs" @click="onStatusChange('triaging')">分诊</button>
      <button v-if="event.status === 'triaging'" class="btn btn-xs" @click="onStatusChange('investigating')">调查</button>
      <button v-if="event.status === 'investigating'" class="btn btn-xs" @click="onStatusChange('resolved')">解决</button>
      <button v-if="event.status === 'resolved'" class="btn btn-xs" @click="onStatusChange('investigating')">重开</button>
      <button v-if="event.status !== 'rejected' && event.status !== 'resolved'" class="btn btn-xs btn-muted" @click="onStatusChange('rejected')">误报</button>

      <!-- 深度调查按钮（蓝色突出） -->
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
  if (props.event?.event_type === 'process_start') return '孤立进程'
  if (props.event?.event_type === 'ioc_match') return 'IOC命中'
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
  gap: 16px;
  padding: 12px 20px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid #e5e5e7;
  flex-wrap: wrap;
}
.db-left-group {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}
.db-right-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-left: auto;
}

.severity-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
}
.badge-critical { background: #FCEBEB; color: #A32D2D; }
.badge-high { background: #FCEBEB; color: #A32D2D; }
.badge-medium { background: #FAEEDA; color: #854F0B; }
.badge-low { background: #dbeafe; color: #1e40af; }
.badge-info { background: #f5f5f7; color: #888780; }

.db-risk-label {
  font-size: 12px;
  color: #888780;
}
.db-risk-score {
  font-size: 18px;
  font-weight: 600;
  min-width: 28px;
}
.db-cat-tag {
  font-size: 12px;
  padding: 3px 8px;
  border-radius: 4px;
  background: var(--color-canvas-inset);
  color: #888780;
}
.db-attack-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #FAEEDA;
  color: #854F0B;
}
.db-attack-icon {
  font-weight: 600;
  font-size: 10px;
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
  padding: 4px 12px;
  font-size: 12px;
  border-radius: 8px;
  border: 0.5px solid #b4b2a9;
  background: #fff;
  color: #444441;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn:hover { opacity: 0.85; }
.btn-xs { padding: 4px 12px; font-size: 12px; line-height: 1.5; }
.btn-primary { background: #E6F1FB; color: #185FA5; border-color: #378ADD; font-weight: 500; }
.btn-primary:hover { background: #d0e4f7; }
.btn-muted { background: transparent; color: #888780; border-color: #d3d1c7; }
.btn-muted:hover { background: #f5f5f7; }
</style>
