<template>
  <div class="agent-management-view">
    <!-- 页头 -->
    <div class="am-header">
      <div class="am-tabs">
        <button :class="['am-tab', { active: activeTab === 'builder' }]" @click="activeTab = 'builder'">
          <el-icon><Connection /></el-icon> Pipeline Builder
        </button>
        <button :class="['am-tab', { active: activeTab === 'library' }]" @click="activeTab = 'library'">
          <el-icon><Setting /></el-icon> Agent Library
        </button>
        <button :class="['am-tab', { active: activeTab === 'history' }]" @click="activeTab = 'history'">
          <el-icon><Clock /></el-icon> Execution History
        </button>
      </div>
    </div>

    <!-- Pipeline Builder Tab -->
    <div v-if="activeTab === 'builder'" class="am-content">
      <div class="pipeline-builder">
        <!-- 左侧：Available Agents -->
        <div class="pb-pool">
          <h3 class="pb-pool-title">Available agents</h3>
          <div class="pb-pool-list">
            <div
              v-for="agent in store.availableAgents"
              :key="agent.name"
              class="pb-pool-item"
              :class="{ 'in-pipeline': isInPipeline(agent.name) }"
              draggable="true"
              @dragstart="onDragStart($event, agent)"
              @click="store.addToPipeline(agent)"
            >
              <span class="pb-dot" :style="{ background: agentColor(agent.name) }"></span>
              <span class="pb-name">{{ agent.display_name }}</span>
              <span class="pb-type">{{ agent.type === 'built-in' ? 'built-in' : 'custom' }}</span>
            </div>
          </div>
        </div>

        <!-- 右侧：Pipeline Canvas -->
        <div class="pb-canvas">
          <div class="pb-canvas-header">
            <h3 class="pb-canvas-title">Pipeline ({{ store.pipeline.length }} agents)</h3>
            <div class="pb-canvas-actions">
              <el-button size="small" @click="store.clearPipeline()">Clear</el-button>
              <el-button size="small" @click="onSavePreset">Save Preset</el-button>
              <el-button size="small" type="primary" :loading="store.runLoading"
                         :disabled="!store.isPipelineValid || store.pipeline.length === 0"
                         @click="onStartPipeline">
                <el-icon><VideoPlay /></el-icon> Start Pipeline
              </el-button>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="store.pipeline.length === 0" class="pb-empty">
            <p>Drag agents from the left panel or click to add</p>
          </div>

          <!-- 管道阶段列表 -->
          <div v-else class="pb-stages">
            <div
              v-for="(agent, idx) in store.pipeline"
              :key="agent.name"
              class="pb-stage"
              :class="{ 'is-disabled': !agent.enabled }"
              draggable="true"
              @dragstart="onStageDragStart($event, idx)"
              @dragover.prevent="onStageDragOver($event, idx)"
              @drop="onStageDrop($event, idx)"
              @dragend="onDragEnd"
            >
              <div class="pb-stage-order">{{ idx + 1 }}</div>
              <span class="pb-dot" :style="{ background: agentColor(agent.name) }"></span>
              <div class="pb-stage-info">
                <span class="pb-stage-name">{{ agent.display_name }}</span>
                <span class="pb-stage-desc">{{ agent.description || '' }}</span>
              </div>
              <span class="pb-stage-type">{{ agent.type }}</span>
              <span v-if="agent.hitl" class="pb-stage-hitl">HITL</span>
              <button class="pb-stage-remove" @click="store.removeFromPipeline(agent.name)" title="Remove">&times;</button>
            </div>
          </div>

          <!-- 校验结果 -->
          <div v-if="store.validationMessages.length > 0 && !store.isPipelineValid" class="pb-warnings">
            <div v-for="(msg, i) in store.validationMessages" :key="i" class="pb-warning">
              <el-icon><Warning /></el-icon> {{ msg }}
            </div>
          </div>
          <div v-else-if="store.isPipelineValid && store.pipeline.length > 0" class="pb-valid">
            Pipeline configuration is valid
          </div>
        </div>
      </div>
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
import { Connection, Setting, Clock, VideoPlay, Warning } from '@element-plus/icons-vue'
import { useAgentManagementStore } from '@/stores/agentManagement'
import AgentLibraryPanel from '@/components/agents/AgentLibraryPanel.vue'

const router = useRouter()
const store = useAgentManagementStore()

const activeTab = ref('builder')

// 拖拽状态
let dragAgent = null
let dragStageIdx = -1

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

function isInPipeline(name) {
  return store.pipeline.some(a => a.name === name)
}

function agentColor(name) {
  const colors = {
    triage: '#378ADD', file_analysis: '#639922', process_analysis: '#9B59B6',
    network_analysis: '#D85A30', registry_analysis: '#F39C12',
    threat_intel: '#E74C3C', timeline: '#185FA5',
    root_cause: '#1D9E75', responder: '#888780', reporter: '#378ADD',
  }
  return colors[name] || '#888'
}

// 从 Agent Pool 拖入
function onDragStart(e, agent) {
  dragAgent = agent
  e.dataTransfer.effectAllowed = 'copy'
  e.dataTransfer.setData('text/plain', agent.name)
}

