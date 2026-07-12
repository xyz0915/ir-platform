<template>
  <div>
    <!-- 顶部筛选栏 -->
    <div class="svc-toolbar">
      <el-input
        v-model="searchText"
        placeholder="搜索服务名..."
        size="small"
        clearable
        style="width: 200px"
      />
      <el-select
        v-model="statusFilter"
        size="small"
        clearable
        placeholder="状态筛选"
        style="width: 130px; margin-left: 8px"
      >
        <el-option label="全部" value="" />
        <el-option label="运行中" value="running" />
        <el-option label="已停止" value="stopped" />
        <el-option label="已暂停" value="paused" />
      </el-select>
      <el-select
        v-if="serviceRisk"
        v-model="riskFilter"
        size="small"
        clearable
        placeholder="风险等级"
        style="width: 130px; margin-left: 8px"
      >
        <el-option label="全部" value="" />
        <el-option label="严重" value="critical" />
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <span class="svc-stats" v-if="serviceRisk">
        {{ enrichedServices.length }} 个服务
        <el-tag v-if="highRiskCount > 0" type="danger" size="small" style="margin-left: 8px">
          {{ highRiskCount }} 个高风险
        </el-tag>
      </span>
      <span class="svc-stats" v-else>
        {{ (data || []).length }} 个服务
      </span>
    </div>

    <!-- 服务表格 -->
    <el-table
      :data="filteredServices"
      border
      stripe
      size="small"
      :row-class-name="rowClassName"
    >
      <el-table-column v-if="serviceRisk" type="expand">
        <template #default="{ row }">
          <div class="svc-expand-detail" v-if="row.detections && row.detections.length">
            <h4>检测详情</h4>
            <div
              v-for="(det, idx) in row.detections"
              :key="idx"
              class="svc-detection-item"
            >
              <el-tag
                :type="det.severity === 'critical' ? 'danger' : det.severity === 'high' ? 'warning' : 'info'"
                size="small"
              >
                {{ det.rule_id }}
              </el-tag>
              <span class="svc-det-rule">{{ det.rule_name }}</span>
              <p class="svc-det-detail">{{ det.detail }}</p>
            </div>
          </div>
          <div v-else class="svc-expand-detail">
            <p style="color: #909399">暂无检测命中</p>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="name" label="服务名" min-width="180" show-overflow-tooltip />

      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'running' ? 'success' : row.status === 'stopped' ? 'danger' : 'info'"
            size="small"
          >
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="start_type" label="启动类型" width="100">
        <template #default="{ row }">
          <el-tag :type="startTypeTagType(row.start_type)" size="small">
            {{ startTypeLabel(row.start_type) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column
        v-if="serviceRisk"
        label="风险评分"
        width="140"
      >
        <template #default="{ row }">
          <el-progress
            v-if="row.risk_score !== undefined"
            :percentage="row.risk_score"
            :color="riskColor(row.risk_score)"
            :stroke-width="14"
            :text-inside="true"
          />
          <span v-else style="color: #909399; font-size: 12px">-</span>
        </template>
      </el-table-column>

      <el-table-column
        v-if="serviceRisk"
        label="检测标签"
        min-width="180"
      >
        <template #default="{ row }">
          <template v-if="row.detections && row.detections.length">
            <el-tag
              v-for="(det, idx) in row.detections"
              :key="idx"
              :type="det.severity === 'critical' ? 'danger' : det.severity === 'high' ? 'warning' : 'info'"
              size="small"
              effect="dark"
              style="margin-right: 4px; margin-bottom: 2px"
            >
              {{ det.rule_name }}
            </el-tag>
          </template>
          <span v-else style="color: #909399; font-size: 12px">-</span>
        </template>
      </el-table-column>

      <el-table-column prop="path" label="路径" min-width="280" show-overflow-tooltip />

      <el-table-column v-if="serviceRisk" prop="user" label="运行账户" width="160" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
  serviceRisk: { type: Object, default: null },
})

const searchText = ref('')
const statusFilter = ref('')
const riskFilter = ref('')

/** 合并服务数据与风险分析结果 */
const enrichedServices = computed(() => {
  const riskMap = {}
  if (props.serviceRisk?.services) {
    for (const s of props.serviceRisk.services) {
      riskMap[s.name.toLowerCase()] = s
    }
  }
  return (props.data || []).map(svc => {
    const risk = riskMap[(svc.name || '').toLowerCase()]
    return { ...svc, ...(risk || {}) }
  })
})

/** 筛选后的服务列表 */
const filteredServices = computed(() => {
  let items = enrichedServices.value

  // 搜索
  const kw = searchText.value.trim().toLowerCase()
  if (kw) {
    items = items.filter(s => (s.name || '').toLowerCase().includes(kw))
  }

  // 状态筛选
  if (statusFilter.value) {
    items = items.filter(s => (s.status || '').toLowerCase() === statusFilter.value.toLowerCase())
  }

  // 风险等级筛选
  if (riskFilter.value) {
    items = items.filter(s => (s.severity_label || '').toLowerCase() === riskFilter.value.toLowerCase())
  }

  return items
})

/** 高风险服务数 */
const highRiskCount = computed(() => {
  return enrichedServices.value.filter(s => (s.risk_score || 0) >= 50).length
})

/** 状态显示标签 */
function statusLabel(status) {
  const map = {
    running: '运行中',
    stopped: '已停止',
    paused: '已暂停',
    unknown: '未知',
  }
  return map[status] || status || '未知'
}

/** 启动类型中文标签 */
function startTypeLabel(startType) {
  const map = {
    auto: '自动',
    'delayed-auto': '延迟自动',
    manual: '手动',
    disabled: '已禁用',
    boot: '引导',
    system: '系统',
  }
  return map[startType] || startType || '未知'
}

/** 启动类型标签颜色 */
function startTypeTagType(startType) {
  const map = {
    auto: 'success',
    'delayed-auto': 'success',
    manual: 'warning',
    disabled: 'info',
    boot: '',
    system: '',
  }
  return map[startType] || 'info'
}

/** 风险评分颜色映射 */
function riskColor(score) {
  if (score >= 70) return '#F56C6C'
  if (score >= 50) return '#E6A23C'
  if (score >= 25) return '#409EFF'
  return '#67C23A'
}

/** 行样式：高风险行高亮 */
function rowClassName({ row }) {
  const score = row.risk_score || 0
  if (score >= 70) return 'svc-row-critical'
  if (score >= 50) return 'svc-row-high'
  return ''
}
</script>

<style scoped>
.svc-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--color-canvas-subtle, #f5f7fa);
  border-radius: 6px;
  border: 1px solid var(--color-border-default, #e4e7ed);
}
.svc-stats {
  margin-left: auto;
  font-size: 13px;
  color: #909399;
}

.svc-expand-detail {
  padding: 12px 20px;
  background: #fafafa;
}
.svc-expand-detail h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
  color: #303133;
}
.svc-detection-item {
  margin-bottom: 8px;
  padding: 8px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}
.svc-det-rule {
  margin-left: 8px;
  font-weight: 500;
  font-size: 13px;
}
.svc-det-detail {
  margin: 6px 0 0 0;
  font-size: 12px;
  color: #606266;
}

:deep(.svc-row-critical) {
  background-color: #fef0f0 !important;
}
:deep(.svc-row-high) {
  background-color: #fdf6ec !important;
}
</style>
