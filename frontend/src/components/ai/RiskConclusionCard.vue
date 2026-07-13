<template>
  <div class="risk-conclusion-card">
    <!-- v1.3.1 P2: 数据增强模式横幅 -->
    <div v-if="analysisMode === 'data_enhancement'" class="rc-enhancement-banner">
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>
          {{ dataEnhancementBanner || '⚠ 输入质量不足，以下结论基于不完整数据，建议补采后重算' }}
        </template>
      </el-alert>
    </div>

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
        <span class="rc-dot" :style="{ background: contribColor(item.contribution) }"></span>
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
      <div v-if="topContribItem" class="rc-top-contrib">
        主要风险: {{ topContribItem.signal }} ({{ topContribItem.contribution }}分)
      </div>
    </div>

    <!-- 逐结论证据链（问题②C） -->
    <div v-if="evidenceChains.length" class="rc-evidence">
      <div class="rc-sub">逐结论证据链</div>
      <el-collapse v-model="evidenceExpanded" class="rc-collapse">
        <el-collapse-item
          v-for="(item, i) in evidenceChains"
          :key="i"
          :name="`ec-${i}`"
        >
          <template #title>
            <span class="rc-ec-title">{{ item.name || `发现 #${i + 1}` }}</span>
            <el-tag v-if="item.confidence" size="mini" :type="confTagType(item.confidence)" class="rc-ec-conf-tag">
              {{ item.confidence }}
            </el-tag>
          </template>
          <div class="rc-ec-item">
            <div class="rc-ec-confirmed">
              <span class="rc-ec-label">✅ 已有证据</span>
              <ul>
                <li v-for="(c, ci) in item.confirmed" :key="ci">{{ c }}</li>
                <li v-if="!item.confirmed.length" class="rc-ec-fallback">基于模型推断</li>
              </ul>
            </div>
            <div class="rc-ec-missing">
              <span class="rc-ec-label">❌ 缺失</span>
              <ul>
                <li v-for="(m, mi) in item.missing" :key="mi">{{ m }}</li>
                <li v-if="!item.missing.length" class="rc-ec-fallback">无明确缺失项</li>
              </ul>
            </div>
            <div class="rc-ec-upgrade">
              <span class="rc-ec-label">🔼 升级路径</span>
              <p>{{ item.upgrade_path || '补充缺失证据后可提升置信度' }}</p>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
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
import { computed, ref, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'

const props = defineProps({
  riskAssessment: { type: Object, default: () => ({}) },
  threatAnalysis: { type: Object, default: () => ({}) },
  escalationConditions: { type: Array, default: () => [] },
  analysisMode: { type: String, default: 'full' },
  dataEnhancementBanner: { type: String, default: '' },
})

const emit = defineEmits(['toggle-escalation'])

const riskLevel = computed(() => props.riskAssessment?.risk_level || '')
const riskScore = computed(() => props.riskAssessment?.risk_score ?? 0)
const confidence = computed(() => props.riskAssessment?.confidence || '')
const reason = computed(() => props.riskAssessment?.reason || '')
const breakdown = computed(() => props.riskAssessment?.score_breakdown || [])
const corrections = computed(() => props.riskAssessment?.consistency_corrections || [])

// 从 threat_analysis.malicious_behaviors 提取证据链
const evidenceChains = computed(() => {
  const behaviors = props.threatAnalysis?.malicious_behaviors || []
  return behaviors
    .filter((b) => typeof b === 'object' && b !== null)
    .map((b) => ({
      name: b.name || '',
      confidence: b.confidence || '',
      evidence: b.evidence || '',
      confirmed: b.evidence_chain?.confirmed || [],
      missing: b.evidence_chain?.missing || [],
      upgrade_path: b.evidence_chain?.upgrade_path || '',
    }))
    .filter((ec) => ec.confirmed.length || ec.missing.length || ec.upgrade_path)
})

// 折叠默认展开前 2 条
const evidenceExpanded = ref([])
watch(evidenceChains, (chains) => {
  const names = []
  for (let i = 0; i < Math.min(2, chains.length); i++) {
    names.push(`ec-${i}`)
  }
  evidenceExpanded.value = names
}, { immediate: true })

const levelType = computed(() => {
  const m = { 严重: 'danger', 高危: 'danger', 高: 'danger', 中危: 'warning', 中: 'warning', 低危: 'success', 低: 'success', 安全: 'success' }
  return m[riskLevel.value] || 'info'
})

const maxContrib = computed(() => {
  const ms = Math.max(1, ...breakdown.value.map((b) => Math.abs(b.contribution || 0)))
  return ms
})

const topContribItem = computed(() => {
  if (!breakdown.value.length) return null
  return breakdown.value.reduce((a, b) => (Math.abs(b.contribution || 0) > Math.abs(a.contribution || 0) ? b : a))
})

function contribColor(contribution) {
  const abs = Math.abs(contribution || 0)
  if (abs >= 15) return '#c0392b'
  if (abs >= 10) return '#e67e22'
  return '#2980b9'
}

function pct(v) {
  return Math.min(100, Math.round((Math.abs(v || 0) / maxContrib.value) * 100))
}

function confTagType(conf) {
  const m = { 高: 'danger', 中: 'warning', 低: 'info' }
  return m[conf] || 'info'
}

// 本地仅做推演，不向后端写状态（可证伪游乐场）
function onToggle(ec) {
  emit('toggle-escalation', ec)
}
</script>

<style scoped>
.risk-conclusion-card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; background: var(--el-bg-color); }
.rc-enhancement-banner { margin-bottom: 10px; }
.rc-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rc-title { font-weight: 600; font-size: 15px; }
.rc-score { color: #c0392b; font-weight: 600; }
.rc-conf { color: #888; font-size: 12px; }
.rc-reason { display: flex; gap: 6px; align-items: flex-start; color: #555; font-size: 13px; margin-top: 8px; }
.rc-sub { font-size: 13px; font-weight: 600; color: #666; margin: 10px 0 6px; }
.rc-breakdown { margin-top: 4px; }
.rc-bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.rc-signal { width: 150px; font-size: 12px; color: #444; }
.rc-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.rc-bar { flex: 1; }
.rc-contrib { width: 36px; text-align: right; font-size: 12px; }
.rc-top-contrib { margin-top: 6px; font-size: 12px; color: #c0392b; font-weight: 500; padding: 4px 8px; background: #fef0f0; border-radius: 4px; }
.rc-corr-list { font-size: 12px; color: #666; padding-left: 16px; }
.rc-corr-list code { color: #c0392b; }
.rc-collapse { margin-top: 8px; }
.rc-esc-row { margin-bottom: 4px; }

/* 证据链样式 */
.rc-evidence { margin-top: 8px; }
.rc-ec-title { font-size: 13px; font-weight: 500; }
.rc-ec-conf-tag { margin-left: 8px; }
.rc-ec-item { font-size: 13px; color: #555; padding: 4px 0; }
.rc-ec-label { font-weight: 600; display: block; margin: 6px 0 4px; font-size: 13px; }
.rc-ec-item ul { margin: 2px 0 0 16px; padding: 0; }
.rc-ec-item li { margin-bottom: 2px; line-height: 1.5; }
.rc-ec-item p { margin: 2px 0 0 2px; color: #409EFF; }
.rc-ec-fallback { color: #909399; font-style: italic; }
.rc-ec-confirmed .rc-ec-label { color: #67C23A; }
.rc-ec-missing .rc-ec-label { color: #F56C6C; }
.rc-ec-upgrade .rc-ec-label { color: #409EFF; }
</style>
