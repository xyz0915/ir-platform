<template>
  <div class="agent-library">
    <div class="al-header">
      <h3>Agent Library ({{ store.agents.length }} total, {{ store.availableAgents.length }} active)</h3>
      <el-button size="small" type="primary" @click="showRegisterDialog = true">
        + Register Agent
      </el-button>
    </div>

    <el-table :data="store.agents" style="width: 100%" stripe size="small" max-height="calc(100vh - 200px)">
      <el-table-column prop="name" label="Name" width="150" />
      <el-table-column prop="display_name" label="Display Name" min-width="150" />
      <el-table-column prop="type" label="Type" width="90">
        <template #default="{ row }">
          <el-tag :type="row.type === 'built-in' ? 'primary' : 'success'" size="small">
            {{ row.type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="data_sources" label="Data Sources" min-width="180">
        <template #default="{ row }">
          <span v-if="row.data_sources && row.data_sources.length" class="al-ds">
            {{ row.data_sources.join(', ') }}
          </span>
          <span v-else class="al-none">&mdash;</span>
        </template>
      </el-table-column>
      <el-table-column prop="enabled" label="Status" width="80">
        <template #default="{ row }">
          <el-switch
            v-if="row.type !== 'built-in'"
            :model-value="row.enabled"
            size="small"
            @change="toggleEnabled(row)"
          />
          <span v-else class="al-always">always</span>
        </template>
      </el-table-column>
      <el-table-column label="Actions" width="120">
        <template #default="{ row }">
          <el-button v-if="row.type !== 'built-in'" size="small" text @click="onEdit(row)">edit</el-button>
          <el-button v-if="row.type !== 'built-in'" size="small" text type="danger" @click="onDelete(row)">delete</el-button>
          <span v-else class="al-immutable">&mdash;</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- Register / Edit Dialog -->
    <el-dialog :model-value="showRegisterDialog" @close="showRegisterDialog = false"
               :title="editingAgent ? 'Edit Agent' : 'Register New Agent'" width="500px">
      <el-form :model="agentForm" label-width="120px" size="small">
        <el-form-item label="Name" required>
          <el-input v-model="agentForm.name" :disabled="!!editingAgent" />
        </el-form-item>
        <el-form-item label="Display Name" required>
          <el-input v-model="agentForm.display_name" />
        </el-form-item>
        <el-form-item label="Description">
          <el-input v-model="agentForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="Data Sources">
          <el-input v-model="agentForm.data_sources_text" placeholder="逗号分隔的表.字段" />
        </el-form-item>
        <el-form-item label="Depends On">
          <el-select v-model="agentForm.depends_on" multiple placeholder="前置 Agent" style="width: 100%">
            <el-option v-for="a in store.agents" :key="a.name" :label="a.display_name" :value="a.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="Prompt Template">
          <el-input v-model="agentForm.prompt_template" type="textarea" :rows="3" placeholder="可选 LLM prompt 模板" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="showRegisterDialog = false">Cancel</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="onSave">Save</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAgentManagementStore } from '@/stores/agentManagement'

const store = useAgentManagementStore()
const showRegisterDialog = ref(false)
const editingAgent = ref(null)
const saving = ref(false)

const agentForm = ref({
  name: '', display_name: '', description: '',
  data_sources_text: '', depends_on: [],
  prompt_template: '',
})

function resetForm() {
  agentForm.value = { name: '', display_name: '', description: '', data_sources_text: '', depends_on: [], prompt_template: '' }
}

function onEdit(agent) {
  editingAgent.value = agent
  agentForm.value = {
    name: agent.name,
    display_name: agent.display_name,
    description: agent.description || '',
    data_sources_text: (agent.data_sources || []).join(', '),
    depends_on: agent.depends_on || [],
    prompt_template: agent.prompt_template || '',
  }
  showRegisterDialog.value = true
}

async function onDelete(agent) {
  try {
    await ElMessageBox.confirm(`Delete agent "${agent.display_name}"?`, 'Confirm', { type: 'warning' })
    await store.deleteAgent(agent.name)
    ElMessage.success('Agent deleted')
  } catch { /* cancelled */ }
}

async function onSave() {
  const data = {
    name: agentForm.value.name,
    display_name: agentForm.value.display_name,
    description: agentForm.value.description,
    data_sources: agentForm.value.data_sources_text.split(',').map(s => s.trim()).filter(Boolean),
    depends_on: agentForm.value.depends_on,
    prompt_template: agentForm.value.prompt_template,
  }
  saving.value = true
  try {
    if (editingAgent.value) {
      await store.updateAgent(editingAgent.value.name, data)
      ElMessage.success('Agent updated')
    } else {
      await store.registerAgent(data)
      ElMessage.success('Agent registered')
    }
    showRegisterDialog.value = false
    resetForm()
    editingAgent.value = null
  } catch (e) {
    ElMessage.error('Failed: ' + (e.response?.data?.detail || e.message || 'unknown error'))
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(agent) {
  await store.updateAgent(agent.name, { enabled: !agent.enabled })
}
</script>

<style scoped>
.agent-library { display: flex; flex-direction: column; height: 100%; }
.al-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.al-header h3 { margin: 0; font-size: 14px; font-weight: 500; }
.al-ds { font-size: 12px; }
.al-none { font-size: 12px; color: var(--color-fg-subtle); }
.al-always { font-size: 12px; color: var(--color-fg-subtle); }
.al-immutable { font-size: 12px; color: var(--color-fg-subtle); }
</style>
