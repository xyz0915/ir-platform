<template>
  <div class="agent-run-detail">
    <!-- 顶栏 -->
    <div class="detail-topbar">
      <div class="dt-tabs">
        <button :class="{ active: activeTab === 'process' }" @click="activeTab = 'process'">调查过程</button>
        <button :class="{ active: activeTab === 'conclusion' }" @click="activeTab = 'conclusion'">调查结论</button>
        <button :class="{ active: activeTab === 'observability' }" @click="activeTab = 'observability'">可观测性</button>
      </div>
      <div class="dt-right">
        <span class="dt-run-id">{{ runId }}</span>
        <button class="dt-close" @click="goBack">× 关闭</button>
      </div>
    </div>

    <!-- 内容区：调查过程 -->
    <div class="detail-body" v-if="activeTab === 'process'" :class="{ 'is-dragging': isDragging }">
      <!-- 左栏 -->
      <div class="left-panel" :style="{ width: leftWidth + 'px' }">
        <div class="lp-scroll" ref="scrollRef">
          <div v-if="loading" class="lp-loading">加载中...</div>
          <StepCard v-for="(step, i) in sse.steps.value" :key="step.step_id || i" :step="step" />
          <div v-if="sse.steps.value.length === 0 && !loading" class="lp-empty">
            暂无步骤数据
          </div>
        </div>
      </div>
      <!-- 可拖拽分隔条 -->
      <div
        class="divider-bar"
        @mousedown="onDividerDown"
        @dblclick="resetDivider"
      >
        <div class="divider-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
      <!-- 右栏 -->
      <div class="right-panel">
        <GraphPanel
          :nodes="sse.aggregatedNodes ? sse.aggregatedNodes.value : sse.graphNodes.value"
          :edges="sse.graphEdges.value"
          :steps="sse.steps.value"
          @node-click="onGraphNodeClick"
        />
      </div>
    </div>

    <!-- 内容区：调查结论 -->
    <div class="detail-body" v-if="activeTab === 'conclusion'">
      <div class="conclusion-panel">
        <div class="cp-section">
          <h3>执行摘要</h3>
          <p>Agent 总数: {{ sse.steps.value.length }}</p>
          <p>成功: {{ sse.steps.value.filter(s => s.status === 'completed').length }}</p>
          <p>失败: {{ sse.steps.value.filter(s => s.status === 'failed').length }}</p>
        </div>
        <div class="cp-section" v-for="(step, i) in completedSteps" :key="i">
          <h4>{{ step.agent }} — {{ step.stage }}</h4>
          <pre class="cp-output">{{ step.output }}</pre>
        </div>
      </div>
    </div>

    <!-- 内容区：可观测性（M8 增强 Tab，trace 树 / 结构化日志 / 续跑点） -->
    <div class="detail-body" v-else-if="activeTab === 'observability'">
      <div class="observability-panel">
        <div v-if="obs.loading" class="obs-loading">可观测性数据加载中...</div>
        <template v-else-if="obs.run">
          <!-- 续跑点 -->
          <div class="obs-section" v-if="obs.run.resume_point">
            <h3>续跑点 (Resume Point)</h3>
            <el-alert type="warning" :closable="false" show-icon class="obs-resume">
              <template #title>{{ obs.run.resume_point }}</template>
            </el-alert>
          </div>
          <!-- Trace 树 -->
          <div class="obs-section">
            <h3>调用链路 Trace <span class="obs-count">{{ obs.run.trace?.length || 0 }} 个 span</span></h3>
            <div class="obs-card">
              <TraceTree :trace="obs.run.trace || []" />
            </div>
          </div>
          <!-- 结构化日志 -->
          <div class="obs-section">
            <h3>结构化日志 <span class="obs-count">{{ obs.run.logs?.length || 0 }} 条</span></h3>
            <div class="obs-card obs-logs">
              <LogTimeline :logs="obs.run.logs || []" />
            </div>
          </div>
        </template>
        <el-empty v-else description="暂无可观测性数据" :image-size="60" />
      </div>
    </div>

    <!-- SSE 状态栏 -->
    <div class="sse-status" :class="{ connected: sse.connected.value, archived: sse.runCompleted.value }">
      <span class="sse-dot"></span>
      <span v-if="sse.runCompleted.value">
        📜 已归档（运行完成）— 数据来自历史记录
      </span>
      <span v-else-if="sse.connected.value">SSE 连接中</span>
      <span v-else>SSE 已断开</span>
      <button v-if="!sse.connected.value && !sse.runCompleted.value" class="sse-reconnect" @click="sse.connect(runId)">重连</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAgentOrchestrationStore } from '@/stores/agents'
