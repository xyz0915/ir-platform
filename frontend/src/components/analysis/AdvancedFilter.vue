<template>
  <div class="af">
    <div
      class="af-header"
      role="button"
      :aria-expanded="!collapsed"
      tabindex="0"
      @click="collapsed = !collapsed"
      @keydown.enter.prevent="collapsed = !collapsed"
      @keydown.space.prevent="collapsed = !collapsed"
    >
      <span class="af-title">高级筛选</span>
      <span class="af-toggle-label">{{ collapsed ? '点击展开' : '点击收起' }}</span>
      <span class="af-active-count" v-if="activeCount > 0">{{ activeCount }} 个筛选活跃</span>
      <span class="af-chevron-wrap">
        <svg
          class="af-chevron"
          :class="{ rotated: !collapsed }"
          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        >
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </span>
    </div>
    <div v-show="!collapsed" class="af-body">
      <!-- Row 1: 时间范围 -->
      <div class="af-row">
        <span class="af-row-label">时间范围</span>
        <div class="af-chips">
          <span
            v-for="t in timeOptions"
            :key="t.key"
            class="af-chip"
            :class="{ active: filters.timeRange === t.key }"
            @click="$emit('update', 'timeRange', t.key)"
          >{{ t.label }}</span>
        </div>
      </div>

      <!-- Row 2: 事件类型 + 严重度 -->
      <div class="af-row">
        <span class="af-row-label">事件类型</span>
        <div class="af-chips">
          <span
            v-for="et in eventTypes"
            :key="et.type"
            class="af-chip"
            :class="{ active: filters.eventType.includes(et.type) }"
            @click="toggleArray('eventType', et.type)"
          >{{ eventTypeLabel(et.type) }} <span class="af-cnt">{{ et.count }}</span></span>
        </div>
      </div>
      <div class="af-row">
        <span class="af-row-label">严重度</span>
        <div class="af-chips">
          <span
            v-for="s in severities"
            :key="s.severity"
            class="af-chip"
            :class="{ active: filters.severity.includes(s.severity) }"
            @click="toggleArray('severity', s.severity)"
          >
            <span class="sev-dot" :style="{ background: sevColor(s.severity) }"></span>
            {{ sevLabel(s.severity) }} <span class="af-cnt">{{ s.count }}</span>
          </span>
        </div>
      </div>

      <!-- Row 3: 规则分类 + 置信度 + 重置 -->
      <div class="af-row">
        <span class="af-row-label">规则分类</span>
        <div class="af-chips">
          <span
            v-for="c in ruleCategories"
            :key="c.category"
            class="af-chip"
            :class="{ active: filters.ruleCategory.includes(c.category) }"
            @click="toggleArray('ruleCategory', c.category)"
          >{{ RULE_CATEGORY_LABELS[c.category] || c.category }} <span class="af-cnt">{{ c.count }}</span></span>
        </div>
      </div>
      <div class="af-row">
        <span class="af-row-label">置信度</span>
        <select class="af-select" :value="filters.confidenceMin" @change="onConfidenceChange">
          <option :value="null">不限</option>
          <option :value="0.9">≥ 90%</option>
          <option :value="0.7">≥ 70%</option>
          <option :value="0.5">≥ 50%</option>
          <option :value="0.3">≥ 30%</option>
        </select>
        <button class="af-reset-btn" @click="$emit('reset')">重置筛选</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  filters: { type: Object, default: () => ({}) },
  meta: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['update', 'reset'])

const collapsed = ref(true)

const timeOptions = [
  { key: '1h', label: '1 小时' },
  { key: '24h', label: '24 小时' },
  { key: '7d', label: '7 天' },
  { key: 'all', label: '全部' },
]

const eventTypes = computed(() => props.meta.eventTypeCounts || [])
const severities = computed(() => props.meta.severityCounts || [])
const ruleCategories = computed(() => props.meta.hitRuleCategories || [])

const activeCount = computed(() => {
  let c = 0
  if (props.filters.timeRange !== 'all') c++
  if (props.filters.eventType.length) c++
  if (props.filters.severity.length) c++
  if (props.filters.ruleCategory.length) c++
  if (props.filters.confidenceMin) c++
  return c
})

