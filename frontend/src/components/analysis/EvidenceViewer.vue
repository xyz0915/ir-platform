<template>
  <div class="evidence-viewer">
    <div class="ev-header">
      <span class="ev-title">证据详情</span>
      <button class="ev-toggle" @click="toggleMode">
        {{ mode === 'normalized' ? '切换原始数据 →' : '← 切换范式化视图' }}
      </button>
    </div>

    <!-- 范式化视图 -->
    <div class="ev-body" v-if="mode === 'normalized' && evidenceViews">
      <div class="ev-normalized-content">
        <template v-for="(val, key) in normalizedFields" :key="key">
          <span class="ev-norm-key">{{ key }}</span>
          <span class="ev-norm-val" :class="{ 'ev-norm-danger': val === 'false' || val === false || val === '异常', 'ev-norm-muted': !val || val === '(empty)' || val === '—' }">{{ val === '—' || val === null || val === undefined ? '(empty)' : val }}</span>
        </template>
      </div>
    </div>

    <!-- 范式化视图 - fallback -->
    <div class="ev-body" v-else-if="mode === 'normalized' && !evidenceViews">
      <div class="ev-normalized-content">
        <span class="ev-norm-key">process_name</span><span class="ev-norm-val">LsaIso.exe</span>
        <span class="ev-norm-key">pid</span><span class="ev-norm-val">1088</span>
        <span class="ev-norm-key">ppid</span><span class="ev-norm-val">600</span>
        <span class="ev-norm-key">command_line</span><span class="ev-norm-val ev-norm-muted">(empty)</span>
        <span class="ev-norm-key">is_signed</span><span class="ev-norm-val ev-norm-danger">false ← 异常</span>
        <span class="ev-norm-key">parent_name</span><span class="ev-norm-val ev-norm-muted">(session manager)</span>
        <span class="ev-norm-key">session</span><span class="ev-norm-val">1</span>
        <span class="ev-norm-key">host</span><span class="ev-norm-val">DESKTOP-NCR4EED (192.168.1.108)</span>
      </div>
    </div>

    <!-- 原始数据视图 -->
    <div class="ev-body" v-else-if="mode === 'raw'">
      <div class="ev-raw-src" v-if="evidenceViews">来源: {{ evidenceViews.raw_source || 'event' }}</div>
      <div class="ev-raw-src" v-else>来源: event</div>
      <pre class="ev-json">{{ rawJsonContent }}</pre>
    </div>

    <!-- 自适应主体：进程主体 -->
    <div class="ev-adaptive" v-if="processSubject">
      <div class="ev-sub-title">进程主体</div>
      <div class="ev-sub-grid">
        <template v-for="(val, key) in processSubject" :key="key">
          <div class="ev-sub-row" v-if="val && val !== '—'">
            <span class="ev-sub-key">{{ key }}</span>
            <span class="ev-sub-val">{{ val }}</span>
          </div>
        </template>
      </div>
    </div>

    <!-- 自适应主体：网络主体 -->
    <div class="ev-adaptive" v-if="networkSubject">
      <div class="ev-sub-title">网络主体</div>
      <div class="ev-sub-grid">
        <template v-for="(val, key) in networkSubject" :key="key">
          <div class="ev-sub-row" v-if="val && val !== '—'">
            <span class="ev-sub-key">{{ key }}</span>
            <span class="ev-sub-val">{{ val }}</span>
          </div>
        </template>
      </div>
    </div>

    <!-- 自适应主体：持久化落点 -->
    <div class="ev-adaptive" v-if="persistenceTarget">
      <div class="ev-sub-title">持久化落点</div>
      <div class="ev-sub-val">{{ persistenceTarget }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  evidenceViews: { type: Object, default: null },
  eventType: { type: String, default: '' },
  processSubject: { type: Object, default: null },
  networkSubject: { type: Object, default: null },
  persistenceTarget: { type: String, default: '' },
})

const mode = ref('normalized')

const normalizedFields = computed(() => {
  if (!props.evidenceViews?.normalized) return null
  return props.evidenceViews.normalized
})

const rawJsonContent = computed(() => {
  if (props.evidenceViews?.raw) {
    return formatJson(props.evidenceViews.raw)
  }
  return JSON.stringify({
    process_name: "LsaIso.exe",
    pid: 1088,
    ppid: 600,
    command_line: null,
    is_signed: false,
    parent_name: "Session Manager",
    session: 1,
    host: "DESKTOP-NCR4EED",
    ip_address: "192.168.1.108"
  }, null, 2)
})

function toggleMode() {
  mode.value = mode.value === 'normalized' ? 'raw' : 'normalized'
}

function formatJson(obj) {
  if (!obj) return '{}'
  try { return JSON.stringify(obj, null, 2) }
  catch { return String(obj) }
}
</script>

<style scoped>
.evidence-viewer {
  background: var(--color-canvas-default);
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.ev-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.ev-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
}
.ev-toggle {
  font-size: 11px;
  padding: 4px 10px;
  border: 0.5px solid #e5e5e7;
  border-radius: 4px;
  background: #f8f8fa;
  color: #185FA5;
  cursor: pointer;
}
.ev-toggle:hover {
  background: #E6F1FB;
}
.ev-body {
  background: #fafafa;
  border: 0.5px solid #e5e5e7;
  border-radius: 6px;
  max-height: 400px;
  overflow: auto;
}
.ev-normalized-content {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 16px;
  padding: 12px;
  font-size: 12px;
  font-family: "SF Mono", "JetBrains Mono", "Cascadia Code", monospace;
  line-height: 1.8;
}
.ev-norm-key {
  color: #185FA5;
  white-space: nowrap;
}
.ev-norm-val {
  color: #1d1d1f;
  word-break: break-all;
}
.ev-norm-danger {
  color: #A32D2D;
}
.ev-norm-muted {
  color: #b4b2a9;
}
.ev-json {
  margin: 0;
  padding: 10px;
  font-size: 11px;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-fg-default);
}
.ev-raw-src {
  font-size: 10px;
  color: #b4b2a9;
  padding: 6px 10px 0;
}
.ev-adaptive {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 0.5px solid #e5e5e7;
}
.ev-sub-title {
  font-size: 11px;
  font-weight: 500;
  color: #888780;
  margin-bottom: 8px;
}
.ev-sub-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  font-size: 12px;
}
.ev-sub-row {
  display: contents;
}
.ev-sub-key {
  color: #888780;
  font-family: 'Courier New', monospace;
  font-size: 11px;
  white-space: nowrap;
}
.ev-sub-val {
  color: var(--color-fg-default);
  word-break: break-all;
}
</style>
