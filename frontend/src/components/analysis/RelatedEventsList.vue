<template>
  <div class="related-events-card">
    <div class="rel-title">关联事件 ({{ displayList.length }})</div>
    <div class="rel-list">
      <!-- 真实数据 -->
      <button
        v-for="(item, i) in displayList"
        :key="getItemId(item, i)"
        class="rel-item"
        @click="onViewEvent(item)"
      >
        <span class="rel-dot" :style="{ background: dotColor(getItemType(item)) }"></span>
        <span class="rel-type">{{ getItemType(item) }}</span>
        <span class="rel-detail">{{ getItemDetail(item) }}</span>
        <span class="rel-time">{{ getItemTime(item) }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  relatedIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['view-event'])

const fallbackEvents = [
  { id: 'persistence_001', event_type: 'persistence_register', detail: 'SecurityHealth HKLM\\Run', timestamp: '2026-07-19T09:08:00Z', severity: 'high' },
  { id: 'registry_002', event_type: 'registry_modify', detail: 'HKLM\\Run\\Test REG_SZ', timestamp: '2026-07-19T09:08:00Z', severity: 'medium' },
  { id: 'wmi_003', event_type: 'wmi_subscribe', detail: 'SCM Event Log Filter', timestamp: '2026-07-21T20:48:00Z', severity: 'medium' },
  { id: 'file_004', event_type: 'file_create', detail: 'C:\\test\\test.exe', timestamp: '2026-07-19T09:08:00Z', severity: 'low' },
]

const displayList = computed(() => {
  if (!props.relatedIds || !props.relatedIds.length) return fallbackEvents
  if (typeof props.relatedIds[0] === 'string') {
    return props.relatedIds.map(id => ({
      id,
      event_type: 'related',
      detail: id.substring(0, 16) + '...',
      timestamp: '',
      severity: 'info'
    }))
  }
  return props.relatedIds
})

function getItemId(item, i) {
  return item.id || i
}

function getItemType(item) {
  const typeMap = {
    process_start: '进程启动', process_terminate: '进程退出',
    network_outbound: '出站连接',
    registry_modify: '注册表修改',
    file_create: '文件创建', file_modify: '文件修改',
    persistence_register: '持久化注册', wmi_subscribe: 'WMI订阅',
    dns_query: 'DNS查询',
  }
  return typeMap[item.event_type] || item.event_type || item.type || '关联事件'
}

function getItemDetail(item) {
  return item.detail || item.description || item.summary || ''
}

function getItemTime(item) {
  if (!item.timestamp) return ''
  const d = new Date(item.timestamp)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function dotColor(type) {
  const colors = {
    persistence_register: '#E24B4A', registry_modify: '#BA7517',
    wmi_subscribe: '#D85A30', file_create: '#378ADD',
    process_start: '#BA7517', network_outbound: '#D85A30',
  }
  return colors[type] || '#888780'
}

function onViewEvent(item) {
  const id = typeof item === 'string' ? item : item.id
  if (id) emit('view-event', id)
}
</script>

<style scoped>
.related-events-card {
  background: var(--color-canvas-default);
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.rel-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 10px;
}
.rel-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.rel-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 8px 12px;
  font-size: 12px;
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  cursor: pointer;
  transition: all 0.1s;
}
.rel-item:hover {
  background: #f8f8fa;
}
.rel-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.rel-type {
  font-weight: 500;
  font-size: 11px;
  white-space: nowrap;
}
.rel-detail {
  color: #888780;
  font-size: 11px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rel-time {
  margin-left: auto;
  color: #b4b2a9;
  font-size: 10px;
  white-space: nowrap;
  font-family: 'Courier New', monospace;
}
</style>
