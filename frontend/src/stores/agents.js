/**
 * 多智能体编排运行时 Store（P0-A）。
 *
 * 职责：集中缓存「运行列表 / 当前运行详情 / 待审批列表」，并对外暴露
 * 拉取、启动、审批等动作，供 AgentRunView 与 HitlApprovalPanel 复用。
 * 仅做数据编排，不含任何副作用式 UI 逻辑。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  createAgentRun,
  listAgentRuns,
  getAgentRun,
  approveAgentRun,
  rejectAgentRun,
  listPendingApprovals,
} from '@/api/agentOrchestration'

export const useAgentOrchestrationStore = defineStore('agentOrchestration', () => {
  // ===== 状态 =====
  const runs = ref([]) // 运行列表
  const total = ref(0)
  const currentRun = ref(null) // { run, steps }
  const approvals = ref([]) // 待审批列表
  const loading = ref(false)
  const submitting = ref(false)

  // ===== 派生 =====
  const isLoading = computed(() => loading.value)
  const pendingCount = computed(() => approvals.value.length)

  // ===== 动作 =====
  /**
   * 加载运行列表（分页 + 状态/优先级过滤）。
   * @param {{status?:string, priority?:string, page?:number, page_size?:number}} params
   */
  async function fetchRuns(params = {}) {
    loading.value = true
    try {
      const res = await listAgentRuns(params)
      const data = res.data || {}
      runs.value = data.items || []
      total.value = data.total || 0
    } finally {
      loading.value = false
    }
  }

  /**
   * 加载单次运行详情。
   * @param {string} runId
   */
  async function fetchRunDetail(runId) {
    loading.value = true
    try {
      const res = await getAgentRun(runId)
      currentRun.value = res.data || null
    } finally {
      loading.value = false
    }
  }

  /**
   * 启动一次编排闭环。
   * @param {{event_id?:string, event_ids?:string[], case_id?:number}} payload
   * @returns {Promise<object>} 后端 outcome
   */
  async function startRun(payload = {}) {
    submitting.value = true
    try {
      const res = await createAgentRun(payload)
      return res.data
    } finally {
      submitting.value = false
    }
  }

  /**
   * 加载待审批列表（管理员）。
   */
  async function fetchApprovals() {
    loading.value = true
    try {
      const res = await listPendingApprovals('pending')
      // 后端返回 {items, total}，HitlApprovalPanel 需要数组
      approvals.value = (res.data && res.data.items) || []
    } finally {
      loading.value = false
    }
  }

  /**
   * HITL 批准。
   * @param {string} runId
   * @param {number} approvalId
   * @returns {Promise<object>}
   */
  async function approve(runId, approvalId) {
    submitting.value = true
    try {
      const res = await approveAgentRun(runId, { approval_id: approvalId })
      return res.data
    } finally {
      submitting.value = false
    }
  }

  /**
   * HITL 拒绝。
   * @param {string} runId
   * @param {number} approvalId
   * @param {string} [reason]
   * @returns {Promise<object>}
   */
  async function reject(runId, approvalId, reason) {
    submitting.value = true
    try {
      const res = await rejectAgentRun(runId, { approval_id: approvalId, reason })
      return res.data
    } finally {
      submitting.value = false
    }
  }

  /** 清空当前运行详情（切换视图时调用）。 */
  function clearCurrent() {
    currentRun.value = null
  }

  return {
    // state
    runs,
    total,
    currentRun,
    approvals,
    loading,
    submitting,
    // getters
    isLoading,
    pendingCount,
    // actions
    fetchRuns,
    fetchRunDetail,
    startRun,
    fetchApprovals,
    approve,
    reject,
    clearCurrent,
  }
})
