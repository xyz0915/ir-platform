<template>
  <div class="agent-management-view">
    <!-- 页头 -->
    <div class="am-header">
      <div class="am-tabs">
        <button :class="['am-tab', { active: activeTab === 'builder' }]" @click="activeTab = 'builder'">
          <el-icon><Connection /></el-icon> 流水线编排
        </button>
        <button :class="['am-tab', { active: activeTab === 'library' }]" @click="activeTab = 'library'">
          <el-icon><Setting /></el-icon> 智能体库
        </button>
        <button :class="['am-tab', { active: activeTab === 'history' }]" @click="activeTab = 'history'">
          <el-icon><Clock /></el-icon> 执行历史
        </button>
      </div>
    </div>

    <!-- Pipeline Builder Tab — 重设计三栏布局 -->
    <div v-if="activeTab === 'builder'" class="am-content am-content-pipeline">
      <PipelineRedesignView />
    </div>

    <!-- Agent Library Tab -->
    <div v-if="activeTab === 'library'" class="am-content">
      <AgentLibraryPanel />
    </div>

    <!-- Execution History Tab -->
    <div v-if="activeTab === 'history'" class="am-content">
      <div class="am-history">
        <el-table :data="[]" style="width: 100%" stripe size="small">
          <el-table-column prop="run_id" label="Run ID" width="200" />
          <el-table-column prop="event_id" label="Event" width="150" />
          <el-table-column prop="status" label="Status" width="100" />
          <el-table-column prop="total_elapsed" label="Duration" width="100" />
          <el-table-column prop="created_at" label="Created" />
        </el-table>
        <p class="am-history-empty">Execution history will be available after pipelines are run.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Setting, Clock } from '@element-plus/icons-vue'
import { useAgentManagementStore } from '@/stores/agentManagement'
import AgentLibraryPanel from '@/components/agents/AgentLibraryPanel.vue'
import PipelineRedesignView from '@/views/agent-orchestration/PipelineRedesignView.vue'

const router = useRouter()
const store = useAgentManagementStore()

const activeTab = ref('builder')

onMounted(async () => {
  console.log('[AgentManagement] mounted, fetching agents...')
  try {
    await store.fetchAgents()
    console.log('[AgentManagement] agents loaded:', store.agents.length)
    await store.fetchPresets()
    console.log('[AgentManagement] presets loaded:', store.presets.length)
  } catch (e) {
    console.error('[AgentManagement] mount error:', e)
  }
})
</script>

<style scoped>
.agent-management-view { height: calc(100vh - 52px); display: flex; flex-direction: column; background: var(--color-canvas-subtle); }
.am-header { flex-shrink: 0; background: var(--color-canvas-default); border-bottom: 0.5px solid var(--color-border-default); padding: 0 16px; }
.am-tabs { display: flex; gap: 4px; }
.am-tab { padding: 10px 16px; font-size: 13px; border: none; background: transparent; color: var(--color-fg-subtle); cursor: pointer; border-bottom: 2px solid transparent; display: flex; align-items: center; gap: 6px; }
.am-tab.active { color: var(--color-accent-fg); border-bottom-color: var(--color-accent-fg); font-weight: 500; }
.am-content { flex: 1; overflow: hidden; padding: 12px 16px; }
.am-content-pipeline { padding: 0; }
.am-history-empty { text-align: center; padding: 40px; color: var(--color-fg-subtle); font-size: 13px; }
</style>
