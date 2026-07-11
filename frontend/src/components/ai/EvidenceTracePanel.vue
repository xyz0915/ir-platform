<template>
  <div class="panel">
    <div class="panel-header">证据溯源</div>
    <div v-if="labels.length" class="labels">
      <el-tag v-for="label in labels" :key="label" size="small">{{ label }}</el-tag>
    </div>
    <div v-if="knowledgeEvidence.length" class="section">
      <div class="sub-title">知识库证据</div>
      <div
        v-for="(item, index) in knowledgeEvidence"
        :key="index"
        class="evidence-item"
        :class="{ 'is-clickable': isClickable(item) }"
        @click="goDetail(item)"
      >
        <div class="evidence-top">
          <div class="evidence-title">
            <strong>{{ item.title || item.rule_name }}</strong>
            <!-- 来源徽标：内置种子 / AI 建议 / 规则引擎（与 entry_type 对应） -->
            <el-tag v-if="item.entry_type" size="small" :type="entryTypeTag(item.entry_type)">
              {{ entryTypeLabel(item.entry_type) }}
            </el-tag>
          </div>
          <el-tag size="small" :type="severityType(item.severity)">{{ item.severity || 'medium' }}</el-tag>
        </div>
        <div class="evidence-text">{{ item.summary || item.evidence_text }}</div>
        <div class="evidence-meta">
          {{ item.reason || item.match_reason }}
          <!-- 可点击溯源提示（仅 seed/draft） -->
          <span v-if="isClickable(item)" class="trace-hint">查看详情 ›</span>
        </div>
      </div>
    </div>
    <div v-if="localEvidence.length" class="section">
      <div class="sub-title">本地证据</div>
      <ul>
        <li v-for="(item, index) in localEvidence" :key="index">{{ item.summary }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const props = defineProps({
  evidenceTrace: { type: Object, default: () => ({}) },
})

const router = useRouter()

const knowledgeEvidence = props.evidenceTrace?.knowledge_evidence || []
const localEvidence = props.evidenceTrace?.local_evidence || []
const labels = props.evidenceTrace?.explainability_labels || []

// ── 证据可点击溯源 ──
// seed / draft 可点击跳转到知识条目详情；rule 仅渲染规则引擎徽标（不可点击）；
// entry_ref 缺失（旧数据 / 未命中三分支）按不可点击纯文本渲染，不报错。
function isClickable(item) {
  return !!item.entry_ref && (item.entry_type === 'seed' || item.entry_type === 'draft')
}

function goDetail(item) {
  if (!isClickable(item)) return
  router.push('/knowledge/detail/' + item.entry_ref)
}

function entryTypeLabel(type) {
  const map = { seed: '内置种子', draft: 'AI 建议', rule: '规则引擎' }
  return map[type] || '知识库'
}

function entryTypeTag(type) {
  const map = { seed: 'success', draft: 'warning', rule: 'info' }
  return map[type] || 'info'
}

function severityType(level) {
  if (level === 'critical' || level === 'high') return 'danger'
  if (level === 'medium') return 'warning'
  return 'info'
}
</script>

<style scoped>
.panel { padding: 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fff; }
.panel-header { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.labels { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.section { margin-top: 10px; }
.sub-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #303133; }
.evidence-item { padding: 10px; background: #f7f9fc; border-radius: 6px; margin-bottom: 8px; }
.evidence-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.evidence-text { margin-top: 6px; font-size: 13px; color: #303133; line-height: 1.6; }
.evidence-meta { margin-top: 4px; font-size: 12px; color: #909399; }
ul { margin: 0; padding-left: 18px; color: #606266; line-height: 1.7; }
.evidence-title { display: flex; align-items: center; gap: 8px; }
.evidence-item.is-clickable { cursor: pointer; transition: box-shadow .15s, border-color .15s; }
.evidence-item.is-clickable:hover { border-color: var(--el-color-primary); box-shadow: 0 2px 8px rgba(64, 158, 255, .15); }
.trace-hint { margin-left: auto; color: var(--el-color-primary); font-size: 12px; }
</style>
