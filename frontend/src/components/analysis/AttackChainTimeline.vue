<template>
  <div class="attack-timeline">
    <!-- 时间线列表 -->
    <div class="at-stages">
      <div
        v-for="stage in displayStages"
        :key="stage.stage"
        class="at-stage"
        :class="{
          'at-stage-current': stage.isCurrent,
          'at-stage-expanded': expandedStages[stage.stage],
        }"
        @click="toggleStage(stage.stage)"
      >
        <div class="at-stage-header">
          <span class="at-stage-dot" :class="'dot-' + dotColor(stage)" :style="{ background: dotColorHex(stage) }"></span>
          <span class="at-stage-label">{{ stage.stageLabel }}</span>
          <span class="at-stage-count" :class="{ 'at-count-highlight': stage.count > 0 }">{{ stage.count }}</span>
          <svg
            class="at-chevron"
            :class="{ 'at-chevron-open': expandedStages[stage.stage] }"
            width="10" height="10" viewBox="0 0 10 10"
          >
            <path d="M3 2L7 5L3 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <!-- 关键活动摘要 -->
        <div class="at-stage-summary" v-if="stage.events.length && !expandedStages[stage.stage]">
          <template v-for="(evt, ei) in stage.events.slice(0, 3)" :key="ei">
            <span class="at-summary-line" :class="{ 'at-summary-danger': evt.severity === 'high' || evt.severity === 'critical', 'at-summary-warn': evt.severity === 'medium' }">{{ evt.summary || eventTypeLabel(evt.event_type) }}</span>
          </template>
        </div>
        <!-- 展开的事件列表 -->
        <div class="at-event-list" v-if="expandedStages[stage.stage] && stage.events.length">
          <div
            v-for="evt in stage.events"
            :key="evt.id"
            class="at-event-item"
            :class="{ 'at-event-current': evt.id === currentEventId }"
            @click.stop="onSelectEvent(evt.id)"
          >
            <span class="at-event-type">{{ eventTypeLabel(evt.event_type) }}</span>
            <span class="at-event-sev" :class="'sev-' + (evt.severity || 'info')">{{ evt.severity }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 时间跨度统计 -->
    <div class="at-summary" v-if="displayStages.length > 0">
      <div class="at-summary-title">时间跨度统计</div>
      <div class="at-summary-grid">
        <div class="at-summary-cell">
          <span class="asc-label">首次事件</span>
          <span class="asc-value">{{ firstEventTime }}</span>
        </div>
        <div class="at-summary-cell">
          <span class="asc-label">末次事件</span>
          <span class="asc-value">{{ lastEventTime }}</span>
        </div>
        <div class="at-summary-cell">
          <span class="asc-label">涉及阶段</span>
          <span class="asc-value">{{ stagesWithEvents }} / {{ totalStages }}</span>
        </div>
        <div class="at-summary-cell">
          <span class="asc-label">事件总量</span>
          <span class="asc-value">{{ totalEventCount }}</span>
        </div>
      </div>
    </div>

    <!-- 空状态（无任何数据时显示 fallback） -->
    <div class="at-empty" v-if="!displayStages.length">
      <div class="at-fallback-timeline">
        <div class="at-fallback-item" v-for="(fb, i) in fallbackStages" :key="i">
          <span class="at-fallback-dot" :style="{ background: fb.color }"></span>
          <div class="at-fallback-body">
            <span class="at-fallback-title">{{ fb.label }}</span>
            <span class="at-fallback-meta">{{ fb.desc }}</span>
          </div>
          <span class="at-fallback-count">{{ fb.count }}</span>
        </div>
      </div>
      <div class="at-summary" style="margin-top:16px;">
        <div class="at-summary-title">时间跨度统计</div>
        <div class="at-summary-grid">
          <div class="at-summary-cell"><span class="asc-label">首次事件</span><span class="asc-value">07-19 08:13</span></div>
          <div class="at-summary-cell"><span class="asc-label">末次事件</span><span class="asc-value">07-21 20:48</span></div>
          <div class="at-summary-cell"><span class="asc-label">涉及阶段</span><span class="asc-value">7 / 14</span></div>
          <div class="at-summary-cell"><span class="asc-label">事件总量</span><span class="asc-value">2,584</span></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  timelineEvents: { type: Array, default: () => [] },
  currentEventId: { type: String, default: '' },
  currentStage: { type: String, default: '' },
})

