<template>
  <div class="log-timeline" :class="{ mono: true }">
    <el-empty v-if="!logs.length" description="暂无日志" :image-size="50" />
    <div v-for="(log, i) in logs" :key="i" class="lt-row" :class="'lv-' + log.level">
      <span class="lt-ts">{{ shortTime(log.ts) }}</span>
      <span class="lt-level">{{ levelLabel(log.level) }}</span>
      <span class="lt-msg">{{ log.message }}</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  /** LogEntry[] */
  logs: { type: Array, default: () => [] },
})

function levelLabel(level) {
  return (
    { debug: 'DEBUG', info: 'INFO', warn: 'WARN', error: 'ERROR' }[level] || String(level || '').toUpperCase()
  )
}

function shortTime(iso) {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0')
  } catch {
    return iso || ''
  }
}
</script>

<style scoped>
.log-timeline { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.lt-row { display: flex; gap: 10px; padding: 4px 6px; border-radius: 4px; align-items: baseline; }
.lt-row:hover { background: var(--color-canvas-subtle); }
.lt-ts { color: var(--color-fg-subtle); flex-shrink: 0; }
.lt-level { font-weight: 700; flex-shrink: 0; width: 48px; }
.lt-msg { color: var(--color-fg-default); word-break: break-all; }
.lv-info .lt-level { color: #3B82F6; }
.lv-debug .lt-level { color: var(--color-fg-subtle); }
.lv-warn .lt-level { color: #F59E0B; }
.lv-error .lt-level { color: #EF4444; }
.lv-error { background: var(--color-danger-subtle, rgba(239,68,68,0.08)); }
</style>
