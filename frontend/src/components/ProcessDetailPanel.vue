<template>
  <el-dialog
    :model-value="visible"
    title="进程详情"
    width="700px"
    @update:model-value="$emit('update:visible', $event)"
    destroy-on-close
  >
    <template v-if="processInfo">
      <!-- 基本信息 -->
      <el-descriptions :column="2" border size="small" class="mb-16">
        <el-descriptions-item label="PID">{{ processInfo.pid }}</el-descriptions-item>
        <el-descriptions-item label="进程名">{{ processInfo.process_name }}</el-descriptions-item>
        <el-descriptions-item label="路径" :span="2">{{ processInfo.process_path }}</el-descriptions-item>
        <el-descriptions-item label="命令行" :span="2">{{ processInfo.command_line }}</el-descriptions-item>
        <el-descriptions-item label="父进程">{{ processInfo.parent_name }}</el-descriptions-item>
        <el-descriptions-item label="父进程PID">{{ processInfo.parent_pid }}</el-descriptions-item>
        <el-descriptions-item label="用户">{{ processInfo.details?.user || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="线程数">{{ processInfo.details?.threads || 'N/A' }}</el-descriptions-item>
      </el-descriptions>

      <!-- 风险评分 -->
      <div class="mb-16" v-if="processInfo.risk_score">
        <div class="detail-label">风险评分</div>
        <el-progress
          :percentage="processInfo.risk_score"
          :color="riskColor(processInfo.risk_score)"
          :stroke-width="20"
          :text-inside="true"
        />
      </div>

      <!-- 命中规则 -->
      <div class="mb-16" v-if="processInfo.matched_rules && processInfo.matched_rules.length">
        <div class="detail-label">命中规则</div>
        <div class="matched-rules-tags">
          <el-tag
            v-for="(rule, idx) in processInfo.matched_rules"
            :key="idx"
            :type="severityType(rule.severity)"
            size="small"
            class="rule-tag"
          >
            {{ rule.name }} [{{ rule.severity }}]
          </el-tag>
        </div>
      </div>

      <!-- 攻击路径 -->
      <div class="mb-16" v-if="processInfo.attack_path">
        <div class="detail-label">攻击路径</div>
        <el-alert
          type="error"
          :closable="false"
          :title="processInfo.attack_path"
        />
      </div>
    </template>

    <template v-else>
      <el-empty description="暂无进程信息" />
    </template>
  </el-dialog>
</template>

<script setup>
const props = defineProps({
  visible: { type: Boolean, default: false },
  processInfo: { type: Object, default: null }
})

defineEmits(['update:visible'])

function severityType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary',
    info: 'info'
  }
  return map[severity] || 'info'
}

function riskColor(score) {
  if (score >= 80) return '#F56C6C'
  if (score >= 50) return '#E6A23C'
  if (score >= 20) return '#409EFF'
  return '#67C23A'
}
</script>

<style scoped>
.mb-16 {
  margin-bottom: 16px;
}
.detail-label {
  font-weight: bold;
  margin-bottom: 8px;
  color: #303133;
}
.matched-rules-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rule-tag {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
