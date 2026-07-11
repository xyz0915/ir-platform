<template>
  <div class="token-chart">
    <!-- 周期切换 -->
    <div class="chart-controls mb-15">
      <span class="chart-label">Token 消耗趋势：</span>
      <el-radio-group v-model="period" @change="loadData" size="small">
        <el-radio-button value="daily">日</el-radio-button>
        <el-radio-button value="weekly">周</el-radio-button>
        <el-radio-button value="monthly">月</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 图表区域 -->
    <div class="chart-container" v-loading="loading">
      <v-chart
        v-if="chartOption"
        :option="chartOption"
        autoresize
        class="echart-instance"
      />
      <el-empty v-else description="暂无统计数据" :image-size="80" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import VChart from 'vue-echarts'
import 'echarts'
import { getAiTokenStats } from '@/api/ai'

// ============================================================
// State
// ============================================================
const period = ref('daily')
const loading = ref(false)
const chartOption = ref(null)

// ============================================================
// Lifecycle
// ============================================================
onMounted(() => {
  loadData()
})

// ============================================================
// Data Loading
// ============================================================
async function loadData() {
  loading.value = true
  try {
    // 后端仅支持 days 参数；将周期映射为天数
    const daysMap = { daily: 30, weekly: 90, monthly: 365 }
    const days = daysMap[period.value] || 30
    const res = await getAiTokenStats({ days })
    const raw = res.data
    // 兼容多种后端返回格式
    let data = raw
    if (raw?.items) data = raw.items
    else if (raw?.list) data = raw.list
    else if (!Array.isArray(raw) && raw?.data) data = raw.data

    buildChartOption(Array.isArray(data) ? data : [])
  } catch {
    chartOption.value = null
  } finally {
    loading.value = false
  }
}

// ============================================================
// Chart Building
// ============================================================
function buildChartOption(data) {
  if (!Array.isArray(data) || data.length === 0) {
    chartOption.value = null
    return
  }

  const xData = data.map((d) => d.period || d.date || d.day || d.week || d.month || '')
  const tokenData = data.map((d) => d.tokens || d.total_tokens || d.token_count || 0)
  const callData = data.map((d) => d.calls || d.total_calls || d.call_count || d.count || 0)

  chartOption.value = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params]
        let tip = `<div style="font-weight:600;margin-bottom:4px;">${items[0]?.axisValue || ''}</div>`
        items.forEach((item) => {
          const color = item.color || '#333'
          tip += `<div><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;"></span>${item.seriesName}: <strong>${Number(item.value).toLocaleString()}</strong></div>`
        })
        return tip
      },
    },
    legend: {
      data: ['Token 消耗', '调用次数'],
      bottom: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '40px',
      top: '10px',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: xData,
      boundaryGap: false,
      axisLabel: {
        rotate: xData.length > 10 ? 45 : 0,
      },
    },
    yAxis: [
      {
        type: 'value',
        name: 'Token',
        axisLabel: {
          formatter: (v) => formatLargeNumber(v),
        },
      },
      {
        type: 'value',
        name: '次数',
        axisLabel: {
          formatter: '{value}',
        },
      },
    ],
    series: [
      {
        name: 'Token 消耗',
        type: 'line',
        data: tokenData,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: '#378ADD', width: 2 },
        itemStyle: { color: '#378ADD' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(55,138,221,0.3)' },
              { offset: 1, color: 'rgba(55,138,221,0.05)' },
            ],
          },
        },
      },
      {
        name: '调用次数',
        type: 'line',
        yAxisIndex: 1,
        data: callData,
        smooth: true,
        symbol: 'diamond',
        symbolSize: 6,
        lineStyle: { color: '#639922', width: 2 },
        itemStyle: { color: '#639922' },
      },
    ],
  }
}

// ============================================================
// Helpers
// ============================================================
function formatLargeNumber(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}
</script>

<style scoped>
.token-chart {
  width: 100%;
}

.chart-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chart-label {
  font-size: 14px;
  color: #606266;
}

.chart-container {
  min-height: 300px;
}

.echart-instance {
  width: 100%;
  height: 340px;
}

.mb-15 {
  margin-bottom: 15px;
}
</style>
