/**
 * 可观测性 Store（M8 增强）。
 *
 * 职责：加载某次 run 的 trace / 日志 / 续跑点（ ObservabilityRun ）。
 * 真实运行数据来自 agentApi.runs.getAgentRun，trace/log/resume_point 经
 * agentApi.observability.getRun（当前 Mock，后端 F7 就绪切换真实端点）。
 *
 * 设计依据：01-api-spec.md §8 / T5。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import agentApi from '@/api/agent'

export const useObservabilityStore = defineStore('observability', () => {
  const run = ref(null) // ObservabilityRun
  const loading = ref(false)

  /**
   * 加载某次运行的可观测性数据。
   * @param {string} runId
   */
  async function fetchRun(runId) {
    if (!runId) return
    loading.value = true
    try {
      const res = await agentApi.observability.getRun(runId)
      run.value = res.data || null
    } catch (e) {
      console.error('[observability] fetchRun failed:', e)
      run.value = null
    } finally {
      loading.value = false
    }
  }

  function clear() {
    run.value = null
  }

  return { run, loading, fetchRun, clear }
})
