<template>
  <div class="summary-card">
    <div class="summary-header">调查摘要</div>
    <div v-if="summary.generated_at" class="summary-body">
      <div class="summary-field"><span class="sf-label">目的</span><span class="sf-value">{{ summary.purpose }}</span></div>
      <div class="summary-field"><span class="sf-label">覆盖</span><span class="sf-value">{{ summary.coverage?.queries || 0 }} 次查询 · {{ summary.coverage?.alerts_reviewed || 0 }} 条告警 · {{ summary.coverage?.hosts_involved || 0 }} 台主机</span></div>
      <div class="summary-field"><span class="sf-label">发现</span><span class="sf-value">{{ summary.key_findings?.join('; ') || '无' }}</span></div>
      <div class="summary-field"><span class="sf-label">操作</span><span class="sf-value">{{ summary.actions_taken?.length || 0 }} 项</span></div>
    </div>
    <div v-else class="summary-placeholder">开始查询后自动生成摘要</div>
  </div>
</template>

<script setup>
defineProps({ summary: { type: Object, default: () => ({}) } })
</script>

<style scoped>
.summary-card { background: var(--color-accent-subtle, #eff6ff); border: 0.5px solid var(--color-border-info, #b3d4ff); border-radius: 8px; padding: 10px 12px; }
.summary-header { font-size: 12px; font-weight: 500; color: var(--color-accent-fg, #2563eb); margin-bottom: 6px; }
.summary-body { display: flex; flex-direction: column; gap: 4px; }
.summary-field { display: flex; gap: 6px; font-size: 11px; line-height: 1.5; }
.sf-label { color: var(--color-fg-subtle, #888); min-width: 32px; flex-shrink: 0; }
.sf-value { color: var(--color-fg-default, #111); }
.summary-placeholder { font-size: 11px; color: var(--color-fg-subtle, #888); text-align: center; padding: 8px 0; }
</style>
