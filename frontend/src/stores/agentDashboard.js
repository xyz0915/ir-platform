/**
 * 编排总览 Dashboard Store（M1）。
 *
 * 职责：前端组合聚合 DashboardStats（01-api-spec.md §1）。
 * 真实数据源：agentApi.runs.listAgentRuns + agentApi.stats.getAgentStats；
 * Mock 数据源：agentApi.dashboard.getTrend + agentApi.dashboard.getGuardrailBlocks + agentApi.hitl.listPendingApprovals。
 * 后端 F1 收敛到聚合端点时，仅替换本 store 内部取数逻辑，组件零改动。
 *
 * 设计依据：01-api-spec.md §1 / Q5 / T7。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'

export const useAgentDashboardStore = defineStore('agentDashboard', () => {
  // ===== 状态 =====
  const loading = ref(false)
  const runs = ref([]) // 运行列表（原始）
  const statsRaw = ref(null) // /agents/stats 原始数据
  const trend = ref([]) // 近 7 日成功率
  const guardrailBlocks = ref(0) // 护栏拦截数
  const pendingHitl = ref(0) // 待审 HITL 数
  const lastUpdated = ref(null)

  // ===== 派生：DashboardStats =====
  /** 运行中智能体数 */
  const runningAgents = computed(() => {
    if (statsRaw.value && typeof statsRaw.value.running === 'number') return statsRaw.value.running
    return runs.value.filter((r) => r.status === 'running').length
  })

  /** 成功率（0-100 百分制） */
  const successRate = computed(() => {
    if (statsRaw.value && typeof statsRaw.value.success_rate === 'number') {
      return statsRaw.value.success_rate
    }
    // 兜底：从运行列表计算
    const total = runs.value.length
    if (total === 0) return 0
    const okCount = runs.value.filter((r) => r.status === 'completed').length
    return Math.round((okCount / total) * 100)
  })

  /** 近期运行（取前 6 条） */
  const recentRuns = computed(() => runs.value.slice(0, 6))

  /** 聚合后的 DashboardStats 实体 */
  const stats = computed(() => ({
    running_agents: runningAgents.value,
    success_rate: successRate.value,
    pending_hitl: pendingHitl.value,
    guardrail_blocks: guardrailBlocks.value,
    recent_runs: recentRuns.value,
    trend: trend.value,
  }))

  // ===== 动作 =====
  /**
   * 拉取并聚合总览数据（前端组合：真实 + Mock 并行）。
   * 任一 Mock 失败不影响整体渲染。
   */
  async function fetchStats() {
    loading.value = true
    try {
      const [runsRes, statsRes, trendRes, blocksRes, hitlRes] = await Promise.all([
        agentApi.runs.listAgentRuns({ page_size: 50 }),
        agentApi.stats.getAgentStats().catch(() => ({ data: null })),
        agentApi.dashboard.getTrend().catch(() => ({ data: [] })),
        agentApi.dashboard.getGuardrailBlocks().catch(() => ({ data: 0 })),
        agentApi.hitl.listPendingApprovals('pending').catch(() => ({ data: { items: [] } })),
      ])

      runs.value = (runsRes.data && runsRes.data.items) || []
      statsRaw.value = statsRes.data || null
      trend.value = trendRes.data || []
      guardrailBlocks.value = typeof blocksRes.data === 'number' ? blocksRes.data : 0
      const hitlItems = (hitlRes.data && hitlRes.data.items) || []
      pendingHitl.value = hitlItems.length

      lastUpdated.value = new Date()
    } finally {
      loading.value = false
    }
  }

  return {
    // state
    loading,
    runs,
    statsRaw,
    trend,
    guardrailBlocks,
    pendingHitl,
    lastUpdated,
    // getters
    runningAgents,
    successRate,
    recentRuns,
    stats,
    // actions
    fetchStats,
  }
})
