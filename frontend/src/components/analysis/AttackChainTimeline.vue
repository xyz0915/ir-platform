<template>
  <div class="attack-timeline">
    <div class="at-stages">
      <div
        v-for="stage in stageGroups"
        :key="stage.stage"
        class="at-stage"
        :class="{
          'at-stage-current': stage.isCurrent,
          'at-stage-expanded': expandedStages[stage.stage],
        }"
        @click="toggleStage(stage.stage)"
      >
        <div class="at-stage-header">
          <span class="at-stage-dot" :class="{ 'at-dot-current': stage.isCurrent }"></span>
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
          <span class="at-summary-text">{{ getSummary(stage.events) }}</span>
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
    <!-- 空状态 -->
    <div class="at-empty" v-if="!stageGroups.length">
      <span>暂无时间线数据</span>
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

// 从 props 按阶段聚合（轻量本地聚合，不依赖 store）
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
      // 默认展开当前阶段
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

function eventTypeLabel(t) {
  return EVENT_TYPE_LABELS[t] || t
}

function getSummary(events) {
  if (!events || !events.length) return ''
  const last = events[events.length - 1]
  return last.summary || last.event_type || ''
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
  padding: 6px 12px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.1s;
}
.at-stage:hover {
  background: var(--color-canvas-inset);
}
.at-stage-current {
  border-left-color: var(--color-accent-fg, #2563eb);
  background: var(--color-accent-subtle, #eff6ff);
}
.at-stage-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.at-stage-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-fg-light, #a3a3a3);
  flex-shrink: 0;
}
.at-dot-current {
  background: var(--color-accent-fg, #2563eb);
  box-shadow: 0 0 0 2px var(--color-accent-subtle);
}
.at-stage-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default);
  flex: 1;
}
.at-stage-count {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 8px;
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
  min-width: 16px;
  text-align: center;
}
.at-count-highlight {
  background: var(--color-accent-fg, #2563eb);
  color: #fff;
}
.at-chevron {
  color: var(--color-fg-subtle);
  transition: transform 0.15s;
  flex-shrink: 0;
}
.at-chevron-open {
  transform: rotate(90deg);
}
.at-stage-summary {
  margin-top: 2px;
  margin-left: 14px;
  font-size: 10px;
  color: var(--color-fg-light);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.at-event-list {
  margin-top: 4px;
  margin-left: 14px;
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
.at-empty {
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--color-fg-light);
}
</style>
