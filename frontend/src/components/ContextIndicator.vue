<template>
  <div class="context-indicator" v-if="context.hostName || context.intent">
    <div class="ci-badge">
      <span class="ci-label">当前</span>
      <span class="ci-host">{{ context.hostName }}</span>
      <span class="ci-meta" v-if="context.hostName">{{ context.hostAlertCount || 0 }} 条告警</span>
      <span class="ci-meta" v-if="context.hostName">风险 {{ context.hostRiskScore || '-' }}</span>
    </div>
    <div class="ci-actions">
      <el-button size="small" text @click="$emit('switch-host')">切换</el-button>
      <el-button size="small" text @click="$emit('pin')">{{ context.pinned ? '已固定' : '固定' }}</el-button>
      <el-button size="small" text @click="$emit('clear')">清空</el-button>
    </div>
  </div>
</template>

<script setup>
defineProps({ context: { type: Object, default: () => ({ hostName: '', hostAlertCount: 0, hostRiskScore: '', intent: '', pinned: false }) } })
defineEmits(['switch-host', 'pin', 'clear'])
</script>

<style scoped>
.context-indicator { display: flex; align-items: center; justify-content: space-between; padding: 6px 12px; background: var(--color-accent-subtle, #eff6ff); border-radius: 6px; margin-bottom: 8px; }
.ci-badge { display: flex; align-items: center; gap: 6px; }
.ci-label { font-size: 11px; color: var(--color-accent-fg, #2563eb); font-weight: 500; }
.ci-host { font-size: 13px; font-weight: 500; color: var(--color-fg-default, #111); }
.ci-meta { font-size: 11px; color: var(--color-fg-subtle, #888); }
.ci-actions { display: flex; gap: 2px; }
.ci-actions :deep(.el-button) { font-size: 11px; padding: 0 6px; height: 22px; color: var(--color-accent-fg, #2563eb); }
</style>
