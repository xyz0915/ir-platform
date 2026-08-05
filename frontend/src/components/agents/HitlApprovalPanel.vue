<template>
  <div class="hitl-panel">
    <!-- 非管理员：静默隐藏，不渲染任何 UI（HITL 仅管理员可见） -->
    <div v-if="!isAdmin" class="hitl-empty">
      <p class="hitl-empty-text">HITL 审批仅限管理员操作</p>
    </div>

    <template v-else>
      <!-- 待审批计数 -->
      <div class="hitl-header">
        <span class="hitl-title">
          <el-icon><Stamp /></el-icon>
          待审批处置（{{ pendingList.length }}）
        </span>
        <el-button text size="small" :loading="store.loading" @click="refresh">
          <el-icon><Refresh /></el-icon>
        </el-button>
      </div>

      <div v-if="pendingList.length === 0" class="hitl-empty">
        <p class="hitl-empty-text">暂无待审批处置</p>
      </div>

      <!-- 审批卡片列表 -->
      <div v-for="item in pendingList" :key="item.id" class="hitl-card">
        <div class="hitl-card-head">
          <span class="hitl-status">
            <span class="hitl-status-dot" />
            待审批
          </span>
          <span class="hitl-action">{{ item.action }}</span>
          <span class="hitl-run" @click="openRun(item.run_id)">{{ item.run_id }}</span>
        </div>

        <!-- 处置目标 -->
        <div v-if="hasTarget(item)" class="hitl-row">
          <span class="hitl-label">处置目标</span>
          <span class="hitl-value">{{ targetText(item) }}</span>
        </div>

        <!-- 智能体建议（reason 为 responder 推荐语摘要） -->
        <div v-if="item.reason" class="hitl-row hitl-reason">
          <span class="hitl-label">智能体建议</span>
          <span class="hitl-value">{{ item.reason }}</span>
        </div>

        <!-- 自动回滚预案 -->
        <div v-if="hasRollback(item)" class="hitl-row">
          <span class="hitl-label">回滚预案</span>
          <span class="hitl-value">{{ rollbackText(item) }}</span>
        </div>

        <!-- 决议操作 -->
        <div class="hitl-actions">
          <el-input
            v-model="reasons[item.id]"
            size="small"
            class="hitl-reject-reason"
            placeholder="拒绝原因（可选）"
            :disabled="busy"
          />
          <el-button
            class="btn-approve"
            size="small"
            :loading="busy"
            @click="onApprove(item)"
          >
            <el-icon><Select /></el-icon> 批准执行
          </el-button>
          <el-button
            link
            class="btn-reject"
            size="small"
            :loading="busy"
            @click="onReject(item)"
          >
            <el-icon><CloseBold /></el-icon> 拒绝
          </el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Stamp, Refresh, Select, CloseBold } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useAgentOrchestrationStore } from '@/stores/agents'

const props = defineProps({
  /** 外部传入的待审批列表（可选）；不传则组件自行拉取 */
  approvals: {
    type: Array,
    default: () => [],
  },
})

const authStore = useAuthStore()
const store = useAgentOrchestrationStore()
const router = useRouter()

const busy = ref(false)
const reasons = ref({}) // { [approvalId]: string }

const isAdmin = computed(() => authStore.user?.role === 'admin')

const pendingList = computed(() => {
  if (props.approvals && props.approvals.length) return props.approvals
  return store.approvals
})

onMounted(() => {
  if (isAdmin.value && !props.approvals.length) {
    store.fetchApprovals()
  }
})

function refresh() {
  if (isAdmin.value) store.fetchApprovals()
}

function openRun(runId) {
  if (runId) router.push(`/agent-orchestration?runId=${runId}`)
}

/** hitl_approvals.target_json 反序列化 */
function parse(obj, raw) {
  if (obj && typeof obj === 'object') return obj
  if (typeof raw === 'string' && raw) {
    try {
      return JSON.parse(raw)
    } catch {
      return {}
    }
  }
  return {}
}

function hasTarget(item) {
  const t = parse(item.target, item.target_json)
  return t && Object.keys(t).length > 0
}

function targetText(item) {
  const t = parse(item.target, item.target_json)
  if (!t) return '-'
  // 常见字段：ip / host / host_id / path
  const parts = []
  if (t.ip) parts.push(`IP: ${t.ip}`)
  if (t.host) parts.push(`主机: ${t.host}`)
  if (t.host_id) parts.push(`host_id: ${t.host_id}`)
  if (t.path) parts.push(`路径: ${t.path}`)
  return parts.length ? parts.join('，') : JSON.stringify(t)
}

function hasRollback(item) {
  const r = parse(item.auto_rollback_plan, item.auto_rollback_plan)
  return r && Object.keys(r).length > 0
}

function rollbackText(item) {
  const r = parse(item.auto_rollback_plan, item.auto_rollback_plan)
  if (!r) return '-'
  // 回滚预案可能形如 { steps: [...] } 或直接描述字符串
  if (Array.isArray(r.steps)) return r.steps.join('；')
  if (typeof r === 'object') return Object.entries(r).map(([k, v]) => `${k}: ${v}`).join('；')
  return String(r)
}

async function onApprove(item) {
  busy.value = true
  try {
    await store.approve(item.run_id, item.id)
    ElMessage.success(`已批准处置：${item.action}`)
    await refresh()
    // 通知父级刷新运行列表/详情
    emit('resolved')
  } catch (e) {
    // 错误已由 axios 拦截器提示
  } finally {
    busy.value = false
  }
}

async function onReject(item) {
  busy.value = true
  try {
    await store.reject(item.run_id, item.id, reasons.value[item.id] || undefined)
    ElMessage.warning(`已拒绝处置：${item.action}`)
    await refresh()
    emit('resolved')
  } catch (e) {
    // 错误已由 axios 拦截器提示
  } finally {
    busy.value = false
  }
}

const emit = defineEmits(['resolved'])
</script>

<style scoped>
.hitl-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hitl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hitl-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}

.hitl-empty { display: flex; align-items: center; justify-content: center; padding: 32px 0; }
.hitl-empty-text { font-size: 13px; color: #9ca3af; margin: 0; }

.hitl-card {
  border: 1px solid var(--color-border-default);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--color-canvas-subtle);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hitl-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 待审批状态：单色灰点 + 文字，去 warning 彩色 tag */
.hitl-status { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; color: #4b5563; }
.hitl-status-dot { width: 6px; height: 6px; border-radius: 50%; background: #9ca3af; flex-shrink: 0; }

.hitl-action {
  font-weight: 600;
  color: #111827;
  font-size: 13px;
}

.hitl-run {
  margin-left: auto;
  font-size: 12px;
  color: #111827;
  cursor: pointer;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.hitl-run:hover {
  text-decoration: underline;
}

.hitl-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
  line-height: 1.5;
}

.hitl-label {
  flex-shrink: 0;
  width: 72px;
  color: #6b7280;
}

.hitl-value {
  color: var(--color-fg-default);
  word-break: break-all;
}

.hitl-reason .hitl-value {
  white-space: pre-wrap;
}

.hitl-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

.hitl-reject-reason {
  flex: 1;
  max-width: 220px;
}

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
