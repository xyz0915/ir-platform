<template>
  <div class="streaming-output">
    <!-- Token 使用信息 -->
    <div v-if="tokenUsage" class="token-bar mb-10">
      <span class="token-item">
        <span class="token-dot input-dot"></span>
        输入: {{ formatNumber(tokenUsage.prompt) }} tokens
      </span>
      <span class="token-item">
        <span class="token-dot output-dot"></span>
        输出: {{ formatNumber(tokenUsage.completion) }} tokens
      </span>
      <span class="token-item">
        <span class="token-dot total-dot"></span>
        总计: {{ formatNumber(tokenUsage.total) }} tokens
      </span>
    </div>

    <!-- 终端风格输出区域 -->
    <div class="terminal" ref="terminalRef">
      <div class="terminal-body">
        <!-- 已有内容 -->
        <pre class="terminal-text">{{ displayContent }}</pre>
        <!-- 闪烁光标 -->
        <span v-if="isStreaming" class="cursor-blink">█</span>
      </div>
    </div>

    <!-- 底部 Token 汇总 -->
    <div v-if="tokenUsage" class="token-footer mt-10">
      <span>输入 {{ formatNumber(tokenUsage.prompt) }} tokens</span>
      <span class="footer-sep">|</span>
      <span>输出 {{ formatNumber(tokenUsage.completion) }} tokens</span>
      <span class="footer-sep">|</span>
      <span>总计 {{ formatNumber(tokenUsage.total) }} tokens</span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

// ============================================================
// Props
// ============================================================
const props = defineProps({
  /** 流式输出的累积文本内容 */
  content: {
    type: String,
    default: '',
  },
  /** 是否正在流式输出中 */
  isStreaming: {
    type: Boolean,
    default: false,
  },
  /** Token 使用统计 { prompt, completion, total } */
  tokenUsage: {
    type: Object,
    default: null,
  },
})

// ============================================================
// State
// ============================================================
const terminalRef = ref(null)
const displayContent = ref(props.content || '')

// ============================================================
// Watchers
// ============================================================

// 监听 content 变化，同步显示并自动滚动到底部
watch(
  () => props.content,
  (val) => {
    displayContent.value = val || ''
    scrollToBottom()
  }
)

// ============================================================
// Methods
// ============================================================

/** 滚动终端到底部 */
function scrollToBottom() {
  nextTick(() => {
    const el = terminalRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

/** 格式化数字 */
function formatNumber(n) {
  if (n == null) return '0'
  return Number(n).toLocaleString()
}
</script>

<style scoped>
.streaming-output {
  width: 100%;
}

/* ============================================================
   Token Bar (顶部)
   ============================================================ */
.token-bar {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: #606266;
}

.token-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.token-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.input-dot {
  background: #409eff;
}

.output-dot {
  background: #67c23a;
}

.total-dot {
  background: #e6a23c;
}

/* ============================================================
   Terminal Output
   ============================================================ */
.terminal {
  background: #1e1e1e;
  border-radius: 8px;
  padding: 16px;
  min-height: 300px;
  max-height: 500px;
  overflow-y: auto;
  font-family: Consolas, Monaco, monospace;
  font-size: 14px;
  line-height: 1.7;
}

.terminal-body {
  display: inline;
  color: #00ff00;
}

.terminal-text {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  color: #00ff00;
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
  display: inline;
}

/* ============================================================
   Cursor Blink Animation
   ============================================================ */
.cursor-blink {
  color: #00ff00;
  animation: blink 1s step-end infinite;
  font-family: inherit;
  font-size: inherit;
}

@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

/* ============================================================
   Token Footer
   ============================================================ */
.token-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  font-size: 13px;
  color: #909399;
}

.footer-sep {
  color: #dcdfe6;
}

.mb-10 {
  margin-bottom: 10px;
}

.mt-10 {
  margin-top: 10px;
}
</style>
