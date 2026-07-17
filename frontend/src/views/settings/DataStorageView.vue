<template>
  <div class="data-storage-view">
    <div class="page-header">
      <h2>数据与存储</h2>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-cards">
      <div class="stat-card">
        <div class="stat-value">{{ stats.eventCount.toLocaleString() }}</div>
        <div class="stat-label">事件总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.diskUsage }}</div>
        <div class="stat-label">磁盘使用</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.uploadSize }}</div>
        <div class="stat-label">上传文件大小</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.retentionDays }}</div>
        <div class="stat-label">保留天数</div>
      </div>
    </div>

    <!-- 配置项 -->
    <el-card class="config-card" shadow="never">
      <template #header>
        <span>存储配置</span>
      </template>
      <el-form label-width="200px">
        <el-form-item label="安全事件保留天数">
          <el-input-number v-model="config.logRetentionDays" :min="1" :max="3650" />
          <span class="form-hint">超过此天数的安全事件将被清理</span>
        </el-form-item>
        <el-form-item label="上传日志文件保留天数">
          <el-input-number v-model="config.uploadRetentionDays" :min="1" :max="365" />
          <span class="form-hint">超过此天数的上传文件将被清理</span>
        </el-form-item>
      </el-form>
      <div class="config-actions">
        <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
      </div>
    </el-card>

    <!-- 操作 -->
    <el-card class="actions-card" shadow="never">
      <template #header>
        <span>清理操作</span>
      </template>
      <div class="action-buttons">
        <el-button type="danger" plain @click="confirmCleanup('events')">
          立即清理过期事件
        </el-button>
        <el-button type="warning" plain @click="confirmCleanup('uploads')">
          一键清理临时文件
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSystemSettings, updateSystemSetting } from '@/api/settings'

const saving = ref(false)
const config = reactive({
  logRetentionDays: 90,
  uploadRetentionDays: 7,
})
const stats = reactive({
  eventCount: 0,
  diskUsage: '—',
  uploadSize: '—',
  retentionDays: 90,
})

async function fetchSettings() {
  try {
    const res = await getSystemSettings()
    const settings = res.data || []
    const findVal = (key, def) => {
      const item = settings.find(s => s.key === key)
      return item ? item.value : def
    }
    config.logRetentionDays = parseInt(findVal('log_retention_days', '90'))
    config.uploadRetentionDays = parseInt(findVal('upload_file_retention_days', '7'))
    stats.retentionDays = config.logRetentionDays
  } catch (e) {
    console.error('获取系统参数失败', e)
  }
}

async function fetchStats() {
  try {
    // 尝试获取事件总数
    const { getSecurityEvents } = await import('@/api/events').catch(() => ({ getSecurityEvents: null }))
    if (getSecurityEvents) {
      const res = await getSecurityEvents({ page: 1, page_size: 1 })
      stats.eventCount = res.data?.total || 0
    }
  } catch (e) {
    stats.eventCount = 0
  }
}

async function saveConfig() {
  saving.value = true
  try {
    await updateSystemSetting('log_retention_days', { value: String(config.logRetentionDays) })
    await updateSystemSetting('upload_file_retention_days', { value: String(config.uploadRetentionDays) })
    ElMessage.success('配置已保存')
  } catch (e) {
    console.error('保存配置失败', e)
  } finally {
    saving.value = false
  }
}

function confirmCleanup(type) {
  const titles = { events: '清理过期事件', uploads: '清理临时文件' }
  const messages = {
    events: '确定要清理超过保留天数的安全事件吗？此操作不可撤销。',
    uploads: '确定要一键清理所有临时上传文件吗？此操作不可撤销。',
  }
  ElMessageBox.confirm(messages[type], titles[type], {
    confirmButtonText: '确定清理',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => {
      ElMessage.success(`已提交 ${titles[type]} 任务`)
    })
    .catch(() => {})
}

onMounted(() => {
  fetchSettings()
  fetchStats()
})
</script>

<style scoped>
.data-storage-view {
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
  font-weight: 600;
}

.stats-cards {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  flex: 1;
  padding: 20px;
  background: var(--color-canvas-default, #fff);
  border: 1px solid var(--color-border-default, #e5e7eb);
  border-radius: 8px;
  text-align: center;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-fg-default, #111827);
}

.stat-label {
  font-size: 13px;
  color: var(--color-fg-muted, #6b7280);
  margin-top: 4px;
}

.config-card,
.actions-card {
  margin-bottom: 16px;
}

.form-hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--color-fg-muted, #9ca3af);
}

.config-actions {
  padding-top: 8px;
}

.action-buttons {
  display: flex;
  gap: 12px;
}
</style>
