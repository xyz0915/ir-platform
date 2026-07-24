/**
 * 编排设置 Store（M9）。
 *
 * 职责：加载多模型 profile（ModelProfile）与部署配置（DeploymentConfig）。
 * 当前经 agentApi.settings 走 Mock（F10/F14 后端未建），后端就绪仅切换 USE_MOCK 开关。
 *
 * 设计依据：01-api-spec.md §9 / T10。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'

export const useAgentSettingsStore = defineStore('agentSettings', () => {
  // ===== 状态 =====
  const modelProfiles = ref([]) // ModelProfile[]
  const deploymentConfig = ref(null) // DeploymentConfig
  const loading = ref(false)

  // ===== 派生 =====
  const enabledProfiles = computed(() => modelProfiles.value.filter((p) => p.enabled).length)

  // ===== 动作 =====
  async function fetchModelProfiles() {
    loading.value = true
    try {
      const res = await agentApi.settings.listModelProfiles()
      modelProfiles.value = res.data || []
    } finally {
      loading.value = false
    }
  }

  async function fetchDeploymentConfig() {
    try {
      const res = await agentApi.settings.getDeploymentConfig()
      deploymentConfig.value = res.data || null
    } catch (e) {
      console.error('[agentSettings] fetchDeploymentConfig failed:', e)
    }
  }

  async function refreshAll() {
    await Promise.all([fetchModelProfiles(), fetchDeploymentConfig()])
  }

  return {
    // state
    modelProfiles,
    deploymentConfig,
    loading,
    // getters
    enabledProfiles,
    // actions
    fetchModelProfiles,
    fetchDeploymentConfig,
    refreshAll,
  }
})
