/**
 * 规则管理 Pinia Store（P0-#1）.
 * 统一管理规则列表、统计、覆盖率和 CRUD 状态.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listRules, getRuleStats, getRuleCoverage,
  createRule, updateRule, deleteRule, bulkEnableRules,
} from '@/api/rules'

export const useRulesStore = defineStore('rules', () => {
  // ── state ──
  const rules = ref([])
  const loading = ref(false)
  const stats = ref(null)
  const coverage = ref(null)
  const categories = ref([])
  const error = ref(null)

  // ── getters ──
  const enabledCount = computed(() => rules.value.filter(r => r.enabled).length)
  const highRiskCount = computed(() =>
    rules.value.filter(r => r.severity === 'critical' || r.severity === 'high').length)

  // ── actions ──
  async function fetchRules(params = {}) {
    loading.value = true
    error.value = null
    try {
      const res = await listRules(params)
      rules.value = res.data || []
      // 从规则中提取分类列表
      categories.value = [...new Set(rules.value.map(r => r.category).filter(Boolean))]
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    try {
      const res = await getRuleStats()
      stats.value = res.data
    } catch (e) {
      // 静默失败
    }
  }

  async function fetchCoverage() {
    try {
      const res = await getRuleCoverage()
      coverage.value = res.data
    } catch (e) {
      // 静默失败
    }
  }

  async function addRule(data) {
    const res = await createRule(data)
    rules.value.unshift(res.data)
    return res.data
  }

  async function editRule(ruleId, data) {
    const res = await updateRule(ruleId, data)
    const idx = rules.value.findIndex(r => r.id === ruleId)
    if (idx >= 0) rules.value[idx] = { ...rules.value[idx], ...res.data }
    return res.data
  }

  async function removeRule(ruleId) {
    await deleteRule(ruleId)
    rules.value = rules.value.filter(r => r.id !== ruleId)
  }

  async function batchEnable(ids, enabled) {
    await bulkEnableRules({ ids, enabled })
    for (const r of rules.value) {
      if (ids.includes(r.id)) r.enabled = enabled
    }
  }

  return {
    rules, loading, stats, coverage, categories, error,
    enabledCount, highRiskCount,
    fetchRules, fetchStats, fetchCoverage,
    addRule, editRule, removeRule, batchEnable,
  }
})
