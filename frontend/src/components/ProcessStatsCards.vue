<template>
  <div class="process-stats-cards">
    <!-- 4个统计卡片 -->
    <el-row :gutter="16" class="mb-16">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="异常总数" :value="totalAbnormal" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card critical">
          <el-statistic title="Critical" :value="criticalCount" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card high">
          <el-statistic title="High" :value="highCount" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card avg">
          <el-statistic title="平均风险评分" :value="avgRiskScore" :precision="1" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 饼图 + 条形图 -->
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="hover">
          <div class="chart-title">严重程度分布</div>
          <v-chart :option="pieOption" autoresize style="height: 280px" />
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="hover">
          <div class="chart-title">规则类别分布</div>
          <v-chart :option="barOption" autoresize style="height: 280px" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([PieChart, BarChart, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] }
})

const totalAbnormal = computed(() => props.data.length)
const criticalCount = computed(() => props.data.filter(r => r.severity === 'critical').length)
const highCount = computed(() => props.data.filter(r => r.severity === 'high').length)
const avgRiskScore = computed(() => {
  if (!props.data.length) return 0
  const sum = props.data.reduce((acc, r) => acc + (r.risk_score || 0), 0)
  return sum / props.data.length
})

/** 严重程度分布饼图 */
const severityDistribution = computed(() => {
  const map = {}
  for (const row of props.data) {
    const sev = row.severity || 'unknown'
    map[sev] = (map[sev] || 0) + 1
  }
  return map
})

const pieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, left: 'center' },
  series: [
    {
      type: 'pie',
      radius: ['40%', '70%'],
      avoidLabelOverlap: false,
      label: { show: true, formatter: '{b}\n{c}' },
      data: Object.entries(severityDistribution.value).map(([name, value]) => ({
        name,
        value,
        itemStyle: {
          color: name === 'critical' ? '#F56C6C' : name === 'high' ? '#E6A23C' : name === 'medium' ? '#FABC6F' : name === 'low' ? '#409EFF' : '#909399'
        }
      }))
    }
  ]
}))

/** 规则类别分布条形图（按 matched_rules 的 name 统计） */
const ruleDistribution = computed(() => {
  const map = {}
  for (const row of props.data) {
    if (row.matched_rules && Array.isArray(row.matched_rules)) {
      for (const rule of row.matched_rules) {
        map[rule.name] = (map[rule.name] || 0) + 1
      }
    } else if (row.rule_name) {
      map[row.rule_name] = (map[row.rule_name] || 0) + 1
    }
  }
  // 按数量排序取前15
  return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 15)
})

const barOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 120, right: 20, top: 20, bottom: 30 },
  xAxis: { type: 'value' },
  yAxis: {
    type: 'category',
    data: ruleDistribution.value.map(([name]) => name),
    axisLabel: { width: 100, overflow: 'truncate' }
  },
  series: [
    {
      type: 'bar',
      data: ruleDistribution.value.map(([_, value]) => value),
      itemStyle: { color: '#409EFF' },
      barMaxWidth: 20,
      label: { show: true, position: 'right' }
    }
  ]
}))
</script>

<style scoped>
.mb-16 {
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
}
.stat-card.critical .el-statistic__number {
  color: #F56C6C;
}
.stat-card.high .el-statistic__number {
  color: #E6A23C;
}
.stat-card.avg .el-statistic__number {
  color: #409EFF;
}
.chart-title {
  font-weight: bold;
  margin-bottom: 8px;
  color: #303133;
}
</style>
