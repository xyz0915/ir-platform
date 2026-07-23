<template>
  <div class="remediation-suggestions">
    <div class="rs-title">处置建议</div>
    <div class="rs-text">
      <template v-if="severity === 'critical' || severity === 'high'">
        建议立即隔离受感染主机，终止可疑进程，并收集完整的取证数据。
      </template>
      <template v-else-if="severity === 'medium'">
        建议确认进程/网络行为是否为正常业务操作，可查询历史基线。
      </template>
      <template v-else>
        信息性事件，可归档记录，无需立即处置。
      </template>
    </div>
  </div>
</template>

<script setup>
defineProps({
  severity: { type: String, default: 'info' },
})
</script>

<style scoped>
.remediation-suggestions {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 10px;
}
.rs-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 8px;
}
.rs-text {
  font-size: 13px;
  color: var(--color-fg-muted);
  line-height: 1.6;
}
</style>
