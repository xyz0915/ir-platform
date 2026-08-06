<template>
  <div class="agent-management">
    <div class="page-header">
      <h2>Agent 管理</h2>
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Monitor, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import agentApi from '@/api/agent'
import SettingsStatCard from '@/components/settings/SettingsStatCard.vue'

const loading = ref(false)
const agentList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const stats = ref({ total: 0, online: 0, offline: 0 })

function relativeTime(val) {
  if (!val) return '—'
  const now = Date.now()
  const t = new Date(val).getTime()
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
  background: var(--color-success-fg, #3f8f5b);
}

.status-dot.offline {
  background: var(--color-fg-light, #b0b0b0);
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
</style>
