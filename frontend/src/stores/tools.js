/**
 * 工具与 MCP Store（M4）。
 *
 * 职责：加载工具清单（ToolDef）与 MCP 服务器状态（McpServer）。
 * 当前经 agentApi.tools 走 Mock（F1 后端未建），后端就绪仅切换 USE_MOCK 开关。
 *
 * 设计依据：01-api-spec.md §4 / T8。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import agentApi from '@/api/agent'
import { TOOL_STATUS_LABELS, MCP_STATUS_LABELS } from '@/constants/agentLabels'

export const useToolsStore = defineStore('tools', () => {
  // ===== 状态 =====
  const tools = ref([]) // ToolDef[]
  const mcpServers = ref([]) // McpServer[]
  const loading = ref(false)

  // ===== 派生 =====
  const toolCount = computed(() => tools.value.length)
  const onlineCount = computed(() => mcpServers.value.filter((s) => s.status === 'online').length)
  const toolsByCategory = computed(() => {
    const map = new Map()
    tools.value.forEach((t) => {
      const key = t.category || '其他'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(t)
    })
    return Array.from(map.entries())
  })

  const toolStatusLabel = (s) => TOOL_STATUS_LABELS[s] || s || '—'
  const mcpStatusLabel = (s) => MCP_STATUS_LABELS[s] || s || '—'

  // ===== 动作 =====
  async function fetchTools() {
    loading.value = true
    try {
      const res = await agentApi.tools.listTools()
      tools.value = res.data || []
    } finally {
      loading.value = false
    }
  }

  async function fetchMcpServers() {
    try {
      const res = await agentApi.tools.listMcpServers()
      mcpServers.value = res.data || []
    } catch (e) {
      console.error('[tools] fetchMcpServers failed:', e)
    }
  }

  async function refreshAll() {
    await Promise.all([fetchTools(), fetchMcpServers()])
  }

  return {
    // state
    tools,
    mcpServers,
    loading,
    // getters
    toolCount,
    onlineCount,
    toolsByCategory,
    toolStatusLabel,
    mcpStatusLabel,
    // actions
    fetchTools,
    fetchMcpServers,
    refreshAll,
  }
})
