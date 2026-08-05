<template>
  <el-dialog
    :model-value="visible"
    :title="editingAgent ? '编辑智能体' : '新建自定义智能体'"
    width="560px"
    @update:model-value="(v) => emit('update:visible', v)"
    @close="emit('update:visible', false)"
  >
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="运行类型说明"
      description="内置智能体按固定逻辑运行；自定义智能体运行时按 name 分派，未匹配已知类型时将走“摘要/自定义执行”模式（可配置关联工具与模型获得真实分析）。"
      style="margin-bottom: 16px"
    />
    <el-form :model="form" label-width="110px" size="default" class="af-form">
      <el-form-item label="标识 Name" required>
        <el-input v-model="form.name" :disabled="!!editingAgent" placeholder="如 incident-custom-phish" />
        <div v-if="nameHint" class="af-name-hint">{{ nameHint }}</div>
      </el-form-item>
      <el-form-item label="运行类型 type" required>
        <el-radio-group v-model="form.type">
          <el-radio value="custom">自定义执行（custom）</el-radio>
          <el-radio value="built-in">内置（built-in）</el-radio>
        </el-radio-group>
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
      <template v-if="form.type === 'custom'">
        <el-form-item label="关联工具">
          <el-select v-model="form.tools" multiple filterable placeholder="ToolRegistry 工具" style="width: 100%">
            <el-option v-for="t in toolOptions" :key="t.tool_id" :label="`${t.name} (${t.tool_id})`" :value="t.tool_id" />
          </el-select>
          <div class="af-field-hint">运行时通过 ToolRegistry 真实调用，结果并入证据；调用失败不阻断管道。</div>
        </el-form-item>
        <el-form-item label="模型 Profile">
          <el-select v-model="form.model_profile" filterable placeholder="关联 AgentLLM profile" style="width: 100%">
            <el-option v-for="p in profileOptions" :key="p.profile_id" :label="`${p.name} / ${p.provider}`" :value="p.profile_id" />
          </el-select>
          <div class="af-field-hint">运行时使用该模型基于 prompt 生成分析结论；未配置则走静态摘要兜底。</div>
        </el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button class="af-btn-dark" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useAgentManagementStore } from '@/stores/agentManagement'
import agentApi from '@/api/agent'
import { ALL_KNOWN_TYPES_SET } from '@/constants/agentRuntime'

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
  type: 'custom',
  data_sources: [],
  depends_on: [],
  tools: [],
  model_profile: '',
})

/** name 输入预检（P2）：非空且不在已知类型 → 内联提示走摘要/自定义执行模式。 */
const nameHint = computed(() => {
  const name = (form.value.name || '').trim()
  if (!name) return ''
  if (ALL_KNOWN_TYPES_SET.has(name)) return ''
  return '该智能体将走摘要/自定义执行模式（未匹配内置运行类型）。'
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
          type: a.type || a.kind || 'custom',
          data_sources: Array.isArray(a.data_sources) ? a.data_sources : [],
          depends_on: a.depends_on || [],
          tools: a.tools || [],
          model_profile: a.model_profile || '',
        }
      } else {
        form.value = { name: '', display_name: '', description: '', type: 'custom', data_sources: [], depends_on: [], tools: [], model_profile: '' }
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
  // P1 payload 修复：kind:'custom' → type: form.type；status:'active' → enabled: true
  const payload = {
    name: form.value.name.trim(),
    display_name: form.value.display_name.trim(),
    description: form.value.description,
    type: form.value.type,
    data_sources: Array.isArray(form.value.data_sources) ? form.value.data_sources : [],
    depends_on: form.value.depends_on,
    tools: form.value.tools,
    model_profile: form.value.model_profile,
    enabled: true,
  }
  saving.value = true
  try {
    let res = null
    if (props.editingAgent) {
      res = await store.updateAgentAction(form.value.name, payload)
      ElMessage.success('智能体已更新')
    } else {
      res = await store.registerAgent(payload)
      ElMessage.success('智能体已注册')
    }
    // P2：保存成功后展示后端顶层 warning（若有）
    if (res && res.warning) {
      ElMessage.warning(res.warning)
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

<style scoped>
/* 主操作按钮：黑底白字（去 EP 默认蓝 primary） */
.af-btn-dark {
  --el-button-bg-color: #111827;
  --el-button-border-color: #111827;
  --el-button-text-color: #fff;
  --el-button-hover-bg-color: #1f2937;
  --el-button-hover-border-color: #1f2937;
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: #1f2937;
  --el-button-active-border-color: #1f2937;
  --el-button-active-text-color: #fff;
}

/* 单选选中态：近黑（去 EP 默认蓝） */
.af-form :deep(.el-radio__input.is-checked .el-radio__inner) {
  background: #111827;
  border-color: #111827;
}
.af-form :deep(.el-radio__input.is-checked + .el-radio__label) { color: #111827; }
.af-form :deep(.el-radio__inner:hover) { border-color: #111827; }

.af-name-hint {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
  margin-top: 4px;
}
.af-field-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  line-height: 1.5;
  margin-top: 4px;
}
</style>
