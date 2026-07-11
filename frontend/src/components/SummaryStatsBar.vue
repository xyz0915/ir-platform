<template>
  <el-row :gutter="16" class="summary-stats-bar">
    <el-col :span="4" v-for="card in cards" :key="card.key">
      <el-card shadow="hover" class="stat-card" :style="{ borderTop: `3px solid ${card.color}` }">
        <div class="stat-value" :style="{ color: card.color }">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import analysisApi from '@/api/analysis'
import { SEVERITY } from '@/constants/design-tokens.js'

const props = defineProps({
  hostId: { type: [Number, String], required: true },
  stats: { type: Object, default: null },
})

const emit = defineEmits(['stats-loaded'])

const localStats = ref({
  highCount: 0,
  mediumCount: 0,
  lowCount: 0,
  iocHitCount: 0,
  timeSpan: 0,
})

const effectiveStats = computed(() => props.stats || localStats.value)

const cards = computed(() => [
  {
    key: 'high',
    label: '高危事件',
    value: effectiveStats.value.highCount ?? 0,
    color: SEVERITY.COLOR.high,
  },
  {
    key: 'medium',
    label: '中危事件',
    value: effectiveStats.value.mediumCount ?? 0,
    color: SEVERITY.COLOR.medium,
  },
  {
    key: 'low',
    label: '低危事件',
    value: effectiveStats.value.lowCount ?? 0,
    color: SEVERITY.COLOR.low,
  },
  {
    key: 'ioc',
    label: 'IOC 命中',
    value: effectiveStats.value.iocHitCount ?? 0,
    color: SEVERITY.COLOR.critical,
  },
  {
    key: 'timespan',
    label: '时间跨度(h)',
    value: effectiveStats.value.timeSpan ?? 0,
    color: '#409EFF',
  },
])

async function fetchStats() {
  try {
    const res = await analysisApi.getTimelineStats(props.hostId)
    if (res.data) {
      localStats.value = res.data
    }
    emit('stats-loaded', localStats.value)
  } catch (e) {
    // Stats fetch failed silently
  }
}

onMounted(() => {
  if (!props.stats) {
    fetchStats()
  }
})

watch(() => props.hostId, () => {
  if (!props.stats) {
    fetchStats()
  }
})
</script>

<style scoped>
.summary-stats-bar {
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
  padding: 4px 0;
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
