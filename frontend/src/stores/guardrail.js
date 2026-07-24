/**
 * 护栏与安全 Store（M7）。
 *
 * 职责：管理护栏策略（GuardrailPolicy）的 CRUD、评估（evaluate）与命中记录（GuardrailHit）。
 * 当前全部经 agentApi.guardrail 走 Mock（F8 后端未建），后端就绪仅切换 USE_MOCK 开关。
 *
 * 设计依据：01-api-spec.md §7 / T6。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'
import { SEVERITY_LABELS } from '@/constants/agentLabels'

export const useGuardrailStore = defineStore('guardrail', () => {
  // ===== 状态 =====
  const policies = ref([]) // GuardrailPolicy[]
  const hits = ref([]) // GuardrailHit[]
  const loading = ref(false)
  const submitting = ref(false)
  const lastResult = ref(null) // 最近一次 evaluate 结果（供评估抽屉展示）

  // ===== 派生 =====
  const enabledCount = computed(() => policies.value.filter((p) => p.enabled).length)
  const blockedCount = computed(() => hits.value.filter((h) => !h.passed).length)

  /** 严重级别 → 中文标签 */
  const riskLabel = (level) => SEVERITY_LABELS[level] || level || '—'

  // ===== 动作 =====
  /** 加载策略列表 */
  async function fetchPolicies() {
    loading.value = true
    try {
      const res = await agentApi.guardrail.listPolicies()
      policies.value = res.data || []
    } finally {
      loading.value = false
    }
  }

  /** 加载命中记录（M1 拦截数来源） */
  async function fetchHits() {
    try {
      const res = await agentApi.guardrail.listHits()
      hits.value = res.data || []
    } catch (e) {
      console.error('[guardrail] fetchHits failed:', e)
    }
  }

  /** 新增策略 */
  async function createPolicy(policy) {
    submitting.value = true
    try {
      const res = await agentApi.guardrail.createPolicy(policy)
      const created = res.data
      // 会话内即时反映（Mock 内存态）
      const idx = policies.value.findIndex((p) => p.policy_id === created.policy_id)
      if (idx >= 0) policies.value[idx] = created
      else policies.value.push(created)
      return created
    } finally {
      submitting.value = false
    }
  }

  /** 更新策略 */
  async function updatePolicy(policy) {
    submitting.value = true
    try {
      const res = await agentApi.guardrail.updatePolicy(policy)
      const updated = res.data
      const idx = policies.value.findIndex((p) => p.policy_id === updated.policy_id)
      if (idx >= 0) policies.value[idx] = updated
      return updated
    } finally {
      submitting.value = false
    }
  }

  /** 删除策略 */
  async function deletePolicy(policyId) {
    submitting.value = true
    try {
      await agentApi.guardrail.deletePolicy(policyId)
      policies.value = policies.value.filter((p) => p.policy_id !== policyId)
    } finally {
      submitting.value = false
    }
  }

  /**
   * 评估某个动作是否通过护栏（热插拔：当前 Mock，后端就绪零改动）。
   * @param {string} action
   * @param {Record<string, unknown>} [ctx]
   * @returns {Promise<object>} GuardrailResult
   */
  async function evaluate(action, ctx) {
    submitting.value = true
    try {
      const res = await agentApi.guardrail.evaluate(action, ctx)
      lastResult.value = res.data
      // 重新拉取命中记录，保证 M1 拦截数实时性
      await fetchHits()
      return res.data
    } finally {
      submitting.value = false
    }
  }

  return {
    // state
    policies,
    hits,
    loading,
    submitting,
    lastResult,
    // getters
    enabledCount,
    blockedCount,
    riskLabel,
    // actions
    fetchPolicies,
    fetchHits,
    createPolicy,
    updatePolicy,
    deletePolicy,
    evaluate,
  }
})