// 管道内拖拽
function onStageDragStart(e, idx) {
  dragStageIdx = idx
  e.dataTransfer.effectAllowed = 'move'
}
function onStageDragOver(e, idx) {
  if (dragStageIdx === -1) return
  e.dataTransfer.dropEffect = 'move'
}
function onStageDrop(e, idx) {
  if (dragStageIdx >= 0) {
    // 管道内重排
    store.reorderPipeline(dragStageIdx, idx)
  }
  dragStageIdx = -1
}
function onDragEnd() {
  dragAgent = null
  dragStageIdx = -1
}

// 保存预置
async function onSavePreset() {
  try {
    const { value: name } = await ElMessageBox.prompt('Enter a name for this pipeline preset', 'Save Preset', {
      inputPattern: /.+/,
      inputErrorMessage: 'Name is required',
    })
    await store.savePreset(name, `Pipeline with ${store.pipeline.length} agents`)
    ElMessage.success('Preset saved')
  } catch (e) {
    if (e !== 'cancel' && String(e).indexOf('cancel') < 0) {
      console.error('Save preset error:', e)
      ElMessage.error('Save failed: ' + (e?.response?.data?.detail || e?.message || String(e)))
    }
  }
}

// 启动管道
async function onStartPipeline() {
  try {
    const { value: eventId } = await ElMessageBox.prompt('Enter Event ID to run pipeline on', 'Start Pipeline', {
      inputPattern: /.+/,
      inputErrorMessage: 'Event ID is required',
      inputValue: '',
    })
    const run = await store.startPipeline(eventId)
    ElMessage.success(`Pipeline started: ${run.run_id}`)
    // 跳转到详情页查看 SSE 实时进度
    router.push(`/agent-orchestration/${run.run_id}`)
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('Failed to start pipeline: ' + (e.message || e))
    }
  }
}
</script>

<style scoped>
.agent-management-view { height: calc(100vh - 52px); display: flex; flex-direction: column; background: var(--color-canvas-subtle); }
.am-header { flex-shrink: 0; background: var(--color-canvas-default); border-bottom: 0.5px solid var(--color-border-default); padding: 0 16px; }
.am-tabs { display: flex; gap: 4px; }
.am-tab { padding: 10px 16px; font-size: 13px; border: none; background: transparent; color: var(--color-fg-subtle); cursor: pointer; border-bottom: 2px solid transparent; display: flex; align-items: center; gap: 6px; }
.am-tab.active { color: var(--color-accent-fg); border-bottom-color: var(--color-accent-fg); font-weight: 500; }
.am-content { flex: 1; overflow: hidden; padding: 12px 16px; }
.pipeline-builder { display: flex; gap: 16px; height: 100%; }
.pb-pool { flex: 0 0 220px; display: flex; flex-direction: column; overflow: hidden; }
.pb-pool-title { font-size: 13px; font-weight: 500; margin: 0 0 8px; color: var(--color-fg-default); }
.pb-pool-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.pb-pool-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; background: var(--color-canvas-default); border-radius: 6px; border: 0.5px solid var(--color-border-default); cursor: grab; font-size: 13px; transition: all 0.15s; }
.pb-pool-item:hover { border-color: var(--color-accent-fg); }
.pb-pool-item.in-pipeline { opacity: 0.5; }
.pb-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.pb-name { flex: 1; }
.pb-type { font-size: 11px; color: var(--color-fg-subtle); }
.pb-canvas { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.pb-canvas-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.pb-canvas-title { font-size: 13px; font-weight: 500; margin: 0; }
.pb-canvas-actions { display: flex; gap: 8px; }
.pb-empty { flex: 1; display: flex; align-items: center; justify-content: center; border: 2px dashed var(--color-border-default); border-radius: 8px; color: var(--color-fg-subtle); font-size: 13px; }
.pb-stages { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
.pb-stage { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: var(--color-canvas-default); border-radius: 6px; border: 0.5px solid var(--color-border-default); cursor: grab; font-size: 13px; }
.pb-stage:hover { border-color: var(--color-accent-fg); }
.pb-stage.is-disabled { opacity: 0.5; }
.pb-stage-order { width: 22px; height: 22px; border-radius: 50%; background: var(--color-accent-fg); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 500; flex-shrink: 0; }
.pb-stage-info { flex: 1; min-width: 0; }
.pb-stage-name { display: block; font-weight: 500; }
.pb-stage-desc { display: block; font-size: 11px; color: var(--color-fg-subtle); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pb-stage-type { font-size: 11px; color: var(--color-fg-subtle); padding: 2px 6px; background: var(--color-canvas-subtle); border-radius: 4px; }
.pb-stage-hitl { font-size: 10px; padding: 2px 6px; background: #FCEBEB; color: #A32D2D; border-radius: 4px; font-weight: 500; }
.pb-stage-remove { width: 20px; height: 20px; border: none; background: transparent; font-size: 16px; cursor: pointer; color: var(--color-fg-subtle); border-radius: 4px; }
.pb-stage-remove:hover { background: var(--color-danger-subtle); color: var(--color-danger-fg); }
.pb-warnings { margin-top: 8px; }
.pb-warning { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #A32D2D; padding: 6px 10px; background: #FCEBEB; border-radius: 4px; margin-bottom: 4px; }
.pb-valid { margin-top: 8px; font-size: 12px; color: #3B6D11; padding: 6px 10px; background: #EAF3DE; border-radius: 4px; }
.am-history-empty { text-align: center; padding: 40px; color: var(--color-fg-subtle); font-size: 13px; }
</style>