import { useObservabilityStore } from '@/stores/observability'
import { useSSE } from '@/composables/useSSE'
import agentApi from '@/api/agent'
import StepCard from '@/components/agents/StepCard.vue'
import GraphPanel from '@/components/agents/GraphPanel.vue'
import TraceTree from '@/components/agents/TraceTree.vue'
import LogTimeline from '@/components/agents/LogTimeline.vue'

const route = useRoute()
const router = useRouter()
const store = useAgentOrchestrationStore()
const obs = useObservabilityStore()

const runId = route.params.runId
const activeTab = ref('process')
const loading = ref(true)
const scrollRef = ref(null)

const sse = useSSE()
const autoScroll = ref(true)

// ===== 可拖拽分隔条 =====
const DIVIDER_MIN = 280
const DIVIDER_MAX = 1200
const leftWidth = ref(400)
const isDragging = ref(false)
let dividerStartX = 0
let dividerStartWidth = 400
let dividerMoveHandler = null
let dividerUpHandler = null

function onDividerDown(e) {
  isDragging.value = true
  dividerStartX = e.clientX
  dividerStartWidth = leftWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'

  dividerMoveHandler = (ev) => {
    const dx = ev.clientX - dividerStartX
    const parentW = document.querySelector('.detail-body')?.clientWidth || 1200
    const newW = Math.max(DIVIDER_MIN, Math.min(DIVIDER_MAX, dividerStartWidth + dx, parentW - 340))
    leftWidth.value = newW
  }

  dividerUpHandler = () => {
    isDragging.value = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('mousemove', dividerMoveHandler)
    window.removeEventListener('mouseup', dividerUpHandler)
    dividerMoveHandler = null
    dividerUpHandler = null
  }

  window.addEventListener('mousemove', dividerMoveHandler)
  window.addEventListener('mouseup', dividerUpHandler)
  e.preventDefault()
}

function resetDivider() {
  leftWidth.value = 400
}

onUnmounted(() => {
  if (dividerMoveHandler) window.removeEventListener('mousemove', dividerMoveHandler)
  if (dividerUpHandler) window.removeEventListener('mouseup', dividerUpHandler)
})

// 新步骤出现时自动滚到底部
watch(() => sse.steps.value.length, () => {
  if (autoScroll.value && scrollRef.value) {
    requestAnimationFrame(() => {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
    })
  }
})

// 用户手动滚动时判断是否应继续自动跟随
function onScroll() {
  if (!scrollRef.value) return
  const el = scrollRef.value
  const threshold = 50
  autoScroll.value = (el.scrollHeight - el.scrollTop - el.clientHeight) < threshold
}

const completedSteps = computed(() =>
  sse.steps.value.filter(s => s.status === 'completed')
)

// 切换到「可观测性」Tab 时加载 trace/log/resume_point
watch(activeTab, (tab) => {
  if (tab === 'observability') {
    obs.fetchRun(runId)
  }
})

// 运行完成时（SSE run_completed），若正在查看可观测 Tab 则增量刷新
watch(() => sse.runCompleted.value, (done) => {
  if (done && activeTab.value === 'observability') {
    obs.fetchRun(runId)
  }
})

