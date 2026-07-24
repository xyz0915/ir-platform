/**
 * 记忆与 RAG Store（M5）。
 *
 * 职责：加载知识库 / 向量库概览（KnowledgeBase）。
 * 当前经 agentApi.memory 走 Mock（F3 后端未建），后端就绪仅切换 USE_MOCK 开关。
 *
 * 设计依据：01-api-spec.md §5 / T9。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'

export const useMemoryStore = defineStore('memory', () => {
  // ===== 状态 =====
  const knowledgeBases = ref([]) // KnowledgeBase[]
  const loading = ref(false)

  // ===== 派生 =====
  const totalDocs = computed(() =>
    knowledgeBases.value.reduce((sum, kb) => sum + (Number(kb.doc_count) || 0), 0)
  )

  // ===== 动作 =====
  async function fetchKnowledgeBases() {
    loading.value = true
    try {
      const res = await agentApi.memory.listKnowledgeBases()
      knowledgeBases.value = res.data || []
    } finally {
      loading.value = false
    }
  }

  return {
    // state
    knowledgeBases,
    loading,
    // getters
    totalDocs,
    // actions
    fetchKnowledgeBases,
  }
})
