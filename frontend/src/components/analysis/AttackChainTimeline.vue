<template>
  <div class="attack-timeline">
    <!-- ========== 加载态（骨架屏） ========== -->
    <div class="at-loading" v-if="loading && !timelineEvents.length">
      <div class="at-skeleton" v-for="i in 3" :key="i">
        <div class="at-skel-header"></div>
        <div class="at-skel-event" v-for="j in (i === 1 ? 3 : 2)" :key="j"></div>
      </div>
    </div>

    <!-- ========== 错误态 ========== -->
    <div class="at-error" v-else-if="error">
      <div class="at-error-icon">&#9888;</div>
      <div class="at-error-text">时间线数据加载失败</div>
      <div class="at-error-detail" v-if="error">{{ error }}</div>
      <button class="at-retry-btn" @click="onRetry">重试</button>
    </div>

    <!-- ========== 正常数据 ========== -->
    <template v-else-if="displayStages.length > 0">
      <div class="at-stages">
        <template v-for="(stage, si) in displayStages" :key="stage.stage">
          <!-- 阶段间箭头（P1）：只在上一个阶段展开时显示 -->
          <div
            v-if="si > 0 && expandedStages[displayStages[si - 1].stage]"
            class="at-stage-arrow"
          >
            <div class="at-arrow-line"></div>
            <div class="at-arrow-head"></div>
          </div>

          <!-- 阶段区块 -->
          <div
            class="at-stage"
            :class="{
              'at-stage-current': stage.isCurrent,
              'at-stage-expanded': expandedStages[stage.stage],
            }"
          >
            <!-- 阶段头部 -->
            <div class="at-stage-header" @click="toggleStage(stage.stage)">
              <span
                class="at-stage-dot"
                :class="'dot-' + dotColor(stage)"
                :style="{ background: dotColorHex(stage) }"
              ></span>
              <span class="at-stage-num">{{ stageIndex(stage) }}</span>
              <span class="at-stage-label">{{ stage.stageLabel }}</span>
              <span
                class="at-stage-count"
                :class="{ 'at-count-highlight': stage.count > 0 }"
              >{{ stage.count }}</span>
              <!-- P1: 阶段最高严重度标记 -->
              <span
                v-if="stageMaxSeverity(stage)"
                class="at-stage-severity-badge"
                :class="'ssb-' + stageMaxSeverity(stage).severity"
              >
                {{ stageMaxSeverity(stage).count }}
                {{ severityLabel(stageMaxSeverity(stage).severity) }}
              </span>
              <svg
                class="at-chevron"
                :class="{ 'at-chevron-open': expandedStages[stage.stage] }"
                width="10" height="10" viewBox="0 0 10 10"
              >
                <path d="M3 2L7 5L3 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
            </div>

            <!-- 折叠摘要（折叠态时显示前 3 条摘要） -->
            <div
              class="at-stage-summary"
              v-if="stage.events.length && !expandedStages[stage.stage]"
            >
              <template v-for="(evt, ei) in stage.events.slice(0, 3)" :key="ei">
                <span
                  class="at-summary-line"
                  :class="{
                    'at-summary-danger': evt.severity === 'high' || evt.severity === 'critical',
                    'at-summary-warn': evt.severity === 'medium'
                  }"
                >
                  {{ formatTimestamp(evt.timestamp) }}
                  {{ EVENT_TYPE_ICONS[evt.event_type] || '?' }}
                  {{ extractEventFields(evt).primary }}
                </span>
              </template>
            </div>

            <!-- 展开的事件列表（v-show 而非 v-if，避免 DOM 销毁重建） -->
            <div
              class="at-event-list"
              v-show="expandedStages[stage.stage] && stage.events.length"
            >
              <div
                v-for="evt in visibleEvents(stage)"
                :key="evt.id"
                :ref="el => { if (el) eventRefs[evt.id] = el }"
                class="at-event-item"
                :class="{ 'at-event-current': evt.id === currentEventId }"
                @click.stop="onSelectEvent(evt.id)"
              >
                <span class="ae-timestamp">{{ formatTimestamp(evt.timestamp) }}</span>
                <span class="ae-icon">{{ EVENT_TYPE_ICONS[evt.event_type] || '?' }}</span>
                <span class="ae-type-label">{{ eventTypeLabel(evt.event_type) }}</span>
                <span class="ae-content">
                  <span class="ae-primary">{{ extractEventFields(evt).primary }}</span>
                  <span class="ae-secondary" v-if="extractEventFields(evt).secondary">
                    {{ extractEventFields(evt).secondary }}
                  </span>
                </span>
                <span
                  class="ae-severity"
                  :class="'sev-' + (evt.severity || 'info')"
                >{{ severityLabel(evt.severity || 'info') }}</span>
              </div>
              <!-- 事件截断：超过 MAX_VISIBLE_EVENTS 条时显示 "显示全部" 按钮 -->
              <div
                v-if="stage.events.length > MAX_VISIBLE_EVENTS && !showAllStages[stage.stage]"
                class="at-show-all"
                @click.stop="showAllStages[stage.stage] = true"
              >
                显示全部 {{ stage.events.length }} 条
              </div>
            </div>
          </div>
        </template>
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
    </template>

    <!-- ========== 空状态 ========== -->
    <div class="at-empty" v-else>
      <div class="at-empty-icon">&#128203;</div>
      <div class="at-empty-text">暂无时间线数据</div>
      <div class="at-empty-hint">请确认案件关联的事件是否存在</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

