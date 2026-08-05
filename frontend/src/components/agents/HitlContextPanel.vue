<template>
  <div class="hitl-context" v-if="isAdmin">
    <div v-if="!task" class="hcp-empty">
      <p class="hcp-empty-text">选择左侧待审任务查看上下文</p>
    </div>

    <template v-else>
      <!-- 头部 -->
      <div class="hcp-head">
        <div class="hcp-agent">
          <el-icon><Cpu /></el-icon>
          {{ task.agent_name || '处置响应 Agent' }}
        </div>
        <StatusBadge type="hitl" :value="task.status" />
      </div>

      <!-- 拟执行动作 -->
      <div class="hcp-action">{{ displayAction }}</div>

      <!-- 影响范围 -->
      <div class="hcp-section">
        <div class="hcp-k">影响范围</div>
        <div class="hcp-v">{{ impactScope }}</div>
      </div>

      <!-- 触发上下文 -->
      <div class="hcp-section" v-if="context && Object.keys(context).length">
        <div class="hcp-k">触发上下文</div>
        <div class="hcp-kv" v-for="(v, k) in context" :key="k">
          <span class="hcp-kv-k">{{ ctxLabel(k) }}</span>
          <span class="hcp-kv-v">{{ v }}</span>
        </div>
      </div>

      <!-- 护栏联动结果（Q2 接口位：直接渲染 guardrail_result，缺失则热插拔计算） -->
      <div class="hcp-section">
        <div class="hcp-k">护栏校验</div>
        <GuardrailChip :result="guardrailResult" />
        <div v-if="guardrailResult?.policy_id && guardrailResult.requires_rollback_plan" class="hcp-rollback">
          <el-icon><RefreshLeft /></el-icon>
          回滚预案：{{ rollbackPlan }}
        </div>
      </div>

      <!-- 智能体建议 -->
      <div class="hcp-section" v-if="task.reason">
        <div class="hcp-k">智能体建议</div>
        <div class="hcp-v hcp-reason">{{ task.reason }}</div>
      </div>

      <!-- 决议操作 -->
      <div class="hcp-actions">
        <el-input v-model="rejectReason" size="small" placeholder="拒绝原因（可选）" class="hcp-reject" :disabled="busy" />
        <el-button class="btn-approve" size="small" :loading="busy" @click="onApprove">
          <el-icon><Select /></el-icon> 批准执行
        </el-button>
        <el-button link class="btn-reject" size="small" :loading="busy" @click="onReject">
          <el-icon><CloseBold /></el-icon> 拒绝
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Cpu, RefreshLeft, Select, CloseBold } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useAgentOrchestrationStore } from '@/stores/agents'
import { useGuardrail } from '@/api/agent'
import StatusBadge from './StatusBadge.vue'
import GuardrailChip from './GuardrailChip.vue'

const props = defineProps({
  /** HitlTask（对齐后端 hitl_approval 表 + demo guardrail_result） */
  task: { type: Object, default: null },
})
const emit = defineEmits(['resolved'])

const authStore = useAuthStore()
const store = useAgentOrchestrationStore()
const guardrailApi = useGuardrail()

const isAdmin = computed(() => authStore.user?.role === 'admin')
const busy = ref(false)
const rejectReason = ref('')

// 后端若未携带 guardrail_result，则用热插拔 evaluate 计算（当前 Mock）
const guardrailResult = ref(null)

const displayAction = computed(() => props.task?.action || parseTarget(props.task)?.action || '—')
const impactScope = computed(() => props.task?.impact_scope || describeTarget(props.task) || '—')

const context = computed(() => {
  const t = props.task
  if (!t) return {}
  if (t.context && typeof t.context === 'object' && Object.keys(t.context).length) return t.context
  const tg = parseTarget(t)
  return tg || {}
})

const rollbackPlan = computed(() => {
  const r = guardrailResult.value
  if (!r || !r.policy_id) return '—'
  // 从策略命中推断：演示数据回滚预案在 guardrail mock 中；这里展示策略级提示
  return `policy=${r.policy_id}（执行前确认回滚路径）`
})

