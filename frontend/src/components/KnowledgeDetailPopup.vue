<template>
  <el-dialog
    :model-value="visible"
    title="知识条目详情"
    width="560px"
    :close-on-click-modal="true"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div v-if="loading" class="popup-loading">
      <el-skeleton :rows="5" animated />
    </div>
    <div v-else-if="error" class="popup-error">
      <el-empty description="该知识条目不存在（可能已被拒绝/撤回）" :image-size="64" />
    </div>
    <div v-else-if="entry" class="popup-body">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="标题" label-class-name="desc-label">
          <strong>{{ entry.name }}</strong>
        </el-descriptions-item>
        <el-descriptions-item label="描述" label-class-name="desc-label">
          {{ entry.description || '暂无描述' }}
        </el-descriptions-item>
        <el-descriptions-item label="ATT&CK" label-class-name="desc-label">
          <el-tag v-if="entry.mitre_attack" type="warning" size="small" effect="plain">
            {{ entry.mitre_attack }}
          </el-tag>
          <span v-else class="text-muted">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="严重程度" label-class-name="desc-label">
          <el-tag :type="severityType(entry.severity)" size="small">
            {{ entry.severity }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="来源" label-class-name="desc-label">
          <el-tag size="small" type="info">{{ entry.source || entry.entry_type || 'unknown' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="条目类型" label-class-name="desc-label">
          <el-tag size="small" :type="entryTypeTag(entry.entry_type)">
            {{ entryTypeLabel(entry.entry_type) }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <el-card v-if="hasHitMeta" shadow="never" class="match-context-card" style="margin-top:12px">
        <template #header><span style="font-weight:600;font-size:13px">匹配证据</span></template>
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="证据类型">
            <el-tag size="small" type="primary">{{ evidenceTypeLabel }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="证据标识">
            <el-tag size="small">{{ hitMeta.evidence_key || '（无）' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="语义分数">
            <span style="font-weight:600;color:#409EFF">{{ scorePercent }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="置信度">
            <el-tag :type="confidenceTag">{{ hitMeta.confidence || 'low' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="hitMeta.match_reason" label="匹配原因" :span="2">
            {{ hitMeta.match_reason }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="$emit('update:visible', false)">关闭</el-button>
        <el-button
          v-if="entry && entryRef"
          type="primary"
          @click="goToKnowledge"
        >
          在知识库中查看
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import knowledgeApi from '@/api/knowledge'

const props = defineProps({
  visible: { type: Boolean, default: false },
  entryRef: { type: String, default: '' },
  hitMeta: { type: Object, default: () => ({}) }
})

defineEmits(['update:visible'])

// ── 匹配证据计算属性 ──
const hitMeta = computed(() => props.hitMeta)

const hasHitMeta = computed(() => {
  const hm = hitMeta.value
  return hm && Object.keys(hm).length > 0
})

const evidenceTypeLabel = computed(() => {
  const map = {
    process: '异常进程',
    connection: '可疑外连',
    webshell_ms: 'WebShell/内存马',
    persistence: '持久化',
    memory_shell: '内存马'
  }
  return map[hitMeta.value.evidence_type] || hitMeta.value.evidence_type || '未知'
})

const scorePercent = computed(() => {
  const s = hitMeta.value.semantic_score ?? hitMeta.value.score ?? 0
  return (s * 100).toFixed(1) + '%'
})

const confidenceTag = computed(() => {
  const c = hitMeta.value.confidence || 'low'
  return c === 'high' ? 'danger' : c === 'medium' ? 'warning' : 'info'
})

const router = useRouter()

const loading = ref(false)
const entry = ref(null)
const error = ref(false)

watch(() => [props.visible, props.entryRef], ([vis, refStr]) => {
  if (vis && refStr) {
    loadEntry(refStr)
  } else if (!vis) {
    entry.value = null
    error.value = false
  }
})

async function loadEntry(refStr) {
  if (!refStr) {
    error.value = true
    return
  }
  loading.value = true
  error.value = false
  entry.value = null
  try {
    const res = await knowledgeApi.getEntry(refStr)
    entry.value = res.data
  } catch (e) {
    error.value = true
  } finally {
    loading.value = false
  }
}

function goToKnowledge() {
  router.push({ path: '/knowledge', query: { ref: props.entryRef } })
}

function severityType(severity) {
  const map = { critical: 'danger', high: 'danger', medium: 'warning', low: 'primary', info: 'info' }
  return map[severity] || 'info'
}

function entryTypeTag(type) {
  const map = { seed: 'success', rule: '', draft: 'warning', unknown: 'info' }
  return map[type] || 'info'
}

function entryTypeLabel(type) {
  const map = { seed: '种子知识', rule: '检测规则', draft: '知识草稿', unknown: '未知' }
  return map[type] || type
}
</script>

<style scoped>
.popup-loading { padding: 16px 0; }
.popup-error { padding: 24px 0; }
.popup-body { max-height: 360px; overflow-y: auto; }
.text-muted { color: #909399; }
.desc-label { font-weight: 600 !important; }
</style>