// ── Props ──
const props = defineProps({
  timelineEvents: { type: Array, default: () => [] },
  currentEventId: { type: String, default: '' },
  currentStage: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['select-event', 'toggle-stage', 'retry'])

// ── 内部状态 ──
const expandedStages = ref({})
const showAllStages = ref({})
const eventRefs = {}
const MAX_VISIBLE_EVENTS = 50

// ── 事件类型图标映射 ──
const EVENT_TYPE_ICONS = {
  process_start: '\u{1F680}',
  process_terminate: '\u23F9\uFE0F',
  network_outbound: '\u{1F310}',
  network_listen: '\u{1F50A}',
  registry_modify: '\u{1F4DD}',
  registry_delete: '\u{1F5D1}\uFE0F',
  file_create: '\u{1F4C1}',
  file_modify: '\u270F\uFE0F',
  persistence_register: '\u{1F517}',
  wmi_subscribe: '\u2699\uFE0F',
  behavior_alert: '\u26A0\uFE0F',
  ioc_match: '\u{1F3AF}',
  user_login: '\u{1F464}',
  user_logout: '\u{1F464}',
  dns_query: '\u{1F50D}',
  module_load: '\u{1F50C}',
  scheduled_task: '\u23F0',
  service_operation: '\u2699\uFE0F',
  pipe_connect: '\u{1F4E1}',
  driver_load: '\u{1F6E0}\uFE0F',
}

// ── 事件类型中文标签 ──
const EVENT_TYPE_LABELS = {
  process_start: '\u8FDB\u7A0B\u542F\u52A8',
  process_terminate: '\u8FDB\u7A0B\u9000\u51FA',
  network_outbound: '\u51FA\u7AD9\u8FDE\u63A5',
  network_listen: '\u7AEF\u53E3\u76D1\u542C',
  registry_modify: '\u6CE8\u518C\u8868\u4FEE\u6539',
  registry_delete: '\u6CE8\u518C\u8868\u5220\u9664',
  file_create: '\u6587\u4EF6\u521B\u5EFA',
  file_modify: '\u6587\u4EF6\u4FEE\u6539',
  persistence_register: '\u6301\u4E45\u5316\u6CE8\u518C',
  wmi_subscribe: 'WMI\u8BA2\u9605',
  behavior_alert: '\u884C\u4E3A\u544A\u8B66',
  ioc_match: 'IOC\u547D\u4E2D',
  user_login: '\u7528\u6237\u767B\u5F55',
  user_logout: '\u7528\u6237\u767B\u51FA',
  dns_query: 'DNS\u67E5\u8BE2',
  module_load: '\u6A21\u5757\u52A0\u8F7D',
  scheduled_task: '\u8BA1\u5212\u4EFB\u52A1',
  service_operation: '\u670D\u52A1\u64CD\u4F5C',
  pipe_connect: '\u7BA1\u9053\u8FDE\u63A5',
  driver_load: '\u9A71\u52A8\u52A0\u8F7D',
}

// ── 严重度标签 ──
const SEVERITY_LABELS = {
  critical: '\u4E25\u91CD',
  high: '\u9AD8\u5371',
  medium: '\u4E2D\u5371',
  low: '\u4F4E\u5371',
  info: '\u4FE1\u606F',
}

// ── 阶段定义 ──
const STAGE_LABELS = {
  initial_access: '\u521D\u59CB\u8BBF\u95EE',
  execution: '\u6267\u884C',
  persistence: '\u6301\u4E45\u5316',
  privilege_escalation: '\u63D0\u6743',
  defense_evasion: '\u9632\u5FA1\u89C4\u907F',
  credential_access: '\u51ED\u636E\u8BBF\u95EE',
  discovery: '\u53D1\u73B0',
  lateral_movement: '\u6A2A\u5411\u79FB\u52A8',
  collection: '\u6536\u96C6',
  command_and_control: 'C2',
  exfiltration: '\u5916\u6CC4',
  impact: '\u5F71\u54CD',
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
}

// ── 工具函数 ──

/**
 * 格式化 ISO 8601 时间戳为 HH:MM:SS
 */
function formatTimestamp(ts) {
  if (!ts) return '--:--:--'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return '--:--:--'
  return [
    String(d.getHours()).padStart(2, '0'),
    String(d.getMinutes()).padStart(2, '0'),
    String(d.getSeconds()).padStart(2, '0'),
  ].join(':')
}

/**
 * 严重度中文标签
 */
function severityLabel(sev) {
  return SEVERITY_LABELS[sev] || sev
}

/**
 * 事件类型中文标签
 */
function eventTypeLabel(t) {
  return EVENT_TYPE_LABELS[t] || t
}

/**
 * 圆点颜色（返回 CSS class 后缀）
 */
function dotColor(stage) {
  return DOT_COLORS[stage.stage] || '#888780'
}

/**
 * 圆点颜色（返回 hex）
 */
function dotColorHex(stage) {
  return DOT_COLORS[stage.stage] || '#888780'
}

/**
 * 阶段序号（基于 displayStages 计算 1-based）
 */
function stageIndex(stage) {
  const idx = displayStages.value.findIndex(s => s.stage === stage.stage)
  return idx >= 0 ? idx + 1 : ''
}

/**
 * 从事件对象提取关键字段
 * 字段优先级：事件顶层字段 → evidence 对象 → summary
 */
function extractEventFields(evt) {
  if (!evt) return { primary: '?', secondary: null }

  // 尝试从 evidence 提取（可能是字符串或对象）
  let ev = evt.evidence
  if (typeof ev === 'string') {
    try { ev = JSON.parse(ev) } catch { ev = {} }
  }
  if (!ev || typeof ev !== 'object') ev = {}

  const et = evt.event_type || ''

  // field extraction helpers
  const val = (topField, evidenceField) => {
    return evt[topField] || ev[evidenceField] || ev[topField] || null
  }

  switch (true) {
    // 进程事件
    case et === 'process_start' || et === 'process_terminate': {
      const pn = val('process_name', 'process_name') || evt.summary || '?'
      const pid = val('pid', 'pid')
      return { primary: `${pn}${pid ? ` (PID ${pid})` : ''}`, secondary: null }
    }

    // 网络出站
    case et === 'network_outbound': {
      const addr = val('remote_address', 'remote_address') || '?'
      const port = val('remote_port', 'remote_port')
      const pn = val('process_name', 'process_name')
      const primary = `${addr}${port ? `:${port}` : ''}`
      const secondary = pn ? `\u2190 ${pn}` : null
      return { primary, secondary }
    }

    // 网络监听
    case et === 'network_listen': {
      const addr = val('local_address', 'local_address') || '?'
      const port = val('local_port', 'local_port')
      const pn = val('process_name', 'process_name')
      const primary = `${addr}${port ? `:${port}` : ''}`
      const secondary = pn ? `(${pn})` : null
      return { primary, secondary }
    }

    // 注册表事件
    case et === 'registry_modify' || et === 'registry_delete': {
      const rk = val('registry_key', 'registry_key') || val('key_path', 'key_path') || evt.summary || '?'
      return { primary: rk, secondary: null }
    }

    // 文件事件
    case et === 'file_create' || et === 'file_modify': {
      const fp = val('file_path', 'file_path') || val('file_name', 'file_name') || evt.summary || '?'
      return { primary: fp, secondary: null }
    }

    // 持久化注册
    case et === 'persistence_register': {
      const nm = val('name', 'name') || val('file_name', 'file_name') || evt.summary || '?'
      return { primary: nm, secondary: null }
    }

    // DNS 查询
    case et === 'dns_query': {
      const domain = val('remote_address', 'remote_address') || evt.summary || '?'
      const pn = val('process_name', 'process_name')
      const secondary = pn ? `\u2190 ${pn}` : null
      return { primary: domain, secondary }
    }

    // 用户登录
    case et === 'user_login' || et === 'user_logout': {
      const hn = val('hostname', 'hostname') || '?'
      const summary = evt.summary || ''
      return { primary: hn, secondary: summary || null }
    }

    // 模块加载
    case et === 'module_load': {
      const fn = val('file_name', 'file_name') || evt.summary || '?'
      const pn = val('process_name', 'process_name')
      const secondary = pn ? `(${pn})` : null
      return { primary: fn, secondary }
    }

    // 行为告警 / IOC 命中 / 计划任务 / 服务操作
    case et === 'behavior_alert' || et === 'ioc_match' || et === 'scheduled_task' || et === 'service_operation': {
      return { primary: evt.summary || et, secondary: null }
    }

    // 驱动加载
    case et === 'driver_load': {
      const fn = val('file_name', 'file_name') || evt.summary || '?'
      return { primary: fn, secondary: null }
    }

    // WMI 订阅 / 管道连接
    case et === 'wmi_subscribe' || et === 'pipe_connect': {
      return { primary: evt.summary || et, secondary: null }
    }

    // 默认
    default:
      return { primary: evt.summary || et, secondary: null }
  }
}

/**
 * 计算阶段最高严重度（P1）
 * 返回 { severity: string, count: number } | null
 * 仅当最高严重度 >= 'medium' 时返回
 */
function stageMaxSeverity(stage) {
  if (!stage || !stage.events || stage.events.length === 0) return null
  const order = ['critical', 'high', 'medium', 'low', 'info']
  let maxSev = null
  const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }

  stage.events.forEach(evt => {
    const s = evt.severity || 'info'
    if (counts[s] !== undefined) counts[s]++
    if (!maxSev || order.indexOf(s) < order.indexOf(maxSev)) {
      maxSev = s
    }
  })

  if (!maxSev || ['low', 'info'].includes(maxSev)) return null
  return { severity: maxSev, count: counts[maxSev] }
}

