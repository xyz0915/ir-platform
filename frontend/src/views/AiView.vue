<template>
  <div class="page-container">
    <div class="card-box">
      <h2 class="page-title mb-20">AI 分析配置</h2>

      <!-- 安全警告 -->
      <el-alert
        v-if="config && config.enabled === 1"
        type="warning"
        :closable="false"
        class="mb-20"
      >
        <strong>⚠️ AI 分析功能已开启</strong>
        开启后，主机取证数据将发送至外部 AI 服务进行分析。请确保：
        1) 您已获得授权合规使用该数据；2) AI 服务提供商可信；3) 敏感数据不会泄露。
      </el-alert>

      <el-alert
        v-if="!config || config.enabled === 0"
        type="info"
        :closable="false"
        class="mb-20"
      >
        AI 分析功能当前<strong>已关闭</strong>。需手动开启后才能使用一键 AI 分析功能。
      </el-alert>

      <!-- AI 功能开关 -->
      <div class="flex-between mb-20">
        <div>
          <span class="switch-label">AI 分析功能</span>
          <el-switch
            :model-value="config?.enabled === 1"
            @change="handleToggle"
            active-color="#E6A23C"
            inactive-color="#909399"
            :loading="toggleLoading"
          />
          <el-tag v-if="config?.enabled === 1" type="warning" size="small" class="ml-10">已开启 - 数据将发送至外部AI服务</el-tag>
          <el-tag v-else type="info" size="small" class="ml-10">已关闭</el-tag>
        </div>
      </div>

      <!-- 配置表单 -->
      <el-form
        :model="form"
        label-width="140px"
        :disabled="config?.enabled === 0"
        v-loading="formLoading"
      >
        <el-form-item label="API Base URL">
          <el-input
            v-model="form.api_base_url"
            placeholder="例如: https://api.openai.com/v1"
            clearable
          />
          <div class="form-tip">OpenAI 兼容格式的 API 地址，支持各种大模型服务</div>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            placeholder="输入 API Key"
            show-password
            clearable
          />
          <div class="form-tip" v-if="config?.api_key_masked">
            当前已保存的 Key: <code>{{ config.api_key_masked }}</code>
          </div>
        </el-form-item>

        <el-form-item label="模型名称">
          <el-select v-model="form.model_name" filterable allow-create placeholder="选择或输入模型名称">
            <el-option label="gpt-4o" value="gpt-4o" />
            <el-option label="gpt-4o-mini" value="gpt-4o-mini" />
            <el-option label="gpt-4" value="gpt-4" />
            <el-option label="gpt-3.5-turbo" value="gpt-3.5-turbo" />
            <el-option label="deepseek-chat" value="deepseek-chat" />
            <el-option label="deepseek-reasoner" value="deepseek-reasoner" />
            <el-option label="qwen-max" value="qwen-max" />
            <el-option label="qwen-plus" value="qwen-plus" />
            <el-option label="glm-4" value="glm-4" />
            <el-option label="claude-3-sonnet" value="claude-3-sonnet" />
          </el-select>
        </el-form-item>

        <el-form-item label="Max Tokens">
          <el-slider v-model="form.max_tokens" :min="512" :max="16384" :step="256" show-input />
        </el-form-item>

        <el-form-item label="Temperature">
          <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
        </el-form-item>

        <el-form-item label="系统提示词">
          <el-input
            v-model="form.system_prompt"
            type="textarea"
            :rows="6"
            placeholder="自定义 AI 分析的系统提示词（可选，留空使用默认提示词）"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="handleSave" :loading="saveLoading">保存配置</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAiConfig, saveAiConfig, toggleAi } from '@/api/ai'

const config = ref(null)
const toggleLoading = ref(false)
const formLoading = ref(false)
const saveLoading = ref(false)

const form = reactive({
  api_base_url: '',
  api_key: '',
  model_name: 'gpt-4o',
  max_tokens: 4096,
  temperature: 0.3,
  system_prompt: ''
})

onMounted(() => {
  loadConfig()
})

async function loadConfig() {
  formLoading.value = true
  try {
    const res = await getAiConfig()
    config.value = res.data
    if (res.data) {
      form.api_base_url = res.data.api_base_url || ''
      form.model_name = res.data.model_name || 'gpt-4o'
      form.max_tokens = res.data.max_tokens || 4096
      form.temperature = res.data.temperature || 0.3
      form.system_prompt = res.data.system_prompt || ''
      form.api_key = '' // 不回显已保存的Key
    }
  } catch (error) {
    // handled
  } finally {
    formLoading.value = false
  }
}

async function handleToggle(val) {
  const enabled = val ? 1 : 0

  if (enabled === 1) {
    // 开启时弹确认框
    try {
      await ElMessageBox.confirm(
        '开启 AI 分析功能后，主机取证数据（包括进程、网络、注册表、日志等敏感信息）将发送至您配置的外部 AI 大模型服务进行深度分析。\n\n请注意：\n1. 数据将通过互联网传输至第三方 AI 服务\n2. 请确保您已获得合规授权\n3. 请确保 AI 服务提供商的数据安全政策可信\n\n是否确认开启？',
        '⚠️ 安全确认',
        {
          confirmButtonText: '确认开启',
          cancelButtonText: '取消',
          type: 'warning',
          dangerouslyUseHTMLString: false,
        }
      )
    } catch {
      return // 用户取消
    }
  }

  toggleLoading.value = true
  try {
    const res = await toggleAi(enabled)
    config.value = res.data
    ElMessage.success(enabled === 1 ? 'AI 分析功能已开启' : 'AI 分析功能已关闭')
  } catch (error) {
    ElMessage.error(error.response?.data?.message || '操作失败')
  } finally {
    toggleLoading.value = false
  }
}

async function handleSave() {
  if (!form.api_base_url) {
    ElMessage.warning('请输入 API Base URL')
    return
  }
  if (!form.api_key && !(config.value && config.value.api_key_masked)) {
    ElMessage.warning('请输入 API Key')
    return
  }

  saveLoading.value = true
  try {
    const data = {
      api_base_url: form.api_base_url,
      model_name: form.model_name,
      max_tokens: form.max_tokens,
      temperature: form.temperature,
      system_prompt: form.system_prompt,
      enabled: config.value?.enabled || 0
    }
    // 只在用户输入了新Key时才发送
    if (form.api_key) {
      data.api_key = form.api_key
    } else if (!config.value?.api_key_masked) {
      ElMessage.warning('请输入 API Key')
      return
    }

    const res = await saveAiConfig(data)
    config.value = res.data
    form.api_key = '' // 清空，不保留明文
    ElMessage.success('AI 配置已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.message || '保存失败')
  } finally {
    saveLoading.value = false
  }
}

function handleReset() {
  if (config.value) {
    form.api_base_url = config.value.api_base_url || ''
    form.model_name = config.value.model_name || 'gpt-4o'
    form.max_tokens = config.value.max_tokens || 4096
    form.temperature = config.value.temperature || 0.3
    form.system_prompt = config.value.system_prompt || ''
    form.api_key = ''
  } else {
    form.api_base_url = ''
    form.api_key = ''
    form.model_name = 'gpt-4o'
    form.max_tokens = 4096
    form.temperature = 0.3
    form.system_prompt = ''
  }
}
</script>

<style scoped>
.switch-label {
  font-size: 14px;
  color: #303133;
  margin-right: 10px;
}
.ml-10 {
  margin-left: 10px;
}
.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.form-tip code {
  color: #E6A23C;
  background: #fdf6ec;
  padding: 2px 6px;
  border-radius: 3px;
}
</style>
