<template>
  <el-dialog
    :model-value="visible"
    :title="editingAgent ? '编辑智能体' : '新建自定义智能体'"
    width="560px"
    @update:model-value="(v) => emit('update:visible', v)"
    @close="emit('update:visible', false)"
  >
    <el-form :model="form" label-width="110px" size="default">
      <el-form-item label="标识 Name" required>
        <el-input v-model="form.name" :disabled="!!editingAgent" placeholder="如 incident-custom-phish" />
      </el-form-item>
      <el-form-item label="显示名" required>
        <el-input v-model="form.display_name" placeholder="如 钓鱼事件快处 Agent" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="数据来源">
        <el-select
          v-model="form.data_sources"
          multiple
          filterable
          allow-create
          default-first-option
          placeholder="可输入后回车新增标签，如 邮件网关"
          style="width: 100%"
        >
          <el-option
            v-for="ds in dataSourcePresets"
            :key="ds"
            :label="ds"
            :value="ds"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="依赖 Agent">
        <el-select v-model="form.depends_on" multiple placeholder="前置 Agent" style="width: 100%">
          <el-option v-for="a in agentOptions" :key="a.name" :label="a.display_name" :value="a.name" />
        </el-select>
      </el-form-item>
      <el-form-item label="关联工具">
        <el-select v-model="form.tools" multiple filterable placeholder="ToolRegistry 工具" style="width: 100%">
          <el-option v-for="t in toolOptions" :key="t.tool_id" :label="`${t.name} (${t.tool_id})`" :value="t.tool_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="模型 Profile">
        <el-select v-model="form.model_profile" filterable placeholder="关联 AgentLLM profile" style="width: 100%">
          <el-option v-for="p in profileOptions" :key="p.profile_id" :label="`${p.name} / ${p.provider}`" :value="p.profile_id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useAgentManagementStore } from '@/stores/agentManagement'
import agentApi from '@/api/agent'

const props = defineProps({
  visible: { type: Boolean, default: false },
  editingAgent: { type: Object, default: null },
})
const emit = defineEmits(['update:visible', 'saved'])

const store = useAgentManagementStore()
const saving = ref(false)

const form = ref({
  name: '',
  display_name: '',
  description: '',
  data_sources: [],
  depends_on: [],
  tools: [],
  model_profile: '',
})

/** 数据来源常用预设（用户仍可通过 el-select 的 allow-create 自由新增）。 */
const dataSourcePresets = ['邮件网关', '身份目录', 'EDR 终端', '防火墙', 'Web 代理', 'DNS 日志']

const agentOptions = computed(() => store.agents)
const toolOptions = ref([])
const profileOptions = ref([])

watch(
  () => props.visible,
  (v) => {
    if (v) {
      if (props.editingAgent) {
        const a = props.editingAgent
        form.value = {
          name: a.name,
          display_name: a.display_name || '',
          description: a.description || '',
          data_sources: Array.isArray(a.data_sources) ? a.data_sources : [],
          depends_on: a.depends_on || [],
          tools: a.tools || [],
          model_profile: a.model_profile || '',
        }
      } else {
        form.value = { name: '', display_name: '', description: '', data_sources: [], depends_on: [], tools: [], model_profile: '' }
      }
    }
  }
)

onMounted(async () => {
  try {
    const [t, p] = await Promise.all([
      agentApi.tools.listTools(),
      agentApi.settings.listModelProfiles(),
    ])
    toolOptions.value = t.data || []
    profileOptions.value = p.data || []
  } catch (e) {
    console.error('[AgentForm] 加载工具/模型失败', e)
  }
})

async function onSave() {
  if (!form.value.name.trim() || !form.value.display_name.trim()) {
    ElMessage.warning('标识与显示名必填')
    return
  }
  const payload = {
    name: form.value.name.trim(),
    display_name: form.value.display_name.trim(),
    description: form.value.description,
    kind: 'custom',
    data_sources: Array.isArray(form.value.data_sources) ? form.value.data_sources : [],
    depends_on: form.value.depends_on,
    tools: form.value.tools,
    model_profile: form.value.model_profile,
    status: 'active',
  }
  saving.value = true
  try {
    if (props.editingAgent) {
      await store.updateAgentAction(form.value.name, payload)
      ElMessage.success('智能体已更新')
    } else {
      await store.registerAgent(payload)
      ElMessage.success('智能体已注册')
    }
    emit('saved')
    emit('update:visible', false)
  } catch (e) {
    // 错误已由 axios 拦截器提示
  } finally {
    saving.value = false
  }
}
</script>
