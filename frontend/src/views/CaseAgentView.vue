<template>
  <div class="case-agent-view">
    <div class="page-header">
      <div class="title-wrap">
        <h2>主机 Agent</h2>
        <span class="scope-tag" v-if="selectedCaseId === 'ALL'">全平台</span>
        <span class="scope-tag case" v-else-if="selectedCase">{{ selectedCase.name }}</span>
      </div>
      <el-select
        v-model="selectedCaseId"
        placeholder="请选择案件"
        class="case-select"
        filterable
        clearable
        @change="onCaseChange"
      >
        <el-option label="全部案件（全平台）" value="ALL" />
        <el-option
          v-for="c in caseOptions"
          :key="c.id"
          :label="c.name"
          :value="c.id"
        />
      </el-select>
    </div>

    <!-- 未选择案件：空态提示（案件维度收敛） -->
    <el-empty
      v-if="selectedCaseId === ''"
      description="请选择案件以查看其主机 Agent；或选择「全部案件（全平台）」查看全平台"
    />

    <template v-else>
      <!-- 统计卡片 -->
      <div class="stats-cards">
        <SettingsStatCard label="Agent 总数" :value="stats.total" :icon="Monitor" />
        <SettingsStatCard label="在线" :value="stats.online" :icon="CircleCheck" />
        <SettingsStatCard label="离线" :value="stats.offline" :icon="CircleClose" />
      </div>

      <!-- Agent 列表 -->
      <el-table :data="agentList" border stripe style="width: 100%" v-loading="loading">
        <el-table-column label="主机名" min-width="150">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="goHostDetail(row)">
              {{ row.hostname }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column prop="agent_version" label="Agent 版本" width="120" />
        <el-table-column prop="os_type" label="操作系统" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span :class="['status-dot', row.status === 'online' ? 'online' : 'offline']" />
            <span class="status-text">
              {{ row.status === 'online' ? '在线' : '离线' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="心跳时间" width="160">
          <template #default="{ row }">
            {{ row.last_heartbeat ? relativeTime(row.last_heartbeat) : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="ip_address" label="IP 地址" width="140" />
        <el-table-column label="操作" width="180" align="center">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="goHostDetail(row)">
              查看详情
            </el-button>
            <el-button type="primary" link size="small" @click="handleGenerateToken(row)">
              {{ row.token_set ? '重置 Token' : '生成 Token' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @size-change="fetchAgents"
          @current-change="fetchAgents"
        />
      </div>
    </template>

    <!-- 生成/重置 Token 结果弹窗：明文仅此一次展示，可复制部署命令 -->
    <el-dialog v-model="tokenDialogVisible" title="Agent Token" width="560px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="Token 仅本次生成时可见，关闭弹窗后不可再次查看；重置后旧 Token 立即失效"
        style="margin-bottom: 16px"
      />
      <div class="token-field">
        <div class="field-label">Token</div>
        <el-input :model-value="currentToken" readonly>
          <template #append>
            <el-button @click="copyToken">复制 Token</el-button>
          </template>
        </el-input>
      </div>
      <div class="token-field">
        <div class="field-label">部署命令</div>
        <el-input :model-value="deployCommand" readonly type="textarea" :rows="3" />
        <div class="command-actions">
          <el-button type="primary" @click="copyDeployCommand">复制部署命令</el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="tokenDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { parseServerTime } from '@/utils/time'
import { Monitor, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import agentApi from '@/api/agent'
import casesApi from '@/api/cases'
import SettingsStatCard from '@/components/settings/SettingsStatCard.vue'

// '' = 未选择（空态）；'ALL' = 全平台；数字 = 具体案件
const selectedCaseId = ref('')
const caseOptions = ref([])
const selectedCase = computed(() => caseOptions.value.find((c) => c.id === selectedCaseId.value) || null)

const router = useRouter()
function goHostDetail(row) {
  if (row?.host_id) router.push(`/hosts/${row.host_id}`)
}

const loading = ref(false)
const agentList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const stats = ref({ total: 0, online: 0, offline: 0 })

// Token 弹窗状态
const tokenDialogVisible = ref(false)
const currentToken = ref('')
const deployCommand = ref('')

function caseIdParam() {
  // 仅具体案件时传 case_id；'ALL' 与不传等价（全平台）
  return selectedCaseId.value === 'ALL' ? undefined : selectedCaseId.value
}

async function loadCaseOptions() {
  try {
    // 案件下拉框拉取全量；后端 GET /cases 的 size 上限为 100，不能超过
    const res = await casesApi.list(1, 100, '')
    const data = res.data || {}
    caseOptions.value = data.items || []
  } catch (e) {
    console.error('获取案件列表失败', e)
  }
}

function onCaseChange() {
  currentPage.value = 1
  if (selectedCaseId.value === '') {
    agentList.value = []
    stats.value = { total: 0, online: 0, offline: 0 }
    return
  }
  fetchAgents()
  fetchStats()
}

async function fetchAgents() {
  if (selectedCaseId.value === '') return
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    const cid = caseIdParam()
    if (cid !== undefined) params.case_id = cid
    const res = await agentApi.agents.list(params)
    agentList.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取 Agent 列表失败', e)
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  if (selectedCaseId.value === '') return
  try {
    const cid = caseIdParam()
    const res = await agentApi.stats.getAgentStats(cid !== undefined ? { case_id: cid } : undefined)
    stats.value = res.data || { total: 0, online: 0, offline: 0 }
  } catch (e) {
    console.error('获取 Agent 统计失败', e)
  }
}

function relativeTime(val) {
  if (!val) return '—'
  const now = Date.now()
  const t = parseServerTime(val).getTime()
  const diff = Math.floor((now - t) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

function buildServerBase() {
  let origin = window.location.origin || 'http://localhost'
  try {
    const url = new URL(origin)
    url.port = '8000'
    return url.origin
  } catch (e) {
    return `${origin}:8000`
  }
}

function buildDeployCommand(hostId, token) {
  return `python agent.py --daemon --server ${buildServerBase()} --token ${token} --daemon-id ${hostId}`
}

async function handleGenerateToken(row) {
  try {
    const res = await agentApi.agents.generateToken(row.host_id)
    const data = res.data || {}
    currentToken.value = data.token || ''
    deployCommand.value = buildDeployCommand(row.host_id, currentToken.value)
    tokenDialogVisible.value = true
    row.token_set = true
    row.token_created_at = data.token_created_at || row.token_created_at
    ElMessage.success('Token 生成成功')
  } catch (e) {
    ElMessage.error('Token 生成失败，请重试')
  }
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 回退方案
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const success = document.execCommand('copy')
    document.body.removeChild(ta)
    return success
  } catch {
    return false
  }
}

async function copyToken() {
  const ok = await copyText(currentToken.value)
  ElMessage.success(ok ? 'Token 已复制' : '复制失败，请手动复制')
}

async function copyDeployCommand() {
  const ok = await copyText(deployCommand.value)
  ElMessage.success(ok ? '部署命令已复制' : '复制失败，请手动复制')
}

onMounted(() => {
  loadCaseOptions()
})
</script>

<style scoped>
.case-agent-view {
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  gap: 16px;
}

.title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}

.scope-tag {
  font-size: 12px;
  font-weight: 500;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-muted, #555555);
}

.scope-tag.case {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
}

.case-select {
  width: 280px;
}

.stats-cards {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 8px;
  vertical-align: middle;
}

.status-dot.online {
  background: var(--color-success-fg, #16a34a);
}

.status-dot.offline {
  background: var(--color-fg-light, #a3a3a3);
}

.status-text {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  vertical-align: middle;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.token-field {
  margin-bottom: 16px;
}

.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
  margin-bottom: 6px;
}

.command-actions {
  margin-top: 8px;
  text-align: right;
}
</style>
