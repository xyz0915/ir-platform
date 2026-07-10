<template>
  <div class="ti-config">
    <div class="card-box">
      <h2 class="page-title">威胁情报外联配置</h2>

      <el-row :gutter="20">
        <!-- 运行策略 -->
        <el-col :span="10">
          <el-card shadow="never" class="mb-16">
            <template #header><b>运行策略</b></template>
            <el-form :model="settings" label-width="150px" size="small">
              <el-form-item label="回灌到规则引擎">
                <el-switch v-model="settings.enable_enrichment_feedback" />
              </el-form-item>
              <el-form-item label="自动外联扫描">
                <el-switch v-model="settings.auto_enrichment" />
                <span class="hint">（False 时调度器不动作，推荐用 --once + cron）</span>
              </el-form-item>
              <el-form-item label="每日配额">
                <el-input-number v-model="settings.daily_quota" :min="0" :max="100000" />
              </el-form-item>
              <el-form-item label="重新检查间隔(天)">
                <el-input-number v-model="settings.recheck_days" :min="1" :max="3650" />
              </el-form-item>
              <el-form-item label="调度间隔(秒)">
                <el-input-number v-model="settings.scheduler_interval" :min="1" :max="86400" />
              </el-form-item>
              <el-form-item label="限流(QPS)">
                <el-input-number v-model="settings.rate_limit_qps" :min="1" :max="100" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="savingSettings" @click="saveSettings">保存策略</el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </el-col>

        <!-- Provider 管理 -->
        <el-col :span="14">
          <el-card shadow="never" class="mb-16">
            <template #header>
              <div class="flex-between">
                <b>Provider 管理</b>
                <el-button type="primary" size="small" @click="openProviderForm(null)">新增 Provider</el-button>
              </div>
            </template>
            <el-table :data="providers" border size="small" v-loading="loadingProviders">
              <el-table-column prop="name" label="名称" width="120" />
              <el-table-column prop="type" label="类型" width="100" />
              <el-table-column prop="base_url" label="Base URL" min-width="180" show-overflow-tooltip />
              <el-table-column label="启用" width="70">
                <template #default="{ row }">
                  <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                    {{ row.enabled ? '是' : '否' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template #default="{ row }">
                  <el-button type="primary" link size="small" @click="openProviderForm(row)">编辑</el-button>
                  <el-popconfirm title="确认删除该 Provider？" @confirm="deleteProvider(row)">
                    <template #reference>
                      <el-button type="danger" link size="small">删除</el-button>
                    </template>
                  </el-popconfirm>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- Provider 表单对话框 -->
    <el-dialog
      v-model="showProviderDialog"
      :title="editingProvider ? '编辑 Provider' : '新增 Provider'"
      width="560px"
      destroy-on-close
    >
      <el-form :model="providerForm" label-width="140px" size="small">
        <el-form-item label="名称">
          <el-input v-model="providerForm.name" :disabled="!!editingProvider" placeholder="如 threatbook" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="providerForm.type" placeholder="选择类型">
            <el-option label="threatbook（微步）" value="threatbook" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="providerForm.base_url" placeholder="https://api.threatbook.cn" />
        </el-form-item>
        <el-form-item label="API Key 引用">
          <el-input
            v-model="providerForm.api_key_ref"
            placeholder="$ENV_VAR（如 $THREATBOOK_KEY，运行时从环境变量展开，不落明文）"
          />
          <span class="hint">仅填写环境变量名（以 $ 开头），密钥本身不存储、不返回前端。</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="providerForm.enabled" />
        </el-form-item>
        <el-form-item label="限流(QPS)">
          <el-input-number v-model="providerForm.rate_limit_qps" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="IP 端点">
          <el-input v-model="providerForm.ipEndpoint" placeholder="/v3/scene/ip" />
        </el-form-item>
        <el-form-item label="域名端点">
          <el-input v-model="providerForm.domainEndpoint" placeholder="/v3/domain/adv" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showProviderDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingProvider" @click="saveProvider">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import iocApi from '@/api/iocs'

const providers = ref([])
const loadingProviders = ref(false)
const showProviderDialog = ref(false)
const editingProvider = ref(null)
const savingProvider = ref(false)

const providerForm = ref({
  name: '',
  type: 'threatbook',
  base_url: '',
  api_key_ref: '',
  enabled: true,
  rate_limit_qps: 2,
  ipEndpoint: '/v3/scene/ip',
  domainEndpoint: '/v3/domain/adv'
})

const settings = ref({
  enable_enrichment_feedback: true,
  auto_enrichment: false,
  daily_quota: 1000,
  recheck_days: 30,
  scheduler_interval: 3600,
  rate_limit_qps: 2
})
const savingSettings = ref(false)

onMounted(() => {
  loadProviders()
  loadSettings()
})

async function loadProviders() {
  loadingProviders.value = true
  try {
    const res = await iocApi.getProviders()
    providers.value = res.data || []
  } catch (error) {
    // handled by interceptor
  } finally {
    loadingProviders.value = false
  }
}

async function loadSettings() {
  try {
    const res = await iocApi.getSettings()
    if (res.data) {
      settings.value = { ...settings.value, ...res.data }
    }
  } catch (error) {
    // handled by interceptor
  }
}

async function saveSettings() {
  savingSettings.value = true
  try {
    await iocApi.updateSettings({ ...settings.value })
    ElMessage.success('策略已保存')
  } catch (error) {
    // handled by interceptor
  } finally {
    savingSettings.value = false
  }
}

function openProviderForm(row) {
  editingProvider.value = row
  if (row) {
    const eps = row.endpoints || {}
    providerForm.value = {
      name: row.name,
      type: row.type || 'threatbook',
      base_url: row.base_url,
      api_key_ref: '',
      enabled: !!row.enabled,
      rate_limit_qps: row.rate_limit_qps || 2,
      ipEndpoint: eps.ip || '/v3/scene/ip',
      domainEndpoint: eps.domain || '/v3/domain/adv'
    }
  } else {
    providerForm.value = {
      name: '',
      type: 'threatbook',
      base_url: '',
      api_key_ref: '',
      enabled: true,
      rate_limit_qps: 2,
      ipEndpoint: '/v3/scene/ip',
      domainEndpoint: '/v3/domain/adv'
    }
  }
  showProviderDialog.value = true
}

async function saveProvider() {
  if (!providerForm.value.name || !providerForm.value.base_url) {
    ElMessage.warning('请填写名称和 Base URL')
    return
  }
  savingProvider.value = true
  const payload = {
    name: providerForm.value.name,
    type: providerForm.value.type,
    base_url: providerForm.value.base_url,
    api_key_ref: providerForm.value.api_key_ref || '',
    enabled: providerForm.value.enabled,
    rate_limit_qps: providerForm.value.rate_limit_qps,
    endpoints: {
      ip: providerForm.value.ipEndpoint || '/v3/scene/ip',
      domain: providerForm.value.domainEndpoint || '/v3/domain/adv'
    }
  }
  try {
    await iocApi.upsertProvider(payload)
    ElMessage.success('Provider 已保存')
    showProviderDialog.value = false
    loadProviders()
  } catch (error) {
    // handled by interceptor
  } finally {
    savingProvider.value = false
  }
}

async function deleteProvider(row) {
  try {
    await iocApi.deleteProvider(row.name)
    ElMessage.success(`Provider '${row.name}' 已删除`)
    loadProviders()
  } catch (error) {
    // handled by interceptor
  }
}
</script>

<style scoped>
.ti-config {
  padding: 0;
}
.card-box {
  background: #fff;
  border-radius: 4px;
  padding: 20px;
}
.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.page-title {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
  margin: 0 0 16px;
}
.hint {
  color: #909399;
  font-size: 12px;
  margin-left: 8px;
}
</style>