onMounted(async () => {
  // 先加载历史步骤
  let runIsTerminal = false
  try {
    const res = await agentApi.runs.getAgentRun(runId)

    // 立即判断 run 终态 — 不依赖 setTimeout 时序
    if (res.data?.run) {
      const rs = res.data.run.status
      if (['completed', 'failed', 'cancelled', 'waiting_hitl', 'expired'].includes(rs)) {
        runIsTerminal = true
      }
    }

    if (res.data?.steps) {
      // 历史运行：逐条延迟追加，模拟一步步调查过程
      const stepDelay = 1000  // 每条间隔 1 秒（打字机效果自然覆盖）
      const steps = res.data.steps
      let delay = 0

      for (const step of steps) {
        // 解析 step 数据
        const oj = step.output_json
        const ej = step.evidence_json
        let output = ''
        let evidence = { data_sources: [], evidence: [] }

        if (oj) {
          if (typeof oj === 'string') {
            try {
              const parsed = JSON.parse(oj)
              output = parsed.output || parsed.summary || ''
            } catch {
              output = oj
            }
          } else {
            output = oj.output || oj.summary || ''
          }
        }

        if (ej) {
          if (typeof ej === 'string') {
            try { evidence = JSON.parse(ej) } catch { /* keep default */ }
          } else {
            evidence = ej
          }
        }

        const stepData = {
          id: step.id,
          step_id: String(step.id),
          agent: step.agent || '',
          stage: step.stage || '',
          status: step.status || 'completed',
          output,
          evidence,
          evidence_json: evidence,
          started_at: step.created_at,
          timestamp: step.created_at,
        }

        const currentDelay = delay
        setTimeout(() => {
          sse.loadHistoricalStep(stepData)
        }, currentDelay)
        delay += stepDelay
      }

      // 终态 run → 立即标记，避免无谓的 SSE 连接
      if (runIsTerminal) {
        sse.runCompleted.value = true
      }
      // 非终态 run：runCompleted 保持 false → SSE 保持连接
      // 待后端推 run_completed 事件后由 handleRunCompleted 接管
    } else if (runIsTerminal) {
      sse.runCompleted.value = true
    }
  } catch (e) {
    // 静默失败
  } finally {
    loading.value = false
  }
  // 只有运行未完成时才建立 SSE 连接
  if (!sse.runCompleted.value) {
    sse.connect(runId)
  }

  // 滚动监听
  if (scrollRef.value) {
    scrollRef.value.addEventListener('scroll', onScroll)
  }
})

onUnmounted(() => {
  sse.disconnect()
  if (scrollRef.value) {
    scrollRef.value.removeEventListener('scroll', onScroll)
  }
})

function onGraphNodeClick(node) {
  // 联动左栏：查找与该节点相关的步骤，滚动到对应卡片
  // 节点可能已被聚合（同名 process 合并），用 originalIds 匹配
  const targetIds = node.originalIds || [node.id]
  const stepIdx = sse.steps.value.findIndex(s => {
    const ev = s.evidence_json || {}
    const sources = ev.data_sources || []
    if (Array.isArray(sources) && sources.length > 0) {
      return sources.some(src => targetIds.includes(src.id))
    }
    // 历史数据可能没规范化到 data_sources，fallback 到 step.evidence_json 直接匹配
    return targetIds.some(id => JSON.stringify(ev).includes(id))
  })
  if (stepIdx >= 0 && scrollRef.value) {
    const cards = scrollRef.value.querySelectorAll('.step-card')
    if (cards[stepIdx]) {
      cards[stepIdx].scrollIntoView({ behavior: 'smooth', block: 'center' })
      cards[stepIdx].classList.add('highlight-flash')
      setTimeout(() => cards[stepIdx].classList.remove('highlight-flash'), 2000)
    }
  }
}

function goBack() {
  router.push('/agent-orchestration')
}
</script>

