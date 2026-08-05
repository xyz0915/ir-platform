<template>
  <div class="step-card" :class="{ 'is-running': step.status === 'running', 'is-failed': step.status === 'failed' }">
    <div class="sc-header">
      <span class="sc-status-icon">
        <span v-if="step.status === 'running'" class="spinner"></span>
        <span v-else-if="step.status === 'completed'" class="check-mark">✓</span>
        <span v-else-if="step.status === 'failed'" class="cross-mark">✗</span>
        <span v-else class="idle-mark">·</span>
      </span>
      <span class="sc-agent">{{ step.agent || 'Agent' }}</span>
      <span class="sc-stage">{{ step.stage || '' }}</span>
      <span class="sc-elapsed">
        <template v-if="step.elapsed_seconds > 0">{{ formatElapsed(step.elapsed_seconds) }}</template>
        <template v-else-if="step.status === 'running'">正在运行...</template>
      </span>
    </div>
    <div class="sc-body" v-if="displayText">
      <pre class="sc-output" :class="{ typing: isTyping }">{{ displayText }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'

const props = defineProps({
  step: { type: Object, default: () => ({}) },
})

const displayText = ref('')
const isTyping = ref(false)
let typewriterTimer = null
let typewriterIdx = 0

const isLLMOutput = computed(() => {
  const name = (props.step.agent || '').toLowerCase()
  return name.includes('triage') || name.includes('investigat') || name.includes('respond') || name.includes('report')
})

// 当 output 或 _updated_at 变化时触发打字机效果
watch([() => props.step.output, () => props.step._updated_at], ([newOutput]) => {
  if (!newOutput || !isLLMOutput.value || props.step.status !== 'completed') {
    displayText.value = newOutput || ''
    return
  }
  startTypewriter(newOutput)
}, { immediate: true })

function startTypewriter(text) {
  stopTypewriter()
  typewriterIdx = 0
  displayText.value = ''
  isTyping.value = true
  function tick() {
    if (typewriterIdx >= text.length) {
      displayText.value = text
      isTyping.value = false
      return
    }
    const chunkSize = Math.max(1, Math.floor(Math.random() * 2) + 1)
    const end = Math.min(typewriterIdx + chunkSize, text.length)
    displayText.value = text.substring(0, end)
    typewriterIdx = end
    typewriterTimer = setTimeout(tick, 33)
  }
  tick()
}

function stopTypewriter() {
  if (typewriterTimer) {
    clearTimeout(typewriterTimer)
    typewriterTimer = null
  }
  isTyping.value = false
}

onUnmounted(stopTypewriter)

function formatElapsed(s) {
  if (s < 60) return Math.round(s) + '秒'
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}分${sec}秒`
}
</script>

<style scoped>
.step-card {
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 6px;
  background: var(--color-canvas-default);
  transition: all 0.2s;
}
.step-card.is-running {
  border-left: 3px solid #4b5563;
}
.step-card.is-failed {
  border-left: 3px solid #dc2626;
  background: var(--color-danger-subtle);
}
.sc-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.sc-status-icon { width: 18px; text-align: center; }
.check-mark { color: #16a34a; font-weight: bold; }
.cross-mark { color: #dc2626; font-weight: bold; }
.idle-mark { color: var(--color-fg-subtle); }
.spinner {
  display: inline-block;
  width: 12px; height: 12px;
  border: 2px solid #e5e7eb;
  border-top-color: #4b5563;
  border-radius: 50%;
  animation: sc-spin 0.6s linear infinite;
}
@keyframes sc-spin { to { transform: rotate(360deg); } }
.sc-agent { font-weight: 500; color: var(--color-fg-default); }
.sc-stage { font-size: 11px; color: var(--color-fg-subtle); }
.sc-elapsed { margin-left: auto; font-size: 11px; color: var(--color-fg-subtle); }
.sc-body { margin-top: 6px; }
.sc-output {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--color-fg-default);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}
.sc-output.typing::after {
  content: '|';
  animation: cursor-blink 0.6s step-end infinite;
  color: #111827;
  margin-left: 2px;
}
@keyframes cursor-blink {
  50% { opacity: 0; }
}
</style>
