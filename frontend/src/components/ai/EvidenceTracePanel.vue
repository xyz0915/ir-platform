<template>
  <div class="panel">
    <div class="panel-header">证据溯源</div>
    <div v-if="labels.length" class="labels">
      <el-tag v-for="label in labels" :key="label" size="small">{{ label }}</el-tag>
    </div>
    <div v-if="knowledgeEvidence.length" class="section">
      <div class="sub-title">知识库证据</div>
      <div v-for="(item, index) in knowledgeEvidence" :key="index" class="evidence-item">
        <div class="evidence-top">
          <strong>{{ item.title || item.rule_name }}</strong>
          <el-tag size="small" :type="severityType(item.severity)">{{ item.severity || 'medium' }}</el-tag>
        </div>
        <div class="evidence-text">{{ item.summary || item.evidence_text }}</div>
        <div class="evidence-meta">{{ item.reason || item.match_reason }}</div>
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
const props = defineProps({
  evidenceTrace: { type: Object, default: () => ({}) },
})

const knowledgeEvidence = props.evidenceTrace?.knowledge_evidence || []
const localEvidence = props.evidenceTrace?.local_evidence || []
const labels = props.evidenceTrace?.explainability_labels || []

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
</style>