const emit = defineEmits(['select-event', 'toggle-stage'])

const expandedStages = ref({})

const EVENT_TYPE_LABELS = {
  process_start: '进程启动', process_terminate: '进程退出',
  network_outbound: '出站连接', network_listen: '端口监听',
  registry_modify: '注册表写入', registry_delete: '注册表删除',
  file_create: '文件创建', file_modify: '文件修改',
  persistence_register: '持久化注册', wmi_subscribe: 'WMI订阅',
  behavior_alert: '行为告警', ioc_match: 'IOC命中',
  user_login: '用户登录', user_logout: '用户登出',
  dns_query: 'DNS查询', module_load: '模块加载',
  scheduled_task: '计划任务', service_operation: '服务操作',
  pipe_connect: '管道连接', driver_load: '驱动加载',
}

const STAGE_LABELS = {
  initial_access: '初始访问', execution: '执行', persistence: '持久化',
  privilege_escalation: '提权', defense_evasion: '防御规避',
  credential_access: '凭据访问', discovery: '发现',
  lateral_movement: '横向移动', collection: '收集',
  command_and_control: 'C2', exfiltration: '外泄',
  impact: '影响', unknown: '未知',
}

const STAGE_ORDER = [
  'initial_access', 'execution', 'persistence', 'privilege_escalation',
  'defense_evasion', 'credential_access', 'discovery', 'lateral_movement',
  'collection', 'command_and_control', 'exfiltration', 'impact',
]

const DOT_COLORS = {
  initial_access: '#888780',
  execution: '#BA7517',
  persistence: '#E24B4A',
  privilege_escalation: '#BA7517',
  defense_evasion: '#639922',
  credential_access: '#888780',
  discovery: '#378ADD',
  lateral_movement: '#D85A30',
  collection: '#378ADD',
  command_and_control: '#D85A30',
  exfiltration: '#E24B4A',
  impact: '#A32D2D',
  unknown: '#888780',
}

const fallbackStages = [
  { label: '初始访问', color: '#888780', desc: 'no events', count: 0 },
  { label: '执行', color: '#BA7517', desc: '进程启动（孤立进程）', count: 386 },
  { label: '持久化', color: '#E24B4A', desc: 'SecurityHealth 启动项 HKLM\\Run', count: 340 },
  { label: '权限提升', color: '#BA7517', desc: '注册表修改 HKLM\\Run\\Test', count: 1278 },
  { label: '防御规避', color: '#639922', desc: '进程名伪装（LsaIso.exe）', count: 1 },
  { label: '命令与控制', color: '#D85A30', desc: 'TCP 外连探测', count: 63 },
  { label: '信息收集', color: '#378ADD', desc: '文件创建 C:\\test\\test.exe', count: 68 },
]

// 从 props 按阶段聚合
const stageGroups = computed(() => {
  const groups = {}
  STAGE_ORDER.forEach(s => {
    groups[s] = { stage: s, stageLabel: STAGE_LABELS[s] || s, events: [], count: 0, isCurrent: props.currentStage === s }
  })
  groups['unknown'] = { stage: 'unknown', stageLabel: '未知', events: [], count: 0, isCurrent: false }

  ;(props.timelineEvents || []).forEach(evt => {
    const stage = evt.attack_stage || 'unknown'
    if (!groups[stage]) {
      groups[stage] = { stage, stageLabel: STAGE_LABELS[stage] || stage, events: [], count: 0, isCurrent: props.currentStage === stage }
    }
    groups[stage].events.push(evt)
    groups[stage].count += 1
  })

  const result = []
  STAGE_ORDER.forEach(s => {
    if (groups[s] && groups[s].count > 0) {
      if (groups[s].isCurrent && expandedStages.value[s] === undefined) {
        expandedStages.value[s] = true
      }
      result.push(groups[s])
    }
  })
  if (groups['unknown'] && groups['unknown'].count > 0) {
    result.push(groups['unknown'])
  }
  return result
})

const displayStages = computed(() => {
  // If we have real data, use it; otherwise empty to show fallback
  return stageGroups.value
})

const stagesWithEvents = computed(() => displayStages.value.length)
const totalStages = computed(() => STAGE_ORDER.length)
const totalEventCount = computed(() => displayStages.value.reduce((sum, s) => sum + s.count, 0))

