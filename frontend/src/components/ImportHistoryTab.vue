<template>
  <div>
    <!-- 统计栏 -->
    <div style="display: flex; gap: 16px; margin-bottom: 16px">
      <el-statistic title="总导入数" :value="stats.total" />
      <el-statistic title="成功" :value="stats.success">
        <template #suffix>
          <el-tag type="success" size="small" style="margin-left: 4px">成功</el-tag>
        </template>
      </el-statistic>
      <el-statistic title="失败" :value="stats.failed">
        <template #suffix>
          <el-tag type="danger" size="small" style="margin-left: 4px">失败</el-tag>
        </template>
      </el-statistic>
      <el-statistic title="处理中" :value="stats.processing">
        <template #suffix>
          <el-tag type="warning" size="small" style="margin-left: 4px">处理中</el-tag>
        </template>
      </el-statistic>
    </div>

    <!-- 筛选栏 -->
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
      <div>
        <el-select v-model="typeFilter" placeholder="类型筛选" size="small" style="width: 140px" @change="loadRecords">
          <el-option label="全部" value="" />
          <el-option label="EVTX" value="evtx" />
          <el-option label="Nginx" value="nginx_access" />
          <el-option label="Apache" value="apache_access" />
          <el-option label="IIS" value="iis_access" />
          <el-option label="Tomcat" value="tomcat_access" />
        </el-select>
      </div>
      <el-button size="small" @click="loadRecords">刷新</el-button>
    </div>

    <!-- 表格 -->
    <el-table :data="records" v-loading="loading" stripe size="small" style="width: 100%">
      <el-table-column prop="file_name" label="文件名" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <el-button link type="primary" @click="showDetail(row)">
            {{ row.file_name }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="文件类型" width="120">
        <template #default="{ row }">
          <el-tag :type="logTypeTag(row.log_type)" size="small">
            {{ row.log_type || '未知' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="文件大小" width="100">
        <template #default="{ row }">
          {{ formatFileSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column prop="parsed_count" label="解析条数" width="90" align="center" />
      <el-table-column prop="event_count" label="事件数" width="80" align="center" />
      <el-table-column label="状态" width="140" align="center">
        <template #default="{ row }">
          <template v-if="row.status === 'processing' && row.progress && row.progress.pct !== undefined">
            <el-progress
              :percentage="row.progress.pct"
              :status="row.progress.pct < 100 ? 'warning' : 'success'"
              :stroke-width="14"
              style="width: 110px; margin: 0 auto"
            >
              <span style="font-size: 11px">{{ row.progress.phase || '处理中' }}</span>
            </el-progress>
          </template>
          <template v-else>
            <el-tag
              :type="statusTag(row.status)"
              size="small"
              :class="{ 'status-processing': row.status === 'processing' }"
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="导入时间" width="170" />
      <el-table-column label="操作" width="100" align="center" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="showDetail(row)">查看详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div style="display: flex; justify-content: flex-end; margin-top: 16px">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @change="loadRecords"
      />
    </div>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="detailVisible"
      :title="detailRecord?.file_name || '导入详情'"
      size="600px"
    >
      <template v-if="detailRecord">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="文件名" :span="2">{{ detailRecord.file_name }}</el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ formatFileSize(detailRecord.file_size) }}</el-descriptions-item>
          <el-descriptions-item label="日志类型">
            <el-tag :type="logTypeTag(detailRecord.log_type)" size="small">{{ detailRecord.log_type }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(detailRecord.status)" size="small">{{ statusLabel(detailRecord.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="解析条数">{{ detailRecord.parsed_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="事件数">{{ detailRecord.event_count || 0 }}</el-descriptions-item>
          <el-descriptions-item v-if="detailRecord.error_message" label="错误信息" :span="2">
            <span style="color: var(--el-color-danger)">{{ detailRecord.error_message }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="导入时间" :span="2">{{ detailRecord.created_at }}</el-descriptions-item>
        </el-descriptions>

        <!-- 解析结果明细 -->
        <h4 style="margin: 16px 0 8px">解析结果明细</h4>
        <el-table :data="detailResults" v-loading="detailLoading" stripe size="small" style="width: 100%">
          <el-table-column prop="parsed_line" label="行号" width="70" align="center" />
          <el-table-column prop="log_source" label="来源" width="100" />
          <el-table-column prop="event_type" label="事件类型" width="160" show-overflow-tooltip />
          <el-table-column label="严重度" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="severityTag(row.severity)" size="small">{{ row.severity }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="event_key_hash" label="去重哈希" min-width="160" show-overflow-tooltip />
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getImportRecords, getImportRecordDetail, getImportTaskStatus } from '@/api/importLogs'

const props = defineProps({
  hostId: { type: Number, required: true },
})

const records = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const typeFilter = ref('')

// 详情抽屉
const detailVisible = ref(false)
const detailRecord = ref(null)
const detailResults = ref([])
const detailLoading = ref(false)

// 轮询处理中的记录
let pollTimer = null

// 统计
const stats = computed(() => {
  const all = records.value
  return {
    total: all.length,
    success: all.filter((r) => r.status === 'completed').length,
    failed: all.filter((r) => r.status === 'failed').length,
    processing: all.filter((r) => r.status === 'processing').length,
  }
})

onMounted(() => {
  loadRecords()
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})

async function loadRecords() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    const res = await getImportRecords(props.hostId, params)
    const data = res.data || {}
    records.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error('加载导入记录失败')
    records.value = []
  } finally {
    loading.value = false
  }
}

function startPolling() {
  pollTimer = setInterval(async () => {
    const processingRecords = records.value.filter((r) => r.status === 'processing')
    if (processingRecords.length === 0) return

    for (const rec of processingRecords) {
      try {
        const res = await getImportTaskStatus(props.hostId, rec.id)
        const taskData = res.data || {}
        // 更新本地记录
        const idx = records.value.findIndex((r) => r.id === rec.id)
        if (idx !== -1) {
          records.value[idx] = { ...records.value[idx], ...taskData }
        }
      } catch {
        // 忽略单条轮询失败
      }
    }
  }, 5000) // 每 5 秒
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function showDetail(record) {
  detailRecord.value = record
  detailVisible.value = true
  detailLoading.value = true
  try {
    const res = await getImportRecordDetail(props.hostId, record.id)
    const data = res.data || {}
    detailRecord.value = data.record || record
    detailResults.value = data.results || []
  } catch {
    ElMessage.error('加载导入详情失败')
    detailResults.value = []
  } finally {
    detailLoading.value = false
  }
}

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i]
}

function statusTag(status) {
  const map = { completed: 'success', failed: 'danger', processing: 'warning', pending: 'info' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = {
    completed: '成功',
    failed: '失败',
    processing: '处理中',
    pending: '等待中',
  }
  return map[status] || status
}

function logTypeTag(logType) {
  if (!logType) return 'info'
  if (logType === 'evtx') return 'primary'
  if (logType.includes('nginx')) return 'success'
  if (logType.includes('apache')) return 'warning'
  if (logType.includes('iis')) return ''
  if (logType.includes('tomcat')) return 'danger'
  return 'info'
}

function severityTag(severity) {
  const map = { critical: 'danger', high: 'danger', medium: 'warning', low: 'info', info: 'info' }
  return map[severity] || 'info'
}
</script>

<style scoped>
.status-processing {
  animation: blink 1.5s ease-in-out infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
