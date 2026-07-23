<template>
  <div class="host-overview">
    <div class="ho-title">主机概况 {{ hostname }}</div>
    <div class="ho-stat-grid">
      <div class="ho-stat-card">
        <div class="ho-stat-num">{{ safeStat('total_24h', '2,584') }}</div>
        <div class="ho-stat-label">安全事件</div>
      </div>
      <div class="ho-stat-card">
        <div class="ho-stat-num ho-stat-danger">{{ safeStat('matched_24h', '823') }}</div>
        <div class="ho-stat-label">高危事件</div>
      </div>
      <div class="ho-stat-card">
        <div class="ho-stat-num">{{ safeStat('active_alerts', '8') }}</div>
        <div class="ho-stat-label">活跃告警</div>
      </div>
      <div class="ho-stat-card">
        <div class="ho-stat-num ho-stat-warn">{{ safeStat('resolved_today', '0') }}</div>
        <div class="ho-stat-label">今已处置</div>
      </div>
    </div>
    <!-- 上次处置记录 -->
    <div class="ho-last-disp" v-if="hostStats?.last_disposition">
      上次处置: {{ hostStats.last_disposition.at }} · {{ hostStats.last_disposition.operator }} — "{{ hostStats.last_disposition.comment }}"
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  hostStats: { type: Object, default: null },
  hostname: { type: String, default: '' },
})

function safeStat(key, fallback) {
  return props.hostStats?.[key] ?? fallback
}
</script>

<style scoped>
.host-overview {
  background: var(--color-canvas-default);
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 12px;
}
.ho-title {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 10px;
}
.ho-stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.ho-stat-card {
  padding: 10px;
  background: #f8f8fa;
  border-radius: 8px;
  text-align: center;
}
.ho-stat-num {
  font-size: 20px;
  font-weight: 500;
  color: #1d1d1f;
  line-height: 1.3;
}
.ho-stat-danger {
  color: #A32D2D;
}
.ho-stat-warn {
  color: #854F0B;
}
.ho-stat-label {
  font-size: 11px;
  color: #b4b2a9;
  margin-top: 2px;
}
.ho-last-disp {
  margin-top: 8px;
  font-size: 11px;
  color: #888780;
  line-height: 1.5;
}
</style>
