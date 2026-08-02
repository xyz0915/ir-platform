<template>
  <div class="agent-library">
    <!-- 头部：统计 + 新建 -->
    <div class="al-header">
      <div class="al-stats">
        <span>共 <b>{{ store.agents.length }}</b> 个</span>
        <span class="al-sep">·</span>
        <span>启用 <b>{{ store.availableAgents.length }}</b></span>
        <span class="al-sep">·</span>
        <span>自定义 <b>{{ customCount }}</b></span>
      </div>
      <el-button size="small" type="primary" @click="showForm = true">
        <el-icon><Plus /></el-icon> 新建智能体
      </el-button>
    </div>

    <!-- 卡片网格 -->
    <div v-loading="store.loading" class="al-grid">
      <div
        v-for="agent in store.agents"
        :key="agent.name"
        class="al-card"
        :class="{ disabled: !agent.enabled }"
        @click="openDetail(agent)"
      >
        <div class="al-card-head">
          <span class="al-dot" :style="{ background: agentColor(agent.name) }" />
          <span class="al-card-name">{{ agent.display_name }}</span>
          <el-tag size="small" :type="agent.kind === 'builtin' ? 'primary' : 'success'" effect="plain">
            {{ agent.kind === 'builtin' ? '内置' : '自定义' }}
          </el-tag>
        </div>
        <div class="al-card-desc">{{ agent.description || '暂无描述' }}</div>
        <div class="al-card-meta">
          <span class="al-chip">{{ (agent.data_sources || []).length }} 数据源</span>
          <span class="al-chip">{{ (agent.tools || []).length }} 工具</span>
          <span class="al-chip">{{ (agent.depends_on || []).length }} 依赖</span>
        </div>
      </div>

      <el-empty v-if="!store.loading && store.agents.length === 0" description="暂无智能体" />
    </div>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawer" :title="selected?.display_name" size="420px" @close="selected = null">
      <template v-if="selected">
        <div class="al-d-sheet">
          <div class="al-d-row">
            <span class="al-d-k">标识</span><span class="al-d-v mono">{{ selected.name }}</span>
          </div>
          <div class="al-d-row">
            <span class="al-d-k">类型</span>
            <span class="al-d-v">
              <el-tag size="small" :type="selected.kind === 'builtin' ? 'primary' : 'success'" effect="plain">
                {{ selected.kind === 'builtin' ? '内置' : '自定义' }}
              </el-tag>
            </span>
          </div>
          <div class="al-d-row">
            <span class="al-d-k">状态</span>
            <span class="al-d-v">
              <el-switch
                v-if="selected.kind !== 'builtin'"
                :model-value="selected.enabled"
                @change="toggleEnabled(selected)"
              />
              <el-tag v-else size="small" type="info" effect="plain">常驻</el-tag>
            </span>
          </div>
          <div class="al-d-block">
            <div class="al-d-k">描述</div>
            <div class="al-d-v">{{ selected.description || '—' }}</div>
          </div>
          <div class="al-d-block">
            <div class="al-d-k">数据来源</div>
            <div class="al-d-v">
              <el-tag v-for="ds in (selected.data_sources || [])" :key="ds" size="small" class="al-tag">{{ ds }}</el-tag>
              <span v-if="!(selected.data_sources || []).length">—</span>
            </div>
          </div>
          <div class="al-d-block">
            <div class="al-d-k">依赖 Agent</div>
            <div class="al-d-v">
              <el-tag v-for="d in (selected.depends_on || [])" :key="d" size="small" class="al-tag">{{ nameOf(d) }}</el-tag>
              <span v-if="!(selected.depends_on || []).length">—</span>
            </div>
          </div>
          <div class="al-d-block">
            <div class="al-d-k">关联工具</div>
            <div class="al-d-v">
              <el-tag v-for="t in (selected.tools || [])" :key="t" size="small" class="al-tag" effect="plain">{{ toolName(t) }}</el-tag>
              <span v-if="!(selected.tools || []).length">—</span>
            </div>
          </div>
          <div class="al-d-block">
            <div class="al-d-k">模型 Profile</div>
            <div class="al-d-v">{{ profileName(selected.model_profile) || '—' }}</div>
          </div>
        </div>

        <div class="al-d-actions" v-if="selected.kind !== 'builtin'">
          <el-button size="small" @click="editAgent(selected)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="removeAgent(selected)">删除</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 新建 / 编辑表单 -->
    <AgentForm v-model:visible="showForm" :editing-agent="editingAgent" @saved="onSaved" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { useAgentManagementStore } from '@/stores/agentManagement'
