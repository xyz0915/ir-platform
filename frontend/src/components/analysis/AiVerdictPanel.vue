<template>
  <div class="ai-verdict-panel" :class="'vl-' + (verdictLabel || 'suspicious')">
    <!-- AI 结论标签 -->
    <div class="avp-header">
      <span class="avp-diamond">◆</span>
      <span class="avp-title">AI 研判</span>
      <span class="verdict-badge" :class="'vlabel-' + (verdictLabel || 'suspicious')">{{ verdictLabelText }}</span>
      <span class="avp-confidence" :class="{ 'high-c': confidence >= 80, 'mid-c': confidence >= 60 && confidence < 80 }">置信度 {{ confidence }}%</span>
    </div>

    <div class="avp-body">
      <!-- 研判理由 -->
      <div class="avp-row" v-if="reason">
        <span class="avp-val">{{ reason }}</span>
      </div>
      <div class="avp-row" v-else>
        <span class="avp-val avp-empty-hint">AI 研判暂不可用</span>
      </div>

      <!-- MITRE 技术 -->
      <div class="avp-mitre" v-if="mitreTags.length > 0">
        <span class="avp-mitre-tag" v-for="tag in mitreTags" :key="tag">{{ tag }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  aiVerdict: { type: Object, default: null },
  aiAnalysis: { type: String, default: '' },
})

const showAnalysis = ref(false)

const verdictData = computed(() => {
  if (!props.aiVerdict) return null
  try {
    return typeof props.aiVerdict === 'string' ? JSON.parse(props.aiVerdict) : props.aiVerdict
  } catch {
    return null
  }
})

const verdictLabel = computed(() => verdictData.value?.label || 'suspicious')
const confidence = computed(() => verdictData.value?.confidence || 85)
const tcode = computed(() => verdictData.value?.t_code || '')
const attackType = computed(() => verdictData.value?.attack_type || '')
const rawAction = computed(() => verdictData.value?.action || '')
const reason = computed(() => verdictData.value?.reason || '')

const verdictLabelText = computed(() => {
  const labels = {
    recommended: 'AI 优先推荐',
    suspicious: '可疑',
    false_positive: '误报',
    benign: '良性',
    unknown: '未知/降级',
  }
  return labels[verdictLabel.value] || '可疑'
})

const mitreTags = computed(() => {
  const t = tcode.value
  if (!t) return []
  return t.split(',').map(s => s.trim()).filter(Boolean)
})
</script>

<style scoped>
.ai-verdict-panel {
  background: #E6F1FB;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.ai-verdict-panel.vl-suspicious {
  background: #E6F1FB;
}
.ai-verdict-panel.vl-false_positive {
  background: #f5f5f7;
}
.ai-verdict-panel.vl-benign {
  background: #dcfce7;
}
.ai-verdict-panel.vl-unknown {
  background: #f5f5f7;
}

.avp-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.avp-diamond {
  font-size: 16px;
  color: #1d1d1f;
  font-weight: 500;
}
.avp-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
}
.verdict-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 4px;
  line-height: 1.4;
}
.vlabel-recommended { background: rgba(22,163,74,0.15); color: #16a34a; }
.vlabel-suspicious { background: #FAEEDA; color: #854F0B; }
.vlabel-false_positive { background: rgba(163,163,163,0.15); color: #6b7280; }
.vlabel-benign { background: rgba(22,163,74,0.15); color: #16a34a; }
.vlabel-unknown { background: rgba(100,116,139,0.15); color: #64748b; }

.avp-confidence {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(255,255,255,0.6);
  color: #185FA5;
  font-weight: 500;
}
.avp-confidence.high-c {
  color: #dc2626;
}
.avp-confidence.mid-c {
  color: #d97706;
}

.avp-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.avp-row {
  font-size: 12px;
  line-height: 1.6;
}
.avp-val {
  color: #1d1d1f;
  word-break: break-all;
}
.avp-fallback-reason .avp-val {
  color: #444441;
}
.avp-empty-hint {
  color: #b4b2a9;
  font-style: italic;
}

.avp-mitre {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.avp-mitre-tag {
  background: #FCEBEB;
  color: #A32D2D;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-family: monospace;
}
</style>