<style scoped>
.agent-run-detail {
  height: calc(100vh - 52px);
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-subtle);
}
.detail-topbar {
  display: flex;
  align-items: center;
  padding: 0 16px;
  height: 42px;
  background: var(--color-canvas-default);
  border-bottom: 0.5px solid var(--color-border-default);
  flex-shrink: 0;
}
.dt-tabs {
  display: flex;
  gap: 4px;
}
.dt-tabs button {
  padding: 6px 14px;
  font-size: 12px;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle);
  cursor: pointer;
  border-radius: 4px;
}
.dt-tabs button.active {
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
  font-weight: 500;
}
.dt-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}
.dt-run-id {
  font-size: 11px;
  font-family: monospace;
  color: var(--color-fg-subtle);
}
.dt-close {
  padding: 4px 10px;
  font-size: 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  color: var(--color-fg-subtle);
}
.detail-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}
.left-panel {
  flex: none;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 280px;
  max-width: 1200px;
}
.lp-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}
.lp-loading, .lp-empty {
  text-align: center;
  padding: 40px;
  color: var(--color-fg-subtle);
  font-size: 13px;
}
.right-panel {
  flex: 1;
  min-width: 300px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 可拖拽分隔条 */
.divider-bar {
  width: 8px;
  flex-shrink: 0;
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  position: relative;
  transition: background 0.15s;
  z-index: 5;
}
.divider-bar:hover,
.is-dragging .divider-bar {
  background: var(--color-accent-subtle, #eff6ff);
}
.divider-dots {
  display: flex;
  flex-direction: column;
  gap: 3px;
  pointer-events: none;
}
.divider-dots span {
  display: block;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--color-border-default, #cbd5e1);
  transition: background 0.15s;
}
.divider-bar:hover .divider-dots span,
.is-dragging .divider-dots span {
  background: var(--color-accent-fg, #2563eb);
}
.rp-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--color-fg-subtle);
  font-size: 13px;
}
.rp-hint {
  font-size: 11px;
  color: var(--color-fg-light);
  margin-top: 4px;
}
.conclusion-panel {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.observability-panel {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.obs-loading, .obs-empty {
  text-align: center;
  padding: 40px;
  color: var(--color-fg-subtle);
  font-size: 13px;
}
.obs-section { margin-bottom: 18px; }
.obs-section h3 {
  font-size: 14px;
  font-weight: 500;
  margin: 0 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.obs-count {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle);
}
.obs-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 8px;
  padding: 10px 12px;
}
.obs-logs {
  max-height: 360px;
  overflow-y: auto;
}
.obs-resume {
  background: var(--color-warning-subtle, rgba(245,158,11,0.08));
}
.cp-section {
  margin-bottom: 16px;
}
.cp-section h3 {
  font-size: 14px;
  font-weight: 500;
  margin: 0 0 8px;
}
.cp-section h4 {
  font-size: 13px;
  font-weight: 500;
  margin: 0 0 4px;
  color: var(--color-accent-fg);
}
.cp-output {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-fg-default);
  background: var(--color-canvas-inset);
  padding: 8px;
  border-radius: 4px;
  max-height: 300px;
  overflow-y: auto;
}
.sse-status {
  flex-shrink: 0;
  height: 28px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  font-size: 11px;
  color: var(--color-fg-subtle);
  background: var(--color-canvas-default);
  border-top: 0.5px solid var(--color-border-default);
}
.sse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #E74C3C;
}
.sse-status.connected .sse-dot {
  background: #2ECC71;
}
.sse-status.archived .sse-dot {
  background: #3498DB;
}
.sse-reconnect {
  margin-left: auto;
  padding: 2px 8px;
  font-size: 10px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  background: var(--color-canvas-subtle);
  cursor: pointer;
  color: var(--color-accent-fg);
}

.step-card.highlight-flash {
  animation: hl-flash 0.5s ease 3;
}
@keyframes hl-flash {
  0%, 100% { background: var(--color-canvas-default); }
  50% { background: var(--color-accent-subtle); }
}

/* 响应式: <1024px 上下布局 */
@media (max-width: 1023px) {
  .detail-body { flex-direction: column; }
  .right-panel { width: 100%; height: 40%; border-left: none; border-top: 0.5px solid var(--color-border-default); }
  .divider-bar { display: none; }
}
</style>
