/**
 * 默认闭环流程 Store（config-default-pipeline）。
 *
 * 职责：集中缓存「规则列表 / resolve 预览结果 / 手动覆盖 preset_id」，
 * 并对外暴露拉取、resolve 预览、CRUD 动作，供 AgentRunView（banner + 手动覆盖）
 * 与 DefaultPipelineManagePanel（管理列表）复用。仅做数据编排，不含 UI 副作用。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listDefaultRules,
  createDefaultRule,
  updateDefaultRule,
  deleteDefaultRule,
  resolveDefaultPipeline,
} from '@/api/defaultPipeline'

export const useDefaultPipelineStore = defineStore('defaultPipeline', () => {
  // ===== 状态 =====
  const rules = ref([])            // 规则列表
  const resolvePreview = ref(null) // resolve 预览结果（ResolveResult）
  const manualPresetId = ref(null) // 手动覆盖的 preset_id（P1-3，清空即回退自动匹配）
  const loading = ref(false)

  // ===== 派生 =====
  /** 是否存在全局默认规则。 */
  const hasGlobalDefault = computed(() => rules.value.some((r) => r.is_global))

  /** 场景规则（非全局）。 */
  const sceneRules = computed(() => rules.value.filter((r) => !r.is_global))

  // ===== 动作 =====

  /** 拉取规则列表。 */
  async function fetchRules() {
    loading.value = true
    try {
      const res = await listDefaultRules()
      rules.value = res.data || []
    } finally {
      loading.value = false
    }
  }

  /**
   * 触发 resolve 预览（运行页 banner）。
   * @param {string} [eventId]
   * @param {{category?:string, priority?:string}} [extra] 显式覆盖条件
   */
  async function resolve(eventId, extra = {}) {
    const params = { event_id: eventId || undefined, ...extra }
    const res = await resolveDefaultPipeline(params)
    resolvePreview.value = res.data || null
    return res.data
  }

  /** 新建规则。 */
  async function createRule(payload) {
    const res = await createDefaultRule(payload)
    await fetchRules()
    return res.data
  }

  /** 编辑规则。 */
  async function updateRule(ruleId, payload) {
    const res = await updateDefaultRule(ruleId, payload)
    await fetchRules()
    return res.data
  }

  /**
   * 删除规则。
   * @returns {Promise<object>} { deleted, fell_back_to_hardcoded }
   */
  async function deleteRule(ruleId) {
    const res = await deleteDefaultRule(ruleId)
    await fetchRules()
    return res.data || { deleted: false }
  }

  /** 设置/清除手动覆盖的 preset_id（null 表示回退自动匹配）。 */
  function setManualPreset(presetId) {
    manualPresetId.value = presetId || null
  }

  return {
    // state
    rules,
    resolvePreview,
    manualPresetId,
    loading,
    // getters
    hasGlobalDefault,
    sceneRules,
    // actions
    fetchRules,
    resolve,
    createRule,
    updateRule,
    deleteRule,
    setManualPreset,
  }
})
