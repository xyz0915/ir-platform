<template>
  <div class="ai-verdict-panel" :class="'vl-' + (verdictLabel || 'unknown')">
    <!-- AI 结论标签 -->
    <div class="avp-header">
      <span class="verdict-badge" :class="'vlabel-' + (verdictLabel || 'unknown')">{{ verdictLabelText }}</span>
    </div>

    <div class="avp-body">
      <!-- 置信度 -->
      <div class="avp-row">
        <span class="avp-label">置信度</span>
        <span class="avp-val" :class="{ 'high-c': confidence >= 80, 'mid-c': confidence >= 60 && confidence < 80 }">{{ confidence }}%</span>
      </div>

      <!-- MITRE 技术 -->
      <div class="avp-row" v-if="tcode">
        <span class="avp-label">MITRE 技术</span>
        <span class="avp-val avp-tcode">{{ tcode }}</span>
      </div>

      <!-- 攻击类型 -->
      <div class="avp-row" v-if="attackType">
        <span class="avp-label">攻击类型</span>
        <span class="avp-val">{{ attackType }}</span>
      </div>

      <!-- 建议动作 -->
      <div class="avp-row" v-if="rawAction">
        <span class="avp-label">建议动作</span>
        <span class="avp-val avp-action-tag" :class="'act-' + rawAction">{{ actionLabel }}</span>
      </div>

      <!-- 研判理由 -->
      <div class="avp-row" v-if="reason">
        <span class="avp-label">研判理由</span>
        <span class="avp-val">{{ reason }}</span>
      </div>

      <!-- AI 分析原文（可展开/折叠） -->
      <div class="avp-analysis" v-if="aiAnalysis">
        <div class="avp-analysis-header" @click="showAnalysis = !showAnalysis">
          <span class="avp-label">AI 分析原文</span>
          <svg
            class="avp-chevron"
            :class="{ 'avp-chevron-open': showAnalysis }"
            width="10" height="10" viewBox="0 0 10 10"
          >
            <path d="M3 2L7 5L3 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="avp-analysis-body" v-if="showAnalysis">
          {{ aiAnalysis }}
        </div>
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

const verdictLabel = computed(() => verdictData.value?.label || '')
const confidence = computed(() => verdictData.value?.confidence || 0)
const tcode = computed(() => verdictData.value?.t_code || '')
const attackType = computed(() => verdictData.value?.attack_type || '')
const rawAction = computed(() => verdictData.value?.action || '')
const reason = computed(() => verdictData.value?.reason || '')

const verdictLabelText = computed(() => {
  const labels = {
    recommended: '🤖 AI 优先推荐',
    suspicious: '🟡 可疑·待复核',
    false_positive: '⚪ 误报',
    benign: '🟢 良性',
    unknown: '⚫ 未知/降级',
  }
  return labels[verdictLabel.value] || '🤖 AI 研判'
})

const actionLabel = computed(() => {
  const labels = {
    isolate: '隔离主机',
    kill_process: '结束进程',
    block_ip: '封锁IP',
    review: '人工复核',
  }
  return labels[rawAction.value] || rawAction.value
})
</script>

<style scoped>
.ai-verdict-panel {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 10px;
  border-left: 3px solid #16a34a;
}
.ai-verdict-panel.vl-suspicious { border-left-color: #d97706; }
.ai-verdict-panel.vl-false_positive { border-left-color: #a3a3a3; }
.ai-verdict-panel.vl-benign { border-left-color: #16a34a; }
.ai-verdict-panel.vl-unknown { border-left-color: #64748b; }

.avp-header {
  margin-bottom: 10px;
}
.verdict-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 4px;
  line-height: 1.4;
}
.vlabel-recommended { background: rgba(22,163,74,0.15); color: #16a34a; border: 0.5px solid rgba(22,163,74,0.3); }
.vlabel-suspicious { background: rgba(217,119,6,0.15); color: #d97706; border: 0.5px solid rgba(217,119,6,0.3); }
.vlabel-false_positive { background: rgba(163,163,163,0.15); color: #6b7280; border: 0.5px solid rgba(163,163,163,0.3); }
.vlabel-benign { background: rgba(22,163,74,0.15); color: #16a34a; border: 0.5px solid rgba(22,163,74,0.3); }
.vlabel-unknown { background: rgba(100,116,139,0.15); color: #64748b; border: 0.5px solid rgba(100,116,139,0.3); }

.avp-body {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  font-size: 12px;
}
.avp-row {
  display: contents;
}
.avp-label {
  color: var(--color-fg-subtle);
  font-size: 11px;
  white-space: nowrap;
  padding-top: 1px;
}
.avp-val {
  color: var(--color-fg-default);
  word-break: break-all;
}
.avp-val.high-c { color: #dc2626; font-weight: 600; }
.avp-val.mid-c { color: #d97706; font-weight: 600; }
.avp-tcode {
  font-family: monospace;
  background: rgba(147, 51, 234, 0.1);
  padding: 1px 6px;
  border-radius: 4px;
  display: inline-block;
  color: #7c3aed;
  font-size: 11px;
}
.avp-action-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
}
.avp-action-tag.act-isolate { background: rgba(220,38,38,0.1); color: #dc2626; }
.avp-action-tag.act-kill_process { background: rgba(220,38,38,0.1); color: #dc2626; }
.avp-action-tag.act-block_ip { background: rgba(217,119,6,0.1); color: #d97706; }
.avp-action-tag.act-review { background: rgba(37,99,235,0.1); color: #2563eb; }

.avp-analysis {
  grid-column: 1 / -1;
  margin-top: 6px;
  padding-top: 8px;
  border-top: 0.5px solid var(--color-border-default);
}
.avp-analysis-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.avp-chevron {
  color: var(--color-fg-subtle);
  transition: transform 0.15s;
}
.avp-chevron-open {
  transform: rotate(90deg);
}
.avp-analysis-body {
  margin-top: 6px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--color-fg-default);
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
