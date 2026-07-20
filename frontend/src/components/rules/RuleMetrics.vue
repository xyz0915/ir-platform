<template>
  <div class="metrics">
    <div class="metric">
      <div class="metric-top"><div class="metric-dot blue"></div><div class="metric-label">规则总数</div></div>
      <div class="metric-value">{{ stats?.total || rules.length }}</div>
      <div class="metric-sub">检测类别覆盖</div>
    </div>
    <div class="metric">
      <div class="metric-top"><div class="metric-dot green"></div><div class="metric-label">已启用</div></div>
      <div class="metric-value">{{ stats?.enabled || rules.filter(r => r.enabled).length }}</div>
      <div class="metric-sub up">{{ enabledPct }}% 激活率</div>
    </div>
    <div class="metric">
      <div class="metric-top"><div class="metric-dot amber"></div><div class="metric-label">中高危规则</div></div>
      <div class="metric-value">{{ (stats?.high_risk || 0) + (stats?.medium_risk || 0) }}</div>
      <div class="metric-sub">需关注</div>
    </div>
    <div class="metric">
      <div class="metric-top"><div class="metric-dot red"></div><div class="metric-label">用户规则</div></div>
      <div class="metric-value">{{ stats?.user_rules || rules.filter(r => r.source !== 'default').length }}</div>
      <div class="metric-sub up">自定义</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ stats: { type: Object, default: null }, rules: { type: Array, default: () => [] } })
const enabledPct = computed(() => {
  const total = props.stats?.total || props.rules.length
  const en = props.stats?.enabled || props.rules.filter(r => r.enabled).length
  return total ? Math.round(en / total * 100) : 0
})
</script>
