<template>
  <div class="metrics">
    <div class="metric">
      <div class="metric-top">
        <span class="metric-dot blue"></span>
        <span class="metric-lbl">事件总数</span>
      </div>
      <div class="metric-val">{{ stats.totalEvents }}</div>
      <div class="metric-sub">当前筛选范围内</div>
    </div>
    <div class="metric">
      <div class="metric-top">
        <span class="metric-dot red"></span>
        <span class="metric-lbl">已匹配规则</span>
      </div>
      <div class="metric-val">{{ stats.matchedEvents }}</div>
      <div class="metric-sub">命中 {{ stats.distinctRulesHit }} 条检测规则</div>
    </div>
    <div class="metric">
      <div class="metric-top">
        <span class="metric-dot gray"></span>
        <span class="metric-lbl">未匹配规则</span>
      </div>
      <div class="metric-val">{{ stats.unmatchedEvents }}</div>
      <div class="metric-sub">基线行为 · 可切换查看</div>
    </div>
    <div class="metric">
      <div class="metric-top">
        <span class="metric-dot amber"></span>
        <span class="metric-lbl">今日新增</span>
      </div>
      <div class="metric-val">{{ stats.todayNew }}</div>
      <div class="metric-sub">过去 24 小时 · 已规则匹配 {{ stats.todayMatched }} 条</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  stats: { type: Object, default: () => ({
    totalEvents: 0, matchedEvents: 0, unmatchedEvents: 0,
    distinctRulesHit: 0, todayNew: 0, todayMatched: 0,
  })},
})
</script>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.metric {
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-top {
  display: flex;
  align-items: center;
  gap: 6px;
}
.metric-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.metric-dot.blue { background: var(--color-accent-fg, #2563eb); }
.metric-dot.red { background: var(--color-danger-fg, #dc2626); }
.metric-dot.gray { background: var(--color-fg-light, #a3a3a3); }
.metric-dot.amber { background: var(--color-warning-fg, #d97706); }
.metric-lbl {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
}
.metric-val {
  font-size: 24px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}
.metric-sub {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
}
</style>
