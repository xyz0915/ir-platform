<template>
  <div class="host-overview" v-if="hostStats">
    <div class="ho-title">主机概览 — {{ hostname }}</div>
    <div class="ho-stat-grid">
      <div class="ho-stat">
        <div class="ho-stat-val">{{ hostStats.total_24h || 0 }}</div>
        <div class="ho-stat-lbl">24h 事件</div>
      </div>
      <div class="ho-stat">
        <div class="ho-stat-val ho-stat-warning">{{ hostStats.matched_24h || 0 }}</div>
        <div class="ho-stat-lbl">规则命中</div>
      </div>
      <div class="ho-stat">
        <div class="ho-stat-val ho-stat-danger">{{ hostStats.active_alerts || 0 }}</div>
        <div class="ho-stat-lbl">活跃告警</div>
      </div>
    </div>
    <!-- 上次处置记录 -->
    <div class="ho-last-disp" v-if="hostStats.last_disposition">
      上次处置: {{ hostStats.last_disposition.at }} · {{ hostStats.last_disposition.operator }} — "{{ hostStats.last_disposition.comment }}"
    </div>
  </div>
</template>

<script setup>
defineProps({
  hostStats: { type: Object, default: null },
  hostname: { type: String, default: '' },
})
</script>

<style scoped>
.host-overview {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 10px;
}
.ho-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 10px;
}
.ho-stat-grid {
  display: flex;
  gap: 8px;
}
.ho-stat {
  flex: 1;
  text-align: center;
  padding: 8px;
  background: var(--color-canvas-inset);
  border-radius: 6px;
  border: 0.5px solid var(--color-border-default);
}
.ho-stat-val {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
}
.ho-stat-warning {
  color: var(--color-risk-medium, #d97706);
}
.ho-stat-danger {
  color: var(--color-risk-critical, #dc2626);
}
.ho-stat-lbl {
  font-size: 10px;
  color: var(--color-fg-subtle);
  margin-top: 2px;
}
.ho-last-disp {
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-fg-subtle);
  line-height: 1.5;
}
</style>