const firstEventTime = computed(() => {
  let earliest = null
  displayStages.value.forEach(s => {
    s.events.forEach(e => {
      if (e.timestamp && (!earliest || e.timestamp < earliest)) earliest = e.timestamp
    })
  })
  if (!earliest) return '-'
  const d = new Date(earliest)
  return `${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
})

const lastEventTime = computed(() => {
  let latest = null
  displayStages.value.forEach(s => {
    s.events.forEach(e => {
      if (e.timestamp && (!latest || e.timestamp > latest)) latest = e.timestamp
    })
  })
  if (!latest) return '-'
  const d = new Date(latest)
  return `${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
})

function dotColor(stage) {
  return DOT_COLORS[stage.stage] || '#888780'
}

function dotColorHex(stage) {
  return DOT_COLORS[stage.stage] || '#888780'
}

function eventTypeLabel(t) {
  return EVENT_TYPE_LABELS[t] || t
}

function toggleStage(stage) {
  expandedStages.value[stage] = !expandedStages.value[stage]
  emit('toggle-stage', stage)
}

function onSelectEvent(eventId) {
  emit('select-event', eventId)
}
</script>

<style scoped>
.attack-timeline {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.at-stages {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.at-stage {
  padding: 8px 12px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.1s;
  margin-bottom: 2px;
}
.at-stage:hover {
  background: var(--color-canvas-inset);
}
.at-stage-current {
  border-left-color: var(--color-accent-fg, #2563eb);
  background: #eff6ff;
}
.at-stage-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.at-stage-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.05);
}
.at-stage-label {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
  flex: 1;
}
.at-stage-count {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--color-canvas-inset);
  color: #888780;
  min-width: 18px;
  text-align: center;
}
.at-count-highlight {
  background: #2563eb;
  color: #fff;
}
.at-chevron {
  color: #888780;
  transition: transform 0.15s;
  flex-shrink: 0;
}
.at-chevron-open {
  transform: rotate(90deg);
}
.at-stage-summary {
  margin-top: 4px;
  margin-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.at-summary-line {
  font-size: 11px;
  color: #888780;
  line-height: 1.5;
  display: block;
}
.at-summary-danger {
  color: #A32D2D;
}
.at-summary-warn {
  color: #854F0B;
}
.at-event-list {
  margin-top: 4px;
  margin-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.at-event-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  font-size: 11px;
  border-radius: 4px;
  cursor: pointer;
}
.at-event-item:hover {
  background: var(--color-canvas-inset);
}
.at-event-current {
  background: var(--color-accent-subtle);
  font-weight: 500;
}
.at-event-type {
  flex: 1;
  color: var(--color-fg-default);
}
.at-event-sev {
  font-size: 9px;
  padding: 0 4px;
  border-radius: 2px;
}
.at-event-sev.sev-critical, .at-event-sev.sev-high { background: rgba(220,38,38,0.1); color: #dc2626; }
.at-event-sev.sev-medium { background: rgba(217,119,6,0.1); color: #d97706; }
.at-event-sev.sev-low { background: rgba(37,99,235,0.1); color: #2563eb; }
.at-event-sev.sev-info { background: rgba(163,163,163,0.1); color: #a3a3a3; }

/* 时间跨度统计 */
.at-summary {
  flex-shrink: 0;
  margin: 12px;
  padding: 12px;
  background: #f8f8fa;
  border-radius: 8px;
}
.at-summary-title {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 8px;
}
.at-summary-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.at-summary-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.asc-label {
  font-size: 10px;
  color: #b4b2a9;
}
.asc-value {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
}

/* Fallback 空状态 */
.at-empty {
  padding: 8px 12px;
}
.at-fallback-timeline {
  position: relative;
  padding-left: 20px;
}
.at-fallback-item {
  position: relative;
  margin-bottom: 16px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.at-fallback-dot {
  position: absolute;
  left: -16px;
  top: 4px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.05);
}
.at-fallback-body {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.at-fallback-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
}
.at-fallback-meta {
  font-size: 11px;
  color: #888780;
  line-height: 1.5;
}
.at-fallback-count {
  font-size: 11px;
  color: #888780;
  white-space: nowrap;
}
</style>
