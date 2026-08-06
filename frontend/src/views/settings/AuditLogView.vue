<template>
  <div class="audit-log-view">
    <div class="page-header">
      <h2>审计日志</h2>
    </div>

    <!-- 筛选区域 -->
    <div class="filter-bar">
      <el-select v-model="filterUser" placeholder="用户" clearable style="width: 160px" @change="fetchLogs">
        <el-option
          v-for="u in userOptions"
          :key="u.id"
          :label="u.username"
          :value="u.id"
        />
      </el-select>
      <el-select v-model="filterAction" placeholder="操作类型" clearable style="width: 160px" @change="fetchLogs">
        <el-option
          v-for="a in actionTypes"
          :key="a"
          :label="actionLabel(a)"
          :value="a"
        />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="datetimerange"
        range-separator="至"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        style="width: 360px"
        @change="fetchLogs"
      />
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="danger" plain @click="handleCleanup">清理过期日志</el-button>
    </div>

    <!-- 统计 -->
    <div class="stats-bar">
      <span>总记录数：<strong>{{ total }}</strong></span>
      <span>保留天数：<strong>{{ retentionDays }}</strong> 天</span>
    </div>

    <!-- 日志列表 -->
    <el-table :data="logList" border stripe style="width: 100%" v-loading="loading">
      <el-table-column label="时间" width="170">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="120" />
      <el-table-column label="操作类型" width="140">
        <template #default="{ row }">
          <el-tag :type="actionColor(row.action_type)" size="small">
            {{ actionLabel(row.action_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
      <el-table-column prop="target_type" label="目标类型" width="100" />
      <el-table-column prop="ip_address" label="IP 地址" width="140" />
    </el-table>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @size-change="fetchLogs"
        @current-change="fetchLogs"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAuditLogs, cleanupAuditLogs, getAuditLogActionTypes } from '@/api/auditLogs'

const loading = ref(false)
const logList = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

// 筛选
const filterUser = ref(null)
const filterAction = ref(null)
const dateRange = ref(null)
const userOptions = ref([])
const actionTypes = ref([])
const retentionDays = ref(90)

function actionLabel(action) {
  const map = {
    login: '登录',
    logout: '退出',
    rule_change: '规则变更',
    event_dispose: '事件处置',
    ai_analysis: 'AI 分析',
    settings_change: '系统设置变更',
    user_manage: '用户管理',
  }
  return map[action] || action
}

/**
 * 操作类型标签配色。
 * 审计日志仅承载"记录"语义，不承载状态语义，因此所有操作类型统一使用
 * 中性灰标签（info），避免彩色标签造成的视觉噪音与语义误导。
 * 注意：仅改变配色，标签文字（含"AI 分析"）保持原样，与后端枚举一致。
 * @param {string} action 操作类型枚举值
 * @returns {string} Element Plus tag type
 */
function actionColor(action) {
  void action
  return 'info'
}

function formatTime(val) {
  if (!val) return ''
  const d = new Date(val)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function fetchLogs() {
  loading.value = true
  try {
    const params = { page: currentPage.value, page_size: pageSize.value }
    if (filterUser.value) params.user_id = filterUser.value
    if (filterAction.value) params.action_type = filterAction.value
    if (dateRange.value && dateRange.value.length === 2) {
      params.start_time = dateRange.value[0].toISOString()
      params.end_time = dateRange.value[1].toISOString()
    }
    const res = await getAuditLogs(params)
    logList.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取审计日志失败', e)
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filterUser.value = null
  filterAction.value = null
  dateRange.value = null
  currentPage.value = 1
  fetchLogs()
}

async function handleCleanup() {
  try {
    await ElMessageBox.confirm('确定要清理过期审计日志吗？此操作不可撤销。', '确认清理', {
      confirmButtonText: '确定清理',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const res = await cleanupAuditLogs()
    ElMessage.success(`已清理 ${res.data.deleted} 条过期记录（保留 ${res.data.retention_days} 天）`)
    fetchLogs()
  } catch (e) {
    if (e !== 'cancel') console.error('清理失败', e)
  }
}

onMounted(async () => {
  fetchLogs()
  try {
    const typesRes = await getAuditLogActionTypes()
    actionTypes.value = typesRes.data || []
  } catch (e) {
    // ignore
  }
  // 尝试从系统参数读取保留天数
  try {
    const { getSystemSettings } = await import('@/api/settings')
    const settingsRes = await getSystemSettings()
    const found = (settingsRes.data || []).find(s => s.key === 'log_retention_days')
    if (found) retentionDays.value = parseInt(found.value) || 90
  } catch (e) {
    // 默认值
  }
})
</script>

<style scoped>
.audit-log-view {
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

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.stats-bar {
  display: flex;
  gap: 24px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--color-fg-muted, #6b7280);
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
