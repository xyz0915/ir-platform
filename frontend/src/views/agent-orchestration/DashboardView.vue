<template>
  <div class="dashboard-view">
    <!-- 顶部工具栏：更新时间 + 刷新（页面标题由 AgentOrchestrationLayout 提供） -->
    <div class="dv-toolbar">
      <span v-if="store.lastUpdated" class="dv-updated">更新于 {{ relativeTime(store.lastUpdated) }}</span>
      <el-button :loading="store.loading" @click="store.fetchStats()">刷新</el-button>
    </div>

    <!-- 指标卡：主色 #111827，单色等宽数值，无彩色强调 -->
    <div class="dv-stats">
      <div class="dv-stat">
        <span class="dv-stat-label">运行中智能体</span>
        <span class="dv-stat-value">{{ store.stats.running_agents }}</span>
      </div>
      <div class="dv-stat">
        <span class="dv-stat-label">成功率</span>
        <span class="dv-stat-value">{{ store.stats.success_rate }}%</span>
      </div>
      <div class="dv-stat">
        <span class="dv-stat-label">待审 HITL</span>
        <span class="dv-stat-value">{{ store.stats.pending_hitl }}</span>
      </div>
      <div class="dv-stat">
        <span class="dv-stat-label">护栏拦截</span>
        <span class="dv-stat-value">{{ store.stats.guardrail_blocks }}</span>
      </div>
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
            <el-table-column prop="status" label="状态" width="110">
              <template #default="{ row }">
                <span class="dv-status">
                  <span class="dv-status-dot" :class="statusClass(row.status)" />
                  <span>{{ statusLabel(row.status) }}</span>
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" min-width="110">
              <template #default="{ row }">{{ relativeTime(row.created_at) }}</template>
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
import { useAgentDashboardStore } from '@/stores/agentDashboard'
import { formatServerTime, parseServerTime } from '@/utils/time'

const router = useRouter()
const store = useAgentDashboardStore()

const trendChartRef = ref(null)
let trendChart = null
let pollTimer = null

// ===== 趋势图（近黑配色，去彩色强调） =====
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
      axisLabel: { formatter: (v) => fmtDay(v), color: '#9ca3af', fontSize: 11 },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: {
      type: 'value',
      min: 70,
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#9ca3af', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(17,24,39,0.08)' } },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        data: data.map((d) => d.success_rate),
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 2, color: '#111827' },
        itemStyle: { color: '#111827' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(17,24,39,0.25)' },
            { offset: 1, color: 'rgba(17,24,39,0.02)' },
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

/** 状态点仅两色：运行/完成（绿 #16a34a）/ 其他（灰 #9ca3af） */
function statusClass(status) {
  return status === 'running' || status === 'completed' ? 'ok' : 'off'
}

/** 相对时间：刚刚 / X 分钟前 / X 小时前 / X 天前 */
function relativeTime(iso) {
  if (!iso) return '—'
  const t = parseServerTime(iso)
  if (!t) return String(iso)
  const diffMs = Date.now() - t.getTime()
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return '刚刚'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  return `${day} 天前`
}

function fmtDay(iso) {
  if (!iso) return ''
  return formatServerTime(iso, 'M/D') || iso
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

/* ===== 顶部工具栏 ===== */
.dv-toolbar { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-bottom: 12px; }
.dv-updated { font-size: 12px; color: var(--color-fg-subtle); }

/* ===== 指标卡（紧凑 4 卡，主色 #111827） ===== */
.dv-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.dv-stat {
  flex: 1; min-width: 150px; max-width: 240px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 6px;
  min-height: 82px; justify-content: center;
  transition: box-shadow 0.15s, border-color 0.15s;
}
.dv-stat:hover { box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05); border-color: #d1d5db; }
.dv-stat-label { font-size: 12px; font-weight: 500; color: #6b7280; }
.dv-stat-value {
  font-size: 20px; font-weight: 600; color: #111827;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  line-height: 1.2; letter-spacing: -0.3px;
}

/* ===== 主体布局 ===== */
.dv-body { display: flex; gap: 16px; align-items: flex-start; }
.dv-main { flex: 1; min-width: 0; }
.dv-side { width: 380px; flex-shrink: 0; }

/* ===== 卡片 ===== */
.dv-card { border-radius: 10px; border: 0.5px solid var(--color-border-default); }
.dv-card :deep(.el-card__header) {
  padding: 10px 14px;
  border-bottom: 0.5px solid var(--color-border-default);
}
.dv-card :deep(.el-card__body) { padding: 14px; }
.dv-h { font-size: 13px; font-weight: 600; color: #111827; }
.dv-chart { width: 100%; height: 280px; }

/* ===== 近期运行表格 ===== */
.dv-runs { cursor: pointer; border-radius: 10px; }
.dv-runs :deep(th.el-table__cell) {
  font-size: 12px; font-weight: 500; color: #6b7280;
  background: var(--color-canvas-subtle);
  padding: 8px 10px; height: 36px;
}
.dv-runs :deep(td.el-table__cell) {
  padding: 8px 10px; font-size: 12px; color: var(--color-fg-default); height: 38px;
}
.dv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.dv-status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--color-fg-default); }
.dv-status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.dv-status-dot.ok { background: #16a34a; }
.dv-status-dot.off { background: #9ca3af; }

@media (max-width: 1100px) {
  .dv-body { flex-direction: column; }
  .dv-side { width: 100%; }
}
</style>
