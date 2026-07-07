<template>
  <el-card shadow="never" class="profile-card">
    <template #header>
      <span class="card-title">主机画像</span>
    </template>
    <div v-if="profile">
      <!-- 系统摘要 -->
      <el-descriptions :column="2" border size="small" class="mb-20">
        <el-descriptions-item label="主机名">{{ systemSummary.hostname || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="操作系统">{{ systemSummary.os || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="系统版本">{{ systemSummary.os_version || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="架构">{{ systemSummary.architecture || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="时区">{{ systemSummary.timezone || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="运行时间">{{ formatUptime(systemSummary.uptime_seconds) }}</el-descriptions-item>
      </el-descriptions>

      <!-- CPU 信息 -->
      <el-descriptions :column="3" border size="small" class="mb-20" title="CPU">
        <el-descriptions-item label="型号">{{ cpuInfo.model || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="物理核心">{{ cpuInfo.cores || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="逻辑核心">{{ cpuInfo.logical_cores || 'N/A' }}</el-descriptions-item>
      </el-descriptions>

      <!-- 内存信息 -->
      <el-descriptions :column="2" border size="small" class="mb-20" title="内存">
        <el-descriptions-item label="总量">{{ memoryInfo.total_gb || 'N/A' }} GB</el-descriptions-item>
        <el-descriptions-item label="可用">{{ memoryInfo.available_gb || 'N/A' }} GB</el-descriptions-item>
      </el-descriptions>

      <!-- 磁盘信息 -->
      <div v-if="diskInfo.length" class="mb-20">
        <div class="section-label">磁盘</div>
        <el-table :data="diskInfo" size="small" border>
          <el-table-column prop="device" label="设备" />
          <el-table-column prop="total_gb" label="总量(GB)" />
          <el-table-column prop="free_gb" label="可用(GB)" />
          <el-table-column prop="fs_type" label="文件系统" />
        </el-table>
      </div>

      <!-- 用户账户 -->
      <div v-if="userAccounts.length" class="mb-20">
        <div class="section-label">用户账户</div>
        <el-table :data="userAccounts" size="small" border>
          <el-table-column prop="username" label="用户名" />
          <el-table-column prop="uid" label="UID" width="80" />
          <el-table-column label="管理员" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_admin ? 'danger' : 'info'" size="small">
                {{ row.is_admin ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="禁用" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_disabled ? 'warning' : 'success'" size="small">
                {{ row.is_disabled ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="last_logon" label="最后登录" />
        </el-table>
      </div>

      <!-- 安全产品 -->
      <div v-if="securityProducts.length">
        <div class="section-label">安全产品</div>
        <el-table :data="securityProducts" size="small" border>
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
      </div>
    </div>
    <el-empty v-else description="暂无画像数据" />
  </el-card>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  profile: { type: Object, default: null }
})

function parseJson(str) {
  if (!str) return {}
  if (typeof str === 'object') return str
  try { return JSON.parse(str) } catch { return {} }
}

const systemSummary = computed(() => parseJson(props.profile?.system_summary))
const cpuInfo = computed(() => parseJson(props.profile?.cpu_info))
const memoryInfo = computed(() => parseJson(props.profile?.memory_info))
const diskInfo = computed(() => parseJson(props.profile?.disk_info) || [])
const userAccounts = computed(() => parseJson(props.profile?.user_accounts) || [])
const securityProducts = computed(() => parseJson(props.profile?.security_products) || [])

function formatUptime(seconds) {
  if (!seconds) return 'N/A'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  return `${days}天 ${hours}小时`
}
</script>

<style scoped>
.profile-card {
  margin-bottom: 20px;
}

.card-title {
  font-weight: bold;
  font-size: 16px;
}

.section-label {
  font-weight: bold;
  margin-bottom: 10px;
  color: #606266;
}
</style>