/**
 * 当前阶段可见事件列表（支持截断）
 */
function visibleEvents(stage) {
  if (!stage || !stage.events) return []
  if (showAllStages.value[stage.stage]) {
    return stage.events
  }
  return stage.events.slice(0, MAX_VISIBLE_EVENTS)
}

// ── Computed ──

// 从 props 按阶段聚合
const stageGroups = computed(() => {
  const groups = {}
  STAGE_ORDER.forEach(s => {
    groups[s] = { stage: s, stageLabel: STAGE_LABELS[s] || s, events: [], count: 0, isCurrent: props.currentStage === s }
  })
  groups['unknown'] = { stage: 'unknown', stageLabel: '\u672A\u77E5', events: [], count: 0, isCurrent: false }

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

const displayStages = computed(() => stageGroups.value)

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

// ── Watchers ──

// 当前事件高亮 + 自动滚动
watch(() => props.currentEventId, (newId) => {
  if (!newId) return
  // 自动展开该事件所在阶段
  const event = (props.timelineEvents || []).find(e => e.id === newId)
  if (event && event.attack_stage) {
    expandedStages.value[event.attack_stage] = true
  }

  nextTick(() => {
    const el = eventRefs[newId]
    if (el) {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })
}, { immediate: false })

// 当前阶段变化时自动展开
watch(() => props.currentStage, (newStage) => {
  if (newStage) {
    expandedStages.value[newStage] = true
  }
}, { immediate: true })

// ── 交互方法 ──

function toggleStage(stage) {
  expandedStages.value[stage] = !expandedStages.value[stage]
  emit('toggle-stage', stage)
}

function onSelectEvent(eventId) {
  emit('select-event', eventId)
}

function onRetry() {
  emit('retry')
}
</script>

<style scoped>
/* ── 基础容器 ── */
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

/* ── 阶段区块 ── */
.at-stage {
  padding: 6px 12px;
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

/* ── 阶段头部 ── */
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

.at-stage-num {
  font-size: 10px;
  color: #888780;
  min-width: 14px;
  text-align: center;
  font-weight: 500;
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
  background: #eef0f3;
  color: #4a5260;
  font-weight: 500;
}

/* P1: 阶段最高严重度标记 — 去 AI 警示感，改中性 */
.at-stage-severity-badge {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 500;
  white-space: nowrap;
  background: #f5f5f5;
  color: #6b7280;
}

.ssb-critical {
  background: #f5f5f5;
  color: #6b7280;
}

.ssb-high {
  background: #f5f5f5;
  color: #6b7280;
}

.ssb-medium {
  background: #f5f5f5;
  color: #6b7280;
}

.at-chevron {
  color: #888780;
  transition: transform 0.15s;
  flex-shrink: 0;
}

.at-chevron-open {
  transform: rotate(90deg);
}

/* ── 阶段间箭头（P1） ── */
.at-stage-arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-left: 18px;
  height: 16px;
  position: relative;
}

.at-arrow-line {
  width: 2px;
  flex: 1;
  background: #d1d5db;
}

.at-arrow-head {
  width: 0;
  height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid #d1d5db;
}

/* ── 折叠摘要 ── */
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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.at-summary-danger {
  color: #4a5260;
}

.at-summary-warn {
  color: #6b7280;
}

/* ── 事件列表 ── */
.at-event-list {
  margin-top: 4px;
  margin-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

/* ── 单条事件条目 ── */
.at-event-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 11px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.1s;
}

.at-event-item:hover {
  background: #f3f4f6;
}

.at-event-current {
  background: #eff6ff !important;
  outline: 1px solid #93c5fd;
}

/* 时间戳列 */
.ae-timestamp {
  font-family: 'SF Mono', 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 11px;
  color: #888780;
  min-width: 60px;
  flex-shrink: 0;
  letter-spacing: 0.3px;
}

/* 图标列 */
.ae-icon {
  font-size: 13px;
  width: 20px;
  text-align: center;
  flex-shrink: 0;
  line-height: 1;
}

/* 事件类型标签列 */
.ae-type-label {
  font-size: 10px;
  color: #6b7280;
  min-width: 52px;
  flex-shrink: 0;
}

/* 内容列 */
.ae-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.ae-primary {
  font-weight: 500;
  color: #1d1d1f;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ae-secondary {
  font-size: 10px;
  color: #888780;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 严重度标签列 — 去 AI 红橙警示，改中性灰 */
.ae-severity {
  font-size: 9px;
  padding: 0 5px;
  border-radius: 3px;
  font-weight: 500;
  flex-shrink: 0;
  line-height: 16px;
  white-space: nowrap;
  background: #f5f5f5;
  color: #6b7280;
}

.ae-severity.sev-critical { color: #4a5260; }
.ae-severity.sev-high { color: #4a5260; }
.ae-severity.sev-medium { color: #6b7280; }
.ae-severity.sev-low { color: #9ca3af; }
.ae-severity.sev-info { color: #c0c4cc; }

/* ── "显示全部 N 条" 按钮 ── */
.at-show-all {
  font-size: 11px;
  color: #2563eb;
  cursor: pointer;
  padding: 4px 8px;
  text-align: center;
  border-radius: 4px;
  margin-top: 2px;
  transition: background 0.1s;
}

.at-show-all:hover {
  background: #eff6ff;
  text-decoration: underline;
}

/* ── 骨架屏（加载态） ── */
.at-loading {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.at-skeleton {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: #f9fafb;
  border-radius: 6px;
}

.at-skel-header {
  height: 14px;
  width: 60%;
  border-radius: 4px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

.at-skel-event {
  height: 10px;
  width: 85%;
  border-radius: 4px;
  background: linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  margin-left: 12px;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ── 错误态 ── */
.at-error {
  padding: 40px 12px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.at-error-icon {
  font-size: 32px;
  line-height: 1;
  color: #F56C6C;
}

.at-error-text {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
}

.at-error-detail {
  font-size: 11px;
  color: #888780;
  max-width: 240px;
  word-break: break-all;
}

.at-retry-btn {
  margin-top: 4px;
  padding: 6px 16px;
  font-size: 12px;
  color: #fff;
  background: #2563eb;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.1s;
}

.at-retry-btn:hover {
  background: #1d4ed8;
}

/* ── 空状态 ── */
.at-empty {
  padding: 40px 12px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.at-empty-icon {
  font-size: 32px;
  line-height: 1;
  color: #d1d5db;
}

.at-empty-text {
  font-size: 13px;
  color: #888780;
}

.at-empty-hint {
  font-size: 11px;
  color: #b4b2a9;
}

/* ── 时间跨度统计 ── */
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
</style>
