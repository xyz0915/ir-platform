<template>
  <div class="agent-management">
    <div class="page-header">
      <h2>主机 Agent</h2>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-cards">
      <SettingsStatCard label="Agent 总数" :value="stats.total" :icon="Monitor" />
      <SettingsStatCard label="在线" :value="stats.online" :icon="CircleCheck" />
      <SettingsStatCard label="离线" :value="stats.offline" :icon="CircleClose" />
    </div>

    <!-- Agent 列表 -->
    <el-table :data="agentList" border stripe style="width: 100%" v-loading="loading">
      <el-table-column prop="hostname" label="主机名" min-width="150" />
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
      <el-table-column label="操作" width="140" align="center">
        <template #default="{ row }">
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
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { parseServerTime } from '@/utils/time'
import { Monitor, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import agentApi from '@/api/agent'
import SettingsStatCard from '@/components/settings/SettingsStatCard.vue'

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

function relativeTime(val) {
  if (!val) return '—'
  const now = Date.now()
  // 后端时间字段为 UTC 纯字符串（如 "2026-08-08 00:30:00"），必须用 parseServerTime 按 UTC 解析
  // 否则会被浏览器当本地时间渲染，UTC+8 下恒差 8 小时
  const t = parseServerTime(val).getTime()
  const diff = Math.floor((now - t) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

async function fetchAgents() {
  loading.value = true
  try {
    const res = await agentApi.agents.list({ page: currentPage.value, page_size: pageSize.value })
    agentList.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取 Agent 列表失败', e)
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await agentApi.stats.getAgentStats()
    stats.value = res.data || { total: 0, online: 0, offline: 0 }
  } catch (e) {
    console.error('获取 Agent 统计失败', e)
  }
}

// ── 生成/重置 Token ──
function buildServerBase() {
  // 取「当前页面访问地址的 origin + :8000」；若 origin 不含端口，则拼 8000
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

// 复制文本：优先 Clipboard API，失败则回退到临时 textarea + execCommand
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 继续走回退方案
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
  fetchAgents()
  fetchStats()
})
</script>

<style scoped>
.agent-management {
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}

.stats-cards {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

/* 状态点：在线使用真实状态色（低饱和），离线使用中性灰，不再使用彩色文字 */
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

/* Token 弹窗 */
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