import agentApi from '@/api/agent'
import AgentForm from './AgentForm.vue'

const store = useAgentManagementStore()
const showForm = ref(false)
const editingAgent = ref(null)
const drawer = ref(false)
const selected = ref(null)

const customCount = computed(() => store.agents.filter((a) => a.kind === 'custom').length)

const toolMap = ref({})
const profileMap = ref({})

onMounted(async () => {
  // 面板独立渲染（无 props/emits），挂载时自行拉取智能体列表。
  // store.fetchAgents/fetchPresets 内部已 catch 错误并置空数组，安全。
  try {
    await Promise.all([store.fetchAgents(), store.fetchPresets()])
  } catch (e) {
    console.error('[AgentLibrary] 加载智能体列表失败', e)
  }
  try {
    const [t, p] = await Promise.all([
      agentApi.tools.listTools(),
      agentApi.settings.listModelProfiles(),
    ])
    ;(t.data || []).forEach((x) => { toolMap.value[x.tool_id] = x.name })
    ;(p.data || []).forEach((x) => { profileMap.value[x.profile_id] = `${x.name} / ${x.provider}` })
  } catch (e) {
    console.error('[AgentLibrary] 加载工具/模型失败', e)
  }
})

function agentColor(name) {
  const colors = {
    triage: '#378ADD', file_analysis: '#639922', process_analysis: '#9B59B6',
    network_analysis: '#D85A30', registry_analysis: '#F39C12',
    threat_intel: '#E74C3C', timeline: '#185FA5',
    root_cause: '#1D9E75', remediate: '#888780', reporter: '#378ADD',
  }
  return colors[name] || '#888'
}

function nameOf(name) {
  const a = store.agents.find((x) => x.name === name)
  return a ? a.display_name : name
}
function toolName(id) {
  return toolMap.value[id] || id
}
function profileName(id) {
  return profileMap.value[id] || id
}

function openDetail(agent) {
  selected.value = agent
  drawer.value = true
}

async function toggleEnabled(agent) {
  await store.updateAgentAction(agent.name, { enabled: !agent.enabled })
}

function editAgent(agent) {
  editingAgent.value = agent
  showForm.value = true
}

async function removeAgent(agent) {
  try {
    await ElMessageBox.confirm(`删除智能体「${agent.display_name}」？`, '确认', { type: 'warning' })
    await store.deleteAgentAction(agent.name)
    ElMessage.success('已删除')
    drawer.value = false
  } catch { /* cancelled */ }
}

function onSaved() {
  editingAgent.value = null
  drawer.value = false
}
</script>

<style scoped>
.agent-library { display: flex; flex-direction: column; height: 100%; }
.al-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.al-stats { font-size: 13px; color: var(--color-fg-muted); }
.al-stats b { color: var(--color-fg-default); }
.al-sep { margin: 0 6px; color: var(--color-border-default); }
.al-grid {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  align-content: start;
  padding: 2px;
}
.al-card {
  border: 1px solid var(--color-border-default);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--color-canvas-default);
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.al-card:hover { border-color: var(--color-accent-fg); box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.al-card.disabled { opacity: 0.6; }
.al-card-head { display: flex; align-items: center; gap: 8px; }
.al-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.al-card-name { font-weight: 600; color: var(--color-fg-default); font-size: 14px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.al-card-desc { font-size: 12px; color: var(--color-fg-muted); line-height: 1.5; min-height: 36px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.al-card-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.al-chip { font-size: 11px; padding: 2px 8px; background: var(--color-canvas-subtle); border-radius: 4px; color: var(--color-fg-muted); }

.al-d-sheet { display: flex; flex-direction: column; gap: 12px; }
.al-d-row { display: flex; gap: 12px; align-items: center; }
.al-d-k { width: 80px; flex-shrink: 0; font-size: 12px; color: var(--color-fg-subtle); }
.al-d-v { font-size: 13px; color: var(--color-fg-default); word-break: break-all; }
.al-d-block { display: flex; flex-direction: column; gap: 6px; }
.al-d-block .al-d-k { width: auto; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.al-tag { margin: 0 4px 4px 0; }
.al-d-actions { margin-top: 20px; display: flex; gap: 8px; }
</style>
