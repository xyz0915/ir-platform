<template>
  <div class="dashboard-view">
    <!-- 顶部 -->
    <div class="dv-toolbar">
      <div class="dv-title">
        <h2>编排总览</h2>
        <span class="dv-sub">前端组合聚合 · 真实运行数据 + Mock 趋势/护栏拦截</span>
      </div>
      <div class="dv-actions">
        <span v-if="store.lastUpdated" class="dv-updated">
          更新于 {{ fmtTime(store.lastUpdated) }}
        </span>
        <el-button :loading="store.loading" @click="store.fetchStats()">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <!-- 指标卡 -->
    <div class="dv-stats">
      <StatCard title="运行中智能体" :value="store.stats.running_agents" :icon="Cpu" color="#3B82F6" />
      <StatCard title="成功率" :value="store.stats.success_rate + '%'" :icon="CircleCheck" color="#22C55E" />
      <StatCard title="待审 HITL" :value="store.stats.pending_hitl" :icon="Stamp" color="#F59E0B" />
      <StatCard title="护栏拦截" :value="store.stats.guardrail_blocks" :icon="Lock" color="#EF4444" />
    </div>

    <div class="dv-body">
      <!-- 左：趋势图 -->
      <div class="dv-main">
        <el-card class="dv-card" shadow="never">
          <template #header><span class="dv-h">近 7 日成功率趋势</span></template>
          <div ref="trendChartRef" class="dv-chart"></div>
        </el-card>
      </div>

      <!-- 右：近期运行 -->
      <div class="dv-side">
        <el-card class="dv-card" shadow="never">
          <template #header>
            <span class="dv-h">近期运行 ({{ store.recentRuns.length }})</span>
          </template>
          <el-table :data="store.recentRuns" empty-text="暂无运行" size="small" @row-click="goRun" class="dv-runs">
            <el-table-column prop="run_id" label="Run ID" min-width="130">
              <template #default="{ row }"><span class="dv-mono">{{ row.run_id }}</span></template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="96">
              <template #default="{ row }">
                <el-tag :type="statusTag(row.status)" size="small" effect="light">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" min-width="150">
              <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { Cpu, CircleCheck, Stamp, Lock, Refresh } from '@element-plus/icons-vue'
import { useAgentDashboardStore } from '@/stores/agentDashboard'
import StatCard from '@/components/agents/StatCard.vue'

const router = useRouter()
const store = useAgentDashboardStore()

const trendChartRef = ref(null)
let trendChart = null
let pollTimer = null

// ===== 趋势图 =====
function renderChart() {
  if (!trendChartRef.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }
  const data = store.trend || []
  trendChart.setOption({
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis', formatter: (p) => `${fmtDay(p[0].axisValue)}<br/>成功率 ${p[0].data}%` },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.ts),
      axisLabel: { formatter: (v) => fmtDay(v), color: '#94A3B8', fontSize: 11 },
      axisLine: { lineStyle: { color: '#334155' } },
    },
    yAxis: {
      type: 'value',
      min: 70,
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#94A3B8', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(51,65,85,0.4)' } },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        data: data.map((d) => d.success_rate),
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2, color: '#3B82F6' },
        itemStyle: { color: '#3B82F6' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(59,130,246,0.35)' },
            { offset: 1, color: 'rgba(59,130,246,0.02)' },
          ]),
        },
      },
    ],
  })
  trendChart.resize()
}

function onResize() {
  trendChart && trendChart.resize()
}

// ===== 展示辅助 =====
function statusLabel(status) {
  return (
    {
      pending: '挂起',
      running: '运行中',
      waiting_hitl: '等待 HITL',
      completed: '已完成',
      failed: '失败',
      cancelled: '已取消',
    }[status] || status || '-'
  )
}
function statusTag(status) {
  return (
    {
      pending: 'info',
      running: 'primary',
      waiting_hitl: 'warning',
      completed: 'success',
      failed: 'danger',
      cancelled: 'info',
    }[status] || 'info'
  )
}
function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}
function fmtDay(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()}`
  } catch {
    return iso
  }
}
function goRun(row) {
  if (row && row.run_id) router.push(`/agent-orchestration/runs/${row.run_id}`)
}

// ===== 生命周期 =====
onMounted(async () => {
  await store.fetchStats()
  await nextTick()
  renderChart()
  window.addEventListener('resize', onResize)
  // 30s 轻量轮询（01-api-spec.md Q5）
  pollTimer = setInterval(() => {
    store.fetchStats().catch(() => {})
  }, 30000)
})

watch(
  () => store.trend,
  () => renderChart(),
  { deep: true }
)

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  window.removeEventListener('resize', onResize)
  if (trendChart) {
    trendChart.dispose()
    trendChart = null
  }
})
</script>

<style scoped>
.dashboard-view { padding: 16px; }
.dv-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.dv-title h2 { margin: 0; font-size: 18px; font-weight: 600; }
.dv-sub { display: block; font-size: 12px; color: var(--color-fg-subtle); margin-top: 2px; }
.dv-actions { display: flex; align-items: center; gap: 12px; }
.dv-updated { font-size: 12px; color: var(--color-fg-subtle); }

.dv-stats { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }

.dv-body { display: flex; gap: 16px; align-items: flex-start; }
.dv-main { flex: 1; min-width: 0; }
.dv-side { width: 380px; flex-shrink: 0; }

.dv-card { border-radius: 10px; border: 1px solid var(--color-border-default); }
.dv-h { font-size: 14px; font-weight: 500; }
.dv-chart { width: 100%; height: 280px; }
.dv-runs { cursor: pointer; }
.dv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }

@media (max-width: 1100px) {
  .dv-body { flex-direction: column; }
  .dv-side { width: 100%; }
}
</style>
