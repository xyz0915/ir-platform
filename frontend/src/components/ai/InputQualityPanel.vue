<template>
  <div class="panel">
    <div class="panel-header">输入质量评估</div>
    <div class="score-row">
      <el-progress :percentage="quality.score || 0" :status="progressStatus" />
      <el-tag size="small" :type="tagType">{{ quality.level || 'unknown' }}</el-tag>
    </div>
    <div class="summary">{{ quality.summary || '暂无输入质量说明' }}</div>
    <div v-if="evidenceCountEntries.length" class="counts">
      <div v-for="item in evidenceCountEntries" :key="item.key" class="count-item">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </div>
    <div v-if="suggestions.length" class="suggestions">
      <div class="sub-title">补充建议</div>
      <ul>
        <li v-for="(item, index) in suggestions" :key="index">{{ item.suggestion || item }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  quality: { type: Object, default: () => ({}) },
  suggestions: { type: Array, default: () => [] },
})

const evidenceCountEntries = computed(() => {
  const counts = props.quality?.evidence_counts || {}
  const labelMap = {
    ioc_hits: 'IOC',
    abnormal_processes: '异常进程',
    suspicious_connections: '可疑外连',
    timeline_events: '时间线',
    persistence_items: '持久化',
  }
  return Object.keys(counts).map((key) => ({ key, label: labelMap[key] || key, value: counts[key] }))
})

const tagType = computed(() => {
  const level = props.quality?.level
  if (level === 'high') return 'success'
  if (level === 'medium') return 'warning'
  return 'danger'
})

const progressStatus = computed(() => {
  const score = props.quality?.score || 0
  if (score >= 85) return 'success'
  if (score >= 65) return 'warning'
  return 'exception'
})
</script>

<style scoped>
.panel { padding: 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fff; }
.panel-header { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 10px; }
.score-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.summary { font-size: 13px; color: #606266; line-height: 1.7; }
.counts { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 12px; }
.count-item { display: flex; justify-content: space-between; background: #f7f9fc; padding: 8px 10px; border-radius: 6px; font-size: 12px; }
.suggestions { margin-top: 12px; font-size: 12px; color: #606266; }
.sub-title { font-weight: 600; margin-bottom: 6px; }
.suggestions ul { margin: 0; padding-left: 18px; line-height: 1.7; }
</style>
