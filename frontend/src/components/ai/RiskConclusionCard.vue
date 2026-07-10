<template>
  <div class="risk-conclusion-card">
    <div class="rc-header">
      <span class="rc-title">风险结论</span>
      <el-tag :type="levelType" effect="dark" size="small">{{ riskLevel || '待确认' }}</el-tag>
      <span class="rc-score">评分 {{ riskScore }} / 100</span>
      <span v-if="confidence" class="rc-conf">置信: {{ confidence }}</span>
    </div>

    <div v-if="reason" class="rc-reason">
      <el-icon><InfoFilled /></el-icon>
      <span>{{ reason }}</span>
    </div>

    <!-- 评分明细（透明评分 R1-2） -->
    <div v-if="breakdown.length" class="rc-breakdown">
      <div class="rc-sub">评分明细 (score_breakdown)</div>
      <div v-for="item in breakdown" :key="item.signal" class="rc-bar-row">
        <span class="rc-signal">{{ item.signal }}</span>
        <el-progress
          :percentage="pct(item.contribution)"
          :color="item.historical_known ? '#909399' : '#c0392b'"
          :show-text="false"
          class="rc-bar"
        />
        <span class="rc-contrib">{{ item.contribution }}</span>
        <el-tag v-if="item.historical_known" size="mini" type="info" effect="plain">基线已知</el-tag>
      </div>
    </div>

    <!-- 一致性纠正痕迹（可审计） -->
    <el-collapse v-if="corrections.length" class="rc-collapse">
      <el-collapse-item title="一致性纠正痕迹 (可审计)" name="corr">
        <ul class="rc-corr-list">
          <li v-for="(c, i) in corrections" :key="i">
            <code>{{ c.rule }}</code> · {{ c.field }} · {{ c.action }} — {{ c.detail }}
          </li>
        </ul>
      </el-collapse-item>
    </el-collapse>

    <!-- 可证伪升级条件（R7-1） -->
    <div v-if="escalationConditions.length" class="rc-escalation">
      <div class="rc-sub">可证伪升级条件</div>
      <div v-for="(ec, i) in escalationConditions" :key="i" class="rc-esc-row">
        <el-checkbox v-model="ec._checked" @change="onToggle(ec)">
          {{ ec.condition }} → 若成立则「{{ ec.if_true }}」({{ ec.target_level }})
        </el-checkbox>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'

const props = defineProps({
  riskAssessment: { type: Object, default: () => ({}) },
  escalationConditions: { type: Array, default: () => [] },
})

const emit = defineEmits(['toggle-escalation'])

const riskLevel = computed(() => props.riskAssessment?.risk_level || '')
const riskScore = computed(() => props.riskAssessment?.risk_score ?? 0)
const confidence = computed(() => props.riskAssessment?.confidence || '')
const reason = computed(() => props.riskAssessment?.reason || '')
const breakdown = computed(() => props.riskAssessment?.score_breakdown || [])
const corrections = computed(() => props.riskAssessment?.consistency_corrections || [])

const levelType = computed(() => {
  const m = { 严重: 'danger', 高危: 'danger', 高: 'danger', 中危: 'warning', 中: 'warning', 低危: 'success', 低: 'success', 安全: 'success' }
  return m[riskLevel.value] || 'info'
})

const maxContrib = computed(() => {
  const ms = Math.max(1, ...breakdown.value.map((b) => Math.abs(b.contribution || 0)))
  return ms
})

function pct(v) {
  return Math.min(100, Math.round((Math.abs(v || 0) / maxContrib.value) * 100))
}

// 本地仅做推演，不向后端写状态（可证伪游乐场）
const localChecked = {}
function onToggle(ec) {
  emit('toggle-escalation', ec)
}
</script>

<style scoped>
.risk-conclusion-card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; background: var(--el-bg-color); }
.rc-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rc-title { font-weight: 600; font-size: 15px; }
.rc-score { color: #c0392b; font-weight: 600; }
.rc-conf { color: #888; font-size: 12px; }
.rc-reason { display: flex; gap: 6px; align-items: flex-start; color: #555; font-size: 13px; margin-top: 8px; }
.rc-sub { font-size: 13px; font-weight: 600; color: #666; margin: 10px 0 6px; }
.rc-breakdown { margin-top: 4px; }
.rc-bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.rc-signal { width: 150px; font-size: 12px; color: #444; }
.rc-bar { flex: 1; }
.rc-contrib { width: 36px; text-align: right; font-size: 12px; }
.rc-corr-list { font-size: 12px; color: #666; padding-left: 16px; }
.rc-corr-list code { color: #c0392b; }
.rc-collapse { margin-top: 8px; }
.rc-esc-row { margin-bottom: 4px; }
</style>
