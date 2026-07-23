<template>
  <div class="event-summary-card">
    <!-- 事件概要网格 -->
    <div class="esc-grid">
      <div class="esc-row">
        <span class="esc-label">事件类型</span>
        <span class="esc-value">{{ eventTypeLabel(event.event_type) }}</span>
      </div>
      <div class="esc-row">
        <span class="esc-label">时间</span>
        <span class="esc-value">{{ formatTime(event.timestamp) }}</span>
      </div>
      <div class="esc-row">
        <span class="esc-label">主机</span>
        <span class="esc-value">
          <span class="esc-host-link" @click="onFilterByHost" v-if="event.host_id">
            {{ event.hostname || ('主机#' + event.host_id) }}
          </span>
          <template v-else>—</template>
        </span>
      </div>
      <div class="esc-row">
        <span class="esc-label">IP 地址</span>
        <span class="esc-value esc-ip">{{ event.ip_address || '—' }}</span>
      </div>
      <div class="esc-row">
        <span class="esc-label">采集器</span>
        <span class="esc-value">{{ event.source_collector || '—' }}</span>
      </div>
      <div class="esc-row" v-if="event.attack_chain_id">
        <span class="esc-label">攻击链 ID</span>
        <span class="esc-value esc-mono">{{ event.attack_chain_id }}</span>
      </div>
    </div>

    <!-- 同类事件频率 -->
    <div class="esc-freq" v-if="frequency">
      <span class="esc-freq-label">同类事件频率</span>
      <span class="esc-freq-value">
        首次 {{ formatTime(frequency.first_seen) }}
        · 最近 {{ formatTime(frequency.last_seen) }}
        · 共 <strong :class="{ 'freq-highlight': frequency.total > 50 }">{{ frequency.total }}</strong> 次
        · {{ frequency.affected_hosts }} 台主机
      </span>
    </div>

    <!-- 父进程（按事件类型条件显示） -->
    <div class="esc-row" v-if="event.evidence?.parent_name">
      <span class="esc-label">父进程</span>
      <span class="esc-value">{{ event.evidence.parent_name }} <span class="esc-sub">(PPID: {{ event.evidence.ppid || '?' }})</span></span>
    </div>

    <!-- 文件哈希 -->
    <div class="esc-row" v-if="event.evidence?.sha256">
      <span class="esc-label">文件哈希</span>
      <span class="esc-value">
        <span class="hash-with-actions">
          <span class="hash-val">{{ event.evidence.sha256.substring(0, 16) }}...</span>
          <button class="hash-act-btn" @click.stop="copyHash(event.evidence.sha256)">复制</button>
          <button class="hash-act-btn" @click.stop="openVT(event.evidence.sha256)">VT</button>
        </span>
      </span>
    </div>

    <!-- 签名状态 -->
    <div class="esc-row" v-if="event.evidence?.is_signed !== undefined">
      <span class="esc-label">签名状态</span>
      <span class="esc-value">
        <span v-if="event.evidence.is_signed" class="esc-signed esc-signed-yes">已签名</span>
        <span v-else class="esc-signed esc-signed-no">未签名</span>
      </span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  event: { type: Object, default: () => ({}) },
  frequency: { type: Object, default: null },
})

const emit = defineEmits(['filter-by-host'])

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

function eventTypeLabel(t) {
  return EVENT_TYPE_LABELS[t] || t
}

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function copyHash(hash) {
  navigator.clipboard?.writeText(hash).catch(() => {})
}

function openVT(hash) {
  window.open(`https://www.virustotal.com/gui/file/${hash}`, '_blank')
}

function onFilterByHost() {
  if (props.event.host_id) {
    emit('filter-by-host', props.event.host_id)
  }
}
</script>

<style scoped>
.event-summary-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 12px;
}
.esc-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 16px;
  font-size: 13px;
}
.esc-row {
  display: contents;
}
.esc-label {
  color: var(--color-fg-subtle);
  font-size: 11px;
  padding-top: 2px;
  white-space: nowrap;
}
.esc-value {
  color: var(--color-fg-default);
  word-break: break-all;
}
.esc-sub {
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.esc-ip {
  font-family: 'Courier New', monospace;
  font-size: 12px;
}
.esc-mono {
  font-family: 'Courier New', monospace;
  font-size: 12px;
}
.esc-host-link {
  color: var(--color-accent-fg);
  cursor: pointer;
  text-decoration: underline;
}
.esc-host-link:hover {
  opacity: 0.8;
}
.esc-freq {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 0.5px solid var(--color-border-default);
  font-size: 12px;
}
.esc-freq-label {
  display: block;
  font-size: 11px;
  color: var(--color-fg-subtle);
  margin-bottom: 4px;
}
.esc-freq-value {
  color: var(--color-fg-default);
  line-height: 1.5;
}
.freq-highlight {
  color: #dc2626;
  font-weight: 600;
}
.hash-with-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.hash-val {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.hash-act-btn {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 500;
  border-radius: 3px;
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-subtle);
  color: var(--color-accent-fg);
  cursor: pointer;
  line-height: 1.4;
}
.hash-act-btn:hover {
  background: var(--color-accent-subtle);
}
.esc-signed {
  padding: 0 6px;
  border-radius: 3px;
  font-size: 12px;
}
.esc-signed-yes {
  background: var(--color-success-subtle);
  color: var(--color-success-fg);
}
.esc-signed-no {
  background: var(--color-danger-subtle);
  color: var(--color-danger-fg);
}
</style>