const RULE_CATEGORY_LABELS = {
  process: '进程', network: '网络', persistence: '持久化',
  startup: '启动项', behavior: '行为', ioc: '情报',
  credential: '凭据', discovery: '发现', execution: '执行',
  lateral: '横向', impact: '影响', defense_evasion: '防御规避',
  privilege_escalation: '提权', exfiltration: '数据外泄',
  webshell: 'WebShell', memory_shell: '内存马',
  attack_chain: '攻击链',
}
const SEV_COLORS = {
  critical: '#dc2626', high: '#dc2626', medium: '#d97706',
  low: '#2563eb', info: '#a3a3a3',
}
const SEV_LABELS = {
  critical: '严重', high: '高危', medium: '中危',
  low: '低危', info: '信息',
}
const EVENT_TYPE_LABELS = {
  process_start: '进程启动', process_terminate: '进程退出',
  network_outbound: '出站连接', network_listen: '端口监听',
  registry_modify: '注册表写入', registry_delete: '注册表删除',
  file_create: '文件创建', file_modify: '文件修改',
  user_login: '用户登录', user_logout: '用户登出',
  dns_query: 'DNS查询', module_load: '模块加载',
  behavior_alert: '行为告警', ioc_match: 'IOC命中',
  persistence_register: '持久化注册', wmi_subscribe: 'WMI订阅',
  scheduled_task: '计划任务', service_operation: '服务操作',
  pipe_connect: '管道连接', driver_load: '驱动加载',
}

function sevColor(s) { return SEV_COLORS[s] || '#a3a3a3' }
function sevLabel(s) { return SEV_LABELS[s] || s }
function eventTypeLabel(t) { return EVENT_TYPE_LABELS[t] || t }

function toggleArray(key, value) {
  const arr = [...(props.filters[key] || [])]
  const idx = arr.indexOf(value)
  if (idx >= 0) arr.splice(idx, 1)
  else arr.push(value)
  emit('update', key, arr)
}

function onConfidenceChange(e) {
  const val = e.target.value === 'null' ? null : parseFloat(e.target.value)
  emit('update', 'confidenceMin', val)
}
</script>

<style scoped>
.af {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  overflow: hidden;
}
.af-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.af-header:hover {
  background: var(--color-canvas-subtle, #f5f5f5);
}
.af-header:focus-visible {
  outline: 2px solid var(--color-accent-fg, #2563eb);
  outline-offset: -2px;
}
.af-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}
.af-toggle-label {
  font-size: 10px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
  white-space: nowrap;
}
.af-active-count {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-accent-fg, #2563eb);
  background: var(--color-accent-subtle, #eff6ff);
  padding: 1px 6px;
  border-radius: 4px;
}
.af-chevron-wrap {
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  transition: background 0.15s;
}
.af-header:hover .af-chevron-wrap {
  background: var(--color-border-default, #e5e5e5);
}
.af-chevron {
  color: var(--color-fg-subtle, #888888);
  transition: transform 0.2s;
}
.af-chevron.rotated {
  transform: rotate(180deg);
}
.af-body {
  padding: 0 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.af-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.af-row-label {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  width: 56px;
  flex-shrink: 0;
  padding-top: 4px;
}
.af-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
}
.af-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1;
}
.af-chip:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  border-color: var(--color-accent-fg, #2563eb);
}
.af-chip.active {
  background: var(--color-accent-subtle, #eff6ff);
  border-color: var(--color-accent-fg, #2563eb);
  color: var(--color-accent-fg, #2563eb);
}
.af-cnt {
  font-size: 10px;
  color: var(--color-fg-light, #a3a3a3);
}
.af-chip.active .af-cnt {
  color: var(--color-accent-fg, #2563eb);
}
.sev-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.af-select {
  font-size: 11px;
  padding: 3px 6px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  outline: none;
}
.af-reset-btn {
  margin-left: auto;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-danger-fg, #dc2626);
  cursor: pointer;
  transition: all 0.15s;
}
.af-reset-btn:hover {
  background: var(--color-danger-subtle, #fef2f2);
  border-color: var(--color-danger-fg, #dc2626);
}
</style>
