<template>
  <div class="page-container">
    <!-- 案件信息 -->
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">案件详情</h2>
        <el-button @click="$router.push('/')">
          <el-icon><Back /></el-icon> 返回
        </el-button>
      </div>
      <el-descriptions :column="2" border v-loading="loading">
        <el-descriptions-item label="案件名称">{{ caseData?.name }}</el-descriptions-item>
        <el-descriptions-item label="案件编号">{{ caseData?.case_number || '未分配' }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="caseData?.status === 'open' ? 'success' : 'info'" size="small">
            {{ caseData?.status === 'open' ? '进行中' : '已关闭' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ caseData?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">{{ caseData?.description || '无' }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 主机列表 -->
    <div class="card-box">
      <div class="flex-between mb-20">
        <h3>主机列表</h3>
        <div>
          <el-button type="success" @click="agentDialogRef?.show()">
            <el-icon><Download /></el-icon> 下载 Agent
          </el-button>
          <el-button type="primary" @click="showAddHostDialog">
            <el-icon><Plus /></el-icon> 添加主机
          </el-button>
        </div>
      </div>
      <el-table :data="hosts" border stripe v-loading="hostsLoading">
        <el-table-column prop="hostname" label="主机名" min-width="120" />
        <el-table-column prop="ip_address" label="IP 地址" width="140" />
        <el-table-column prop="os_type" label="系统类型" width="100" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="agent_version" label="Agent版本" width="100" />
        <el-table-column prop="collection_time" label="采集时间" width="180" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="goToHost(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 添加主机对话框 -->
    <el-dialog v-model="addHostDialogVisible" title="添加主机" width="500px">
      <el-form :model="hostForm" label-width="80px">
        <el-form-item label="主机名" required>
          <el-input v-model="hostForm.hostname" placeholder="请输入主机名" />
        </el-form-item>
        <el-form-item label="IP 地址">
          <el-input v-model="hostForm.ip_address" placeholder="如 192.168.1.100" />
        </el-form-item>
        <el-form-item label="系统类型">
          <el-select v-model="hostForm.os_type" placeholder="选择系统类型">
            <el-option label="Windows" value="windows" />
            <el-option label="Linux" value="linux" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统版本">
          <el-input v-model="hostForm.os_version" placeholder="如 Windows 10 Pro" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addHostDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="handleAddHost">添加</el-button>
      </template>
    </el-dialog>

    <AgentDownloadDialog ref="agentDialogRef" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import casesApi from '@/api/cases'
import hostsApi from '@/api/hosts'
import AgentDownloadDialog from '@/components/AgentDownloadDialog.vue'

const route = useRoute()
const router = useRouter()

const caseData = ref(null)
const loading = ref(false)
const hosts = ref([])
const hostsLoading = ref(false)

const addHostDialogVisible = ref(false)
const adding = ref(false)
const hostForm = reactive({
  hostname: '',
  ip_address: '',
  os_type: 'windows',
  os_version: ''
})

const agentDialogRef = ref(null)

onMounted(() => {
  loadCase()
  loadHosts()
})

async function loadCase() {
  loading.value = true
  try {
    const res = await casesApi.get(route.params.id)
    caseData.value = res.data
  } catch (error) {
    // handled
  } finally {
    loading.value = false
  }
}

async function loadHosts() {
  hostsLoading.value = true
  try {
    const res = await hostsApi.listByCase(route.params.id)
    hosts.value = res.data
  } catch (error) {
    // handled
  } finally {
    hostsLoading.value = false
  }
}

function showAddHostDialog() {
  hostForm.hostname = ''
  hostForm.ip_address = ''
  hostForm.os_type = 'windows'
  hostForm.os_version = ''
  addHostDialogVisible.value = true
}

async function handleAddHost() {
  if (!hostForm.hostname) {
    ElMessage.warning('请输入主机名')
    return
  }
  adding.value = true
  try {
    await hostsApi.create(route.params.id, { ...hostForm })
    ElMessage.success('主机添加成功')
    addHostDialogVisible.value = false
    loadHosts()
  } catch (error) {
    // handled
  } finally {
    adding.value = false
  }
}

function goToHost(id) {
  router.push(`/hosts/${id}`)
}

function statusType(status) {
  const map = {
    pending: 'info',
    imported: 'warning',
    analyzed: 'success'
  }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = {
    pending: '待采集',
    imported: '已导入',
    analyzed: '已分析'
  }
  return map[status] || status
}
</script>