watch(
  () => props.task,
  (t) => { if (t) resolveGuardrail(t) },
  { immediate: false }
)

onMounted(() => {
  if (props.task) resolveGuardrail(props.task)
})

function resolveGuardrail(task) {
  if (task?.guardrail_result) {
    guardrailResult.value = task.guardrail_result
  } else {
    // 热插拔：后端 F8 就绪后切换为真实评估，调用方零改动
    guardrailApi.evaluate(displayAction.value, { run_id: task.run_id, ...context.value })
      .then((res) => { guardrailResult.value = res.data })
      .catch(() => { guardrailResult.value = null })
  }
}

function parseTarget(task) {
  if (!task) return {}
  const raw = task.target_json || task.target
  if (typeof raw === 'string' && raw) {
    try { return JSON.parse(raw) } catch { return {} }
  }
  return raw && typeof raw === 'object' ? raw : {}
}

function describeTarget(task) {
  const t = parseTarget(task)
  if (!t || !Object.keys(t).length) return ''
  const parts = []
  if (t.ip) parts.push(`IP: ${t.ip}`)
  if (t.host) parts.push(`主机: ${t.host}`)
  if (t.host_id) parts.push(`host_id: ${t.host_id}`)
  if (t.path) parts.push(`路径: ${t.path}`)
  return parts.length ? parts.join('，') : JSON.stringify(t)
}

function ctxLabel(k) {
  return (
    {
      trigger_agent: '触发 Agent',
      evidence: '证据',
      risk: '风险',
      suggested_by: '来源',
    }[k] || k
  )
}

async function onApprove() {
  busy.value = true
  try {
    await store.approve(props.task.run_id, props.task.id)
    ElMessage.success(`已批准处置：${displayAction.value}`)
    await store.fetchApprovals()
    emit('resolved')
  } catch (e) { /* 拦截器已提示 */ } finally { busy.value = false }
}

async function onReject() {
  busy.value = true
  try {
    await store.reject(props.task.run_id, props.task.id, rejectReason.value || undefined)
    ElMessage.warning(`已拒绝处置：${displayAction.value}`)
    await store.fetchApprovals()
    emit('resolved')
  } catch (e) { /* 拦截器已提示 */ } finally { busy.value = false }
}
</script>

<style scoped>
.hitl-context { padding: 4px; }
.hcp-empty { display: flex; align-items: center; justify-content: center; padding: 48px 0; }
.hcp-empty-text { font-size: 13px; color: #9ca3af; margin: 0; }
.hcp-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.hcp-agent { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: #111827; }
.hcp-action { font-size: 16px; font-weight: 600; color: #111827; padding: 10px 12px; background: var(--color-canvas-subtle); border-radius: 8px; margin-bottom: 12px; border-left: 3px solid #111827; }
.hcp-section { margin-bottom: 14px; }
.hcp-k { font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.hcp-v { font-size: 13px; color: var(--color-fg-default); line-height: 1.6; word-break: break-all; }
.hcp-reason { white-space: pre-wrap; }
.hcp-kv { display: flex; gap: 10px; font-size: 12px; padding: 3px 0; }
.hcp-kv-k { width: 72px; flex-shrink: 0; color: #6b7280; }
.hcp-kv-v { color: var(--color-fg-default); word-break: break-all; }
.hcp-rollback { display: flex; align-items: center; gap: 4px; font-size: 12px; color: #6b7280; margin-top: 8px; }
.hcp-actions { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.hcp-reject { flex: 1; min-width: 160px; max-width: 240px; }

/* 批准：克制绿（白底绿边，hover 反色） */
.btn-approve {
  --el-button-bg-color: #fff;
  --el-button-border-color: #16a34a;
  --el-button-text-color: #16a34a;
  --el-button-hover-bg-color: #16a34a;
  --el-button-hover-border-color: #16a34a;
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: #15803d;
  --el-button-active-border-color: #15803d;
  --el-button-active-text-color: #fff;
}
/* 拒绝：灰 link，hover 红 */
.btn-reject {
  --el-button-text-color: #9ca3af;
  --el-button-hover-text-color: #dc2626;
  font-size: 12px;
}
</style>
