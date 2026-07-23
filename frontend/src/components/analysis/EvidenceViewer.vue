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
      <pre class="ev-json">{{ formatJson(evidenceViews.normalized) }}</pre>
    </div>

    <!-- 原始数据视图 -->
    <div class="ev-body" v-else-if="mode === 'raw' && evidenceViews">
      <div class="ev-raw-src">来源: {{ evidenceViews.raw_source }}</div>
      <pre class="ev-json">{{ formatJson(evidenceViews.raw) }}</pre>
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

    <!-- 空状态 -->
    <div class="ev-empty" v-if="!evidenceViews && !processSubject && !networkSubject && !persistenceTarget">
      暂无证据数据
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  evidenceViews: { type: Object, default: null },
  eventType: { type: String, default: '' },
  processSubject: { type: Object, default: null },
  networkSubject: { type: Object, default: null },
  persistenceTarget: { type: String, default: '' },
})

const mode = ref('normalized')

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
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 12px;
}
.ev-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.ev-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
}
.ev-toggle {
  font-size: 10px;
  padding: 2px 8px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  background: var(--color-canvas-subtle);
  color: var(--color-accent-fg);
  cursor: pointer;
}
.ev-toggle:hover {
  background: var(--color-accent-subtle);
}
.ev-body {
  background: var(--color-canvas-inset);
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  max-height: 400px;
  overflow: auto;
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
  color: var(--color-fg-light);
  padding: 6px 10px 0;
}
.ev-adaptive {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 0.5px solid var(--color-border-default);
}
.ev-sub-title {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle);
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
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
  font-size: 11px;
  white-space: nowrap;
}
.ev-sub-val {
  color: var(--color-fg-default);
  word-break: break-all;
}
.ev-empty {
  padding: 12px;
  text-align: center;
  font-size: 12px;
  color: var(--color-fg-light);
}
</style>
