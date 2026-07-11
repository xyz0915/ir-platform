<template>
  <div class="timeline-compare">
    <div class="compare-controls">
      <el-select
        v-model="selectedHostIds"
        multiple
        filterable
        placeholder="选择要对比的主机（最多 5 台）"
        style="width: 500px"
        :max="5"
        @change="fetchCompareData"
      >
        <el-option
          v-for="h in props.availableHosts"
          :key="h.id"
          :label="`${h.hostname} (ID: ${h.id})`"
          :value="h.id"
        />
      </el-select>
    </div>

    <div v-if="loading" class="compare-loading">
      <el-icon class="is-loading"><Loading /></el-icon> 加载中...
    </div>

    <div v-else-if="compareData && compareData.hosts && compareData.hosts.length > 0" ref="chartRef" class="compare-chart"></div>

    <div v-else-if="selectedHostIds.length === 0" class="compare-hint">
      请在左侧选择要对比的主机
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { Loading } from '@element-plus/icons-vue'
import analysisApi from '@/api/analysis'
import { EVENT_TYPE } from '@/constants/design-tokens.js'

const props = defineProps({
  availableHosts: { type: Array, default: () => [] },
})

const selectedHostIds = ref([])
const compareData = ref(null)
const loading = ref(false)
const chartRef = ref(null)
let chart = null

async function fetchCompareData() {
  if (selectedHostIds.value.length === 0) {
    compareData.value = null
    return
  }
  loading.value = true
  try {
    const res = await analysisApi.getCompareTimeline(selectedHostIds.value)
    compareData.value = res.data
    await nextTick()
    renderChart()
  } catch (e) {
    compareData.value = null
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartRef.value || !compareData.value) return

  if (chart) chart.dispose()
  chart = echarts.init(chartRef.value)

  const hosts = compareData.value.hosts
  if (!hosts || hosts.length === 0) return

  const yAxisData = hosts.map(h => h.hostname)
  const series = hosts.map(h => {
    const events = (h.events || [])
      .filter(e => e.timestamp)
      .map(e => ({
        name: e.description || '',
        value: [new Date(e.timestamp), e.event_type || 'other'],
        itemStyle: { color: h.color },
      }))
    return {
      name: h.hostname,
      type: 'scatter',
      data: events,
      symbolSize: 10,
      itemStyle: { color: h.color },
    }
  })

  chart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: function (params) {
        return `<b>${params.seriesName}</b><br/>${params.data.name}<br/>时间: ${params.data.value[0] ? new Date(params.data.value[0]).toLocaleString() : '-'}`
      },
    },
    legend: { data: yAxisData, top: 10 },
    grid: { left: '15%', right: '4%', bottom: 80, top: 40, containLabel: true },
    xAxis: { type: 'time' },
    yAxis: {
      type: 'category',
      data: yAxisData,
      axisLabel: { interval: 0 },
    },
    dataZoom: [
      { type: 'slider', bottom: 10, height: 20 },
      { type: 'inside' },
    ],
    series: series,
  }, true)
}

watch(() => selectedHostIds.value, () => {
  if (selectedHostIds.value.length === 0 && chart) {
    chart.dispose()
    chart = null
    compareData.value = null
  }
})
</script>

<style scoped>
.timeline-compare {
  padding: 16px 0;
}
.compare-controls {
  margin-bottom: 16px;
}
.compare-chart {
  width: 100%;
  height: 500px;
}
.compare-loading {
  text-align: center;
  padding: 60px 0;
  color: #909399;
}
.compare-hint {
  text-align: center;
  padding: 60px 0;
  color: #c0c4cc;
  font-size: 14px;
}
</style>
