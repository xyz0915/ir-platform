<template>
  <div :class="['action-result-card', result.success ? 'success' : 'failed']">
    <div class="arc-header">
      <span :class="['arc-icon', result.success ? 'ok' : 'fail']">
        {{ result.success ? '✓' : '✗' }}
      </span>
      <span class="arc-action">{{ actionLabel }}</span>
    </div>
    <div class="arc-body">
      <div class="arc-row" v-for="(val, key) in result.result" :key="key">
        <span class="arc-k">{{ key }}</span>
        <span class="arc-v">{{ val }}</span>
      </div>
      <div class="arc-timing">耗时 {{ result.exec_time_ms }}ms</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({
  result: { type: Object, default: () => ({}) },
})
const actionLabel = computed(() => {
  const labels = { block_ip: '封锁 IP', isolate_host: '隔离主机', export_report: '导出报告', mark_false_positive: '标记误报', add_whitelist: '加入白名单', create_case: '创建案件', add_note: '添加笔记' }
  return labels[props.result.action] || props.result.action
})
</script>

<style scoped>
.action-result-card { border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 8px; overflow: hidden; margin-top: 8px; }
.action-result-card.success { border-color: var(--color-text-success, #16a34a); }
.action-result-card.failed { border-color: var(--color-text-danger, #dc2626); }
.arc-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; font-size: 13px; font-weight: 500; }
.action-result-card.success .arc-header { background: var(--color-background-success, #f0fdf4); }
.action-result-card.failed .arc-header { background: var(--color-background-danger, #fef2f2); }
.arc-icon { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: #fff; }
.arc-icon.ok { background: var(--color-text-success, #16a34a); }
.arc-icon.fail { background: var(--color-text-danger, #dc2626); }
.arc-body { padding: 8px 12px; font-size: 12px; background: var(--color-canvas-default, #fff); }
.arc-row { display: flex; gap: 8px; padding: 2px 0; }
.arc-k { color: var(--color-fg-subtle, #888); min-width: 80px; }
.arc-v { color: var(--color-fg-default, #111); word-break: break-all; }
.arc-timing { font-size: 10px; color: var(--color-fg-subtle, #888); margin-top: 4px; }
</style>
