<template>
  <div class="panel">
    <div class="panel-header">覆盖缺口与漏检风险</div>
    <div class="risk-summary">
      <el-tag size="small" :type="riskType">{{ missRisk.level || 'low' }}</el-tag>
      <span>{{ missRisk.summary || '暂无漏检风险说明' }}</span>
    </div>
    <div v-if="blindSpots.length" class="blind-spots">
      <span class="sub-title">可能盲区：</span>
      <el-tag v-for="item in blindSpots" :key="item" size="small" effect="plain">{{ item }}</el-tag>
    </div>
    <div v-if="gaps.length" class="gap-list">
      <div v-for="(item, index) in gaps" :key="index" class="gap-item">
        <div class="gap-top">
          <strong>{{ item.title }}</strong>
          <el-tag size="small" :type="severityType(item.severity)">{{ item.severity }}</el-tag>
        </div>
        <div class="gap-desc">{{ item.description }}</div>
        <div class="gap-suggestion">建议：{{ item.suggestion }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  gaps: { type: Array, default: () => [] },
  missRisk: { type: Object, default: () => ({}) },
})

const blindSpots = computed(() => props.missRisk?.likely_blind_spots || [])
const riskType = computed(() => severityType(props.missRisk?.level))

function severityType(level) {
  if (level === 'high' || level === 'critical') return 'danger'
  if (level === 'medium') return 'warning'
  return 'info'
}
</script>

<style scoped>
.panel { padding: 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fff; }
.panel-header { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.risk-summary { display: flex; gap: 10px; align-items: center; font-size: 13px; color: #606266; }
.blind-spots { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.sub-title { font-size: 12px; color: #909399; }
.gap-list { margin-top: 12px; }
.gap-item { background: #f7f9fc; border-radius: 6px; padding: 10px; margin-bottom: 8px; }
.gap-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.gap-desc, .gap-suggestion { margin-top: 6px; font-size: 12px; color: #606266; line-height: 1.7; }
</style>
