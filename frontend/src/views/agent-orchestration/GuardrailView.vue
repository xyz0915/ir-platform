<template>
  <div class="guardrail-view">
    <!-- 顶部操作栏（页面标题由 AgentOrchestrationLayout 顶部提供） -->
    <div class="gv-toolbar">
      <span class="gv-sub">F8 · 动作白名单 / 高危确认 / 回滚预案（Mock 适配层）</span>
      <div class="gv-actions">
        <el-button class="gv-btn-dark" @click="openCreate" :icon="PlusIcon">新建策略</el-button>
        <el-button class="gv-btn-outline" @click="refreshAll" :loading="store.loading">刷新</el-button>
      </div>
    </div>

    <!-- 指标条：近黑等宽数字，无彩色强调 -->
    <div class="gv-stats">
      <div class="gv-stat">
        <span class="gs-label">策略总数</span>
        <span class="gs-value">{{ store.policies.length }}</span>
      </div>
      <div class="gv-stat">
        <span class="gs-label">已启用</span>
        <span class="gs-value">{{ store.enabledCount }}</span>
      </div>
      <div class="gv-stat">
        <span class="gs-label">命中拦截</span>
        <span class="gs-value">{{ store.blockedCount }}</span>
      </div>
    </div>

    <div class="gv-body">
      <!-- 左：策略列表 -->
      <div class="gv-main">
        <h3 class="gv-section">护栏策略 ({{ store.policies.length }})</h3>
        <el-table
          :data="store.policies"
          v-loading="store.loading"
          row-key="policy_id"
          class="gv-table"
        >
          <template #empty>
            <div class="gv-empty">
              <p class="gv-empty-text">暂无策略</p>
              <el-button link class="gv-empty-action" @click="openCreate">新建第一条策略</el-button>
            </div>
          </template>
          <el-table-column prop="policy_id" label="策略 ID" min-width="150">
            <template #default="{ row }">
              <span class="gv-mono">{{ row.policy_id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="action_pattern" label="动作模式" min-width="150">
            <template #default="{ row }">
              <span class="gv-pattern gv-mono">{{ row.action_pattern }}</span>
            </template>
          </el-table-column>
          <el-table-column label="风险" width="90">
            <template #default="{ row }">
              <span class="gv-risk">
                <span class="gv-risk-dot" />
                {{ store.riskLabel(row.risk_level) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="确认" width="70">
            <template #default="{ row }">
              <el-icon v-if="row.require_confirm" class="gv-confirm-icon"><WarningFilled /></el-icon>
              <span v-else class="gv-dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="回滚预案" min-width="200">
            <template #default="{ row }">
              <span class="gv-dim" :title="row.rollback_plan">{{ row.rollback_plan || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-switch
                :model-value="row.enabled"
                @change="(v) => toggleEnabled(row, v)"
                inline-prompt
                active-text="开"
                inactive-text="关"
                class="gv-switch"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link class="gv-btn-link" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link class="gv-btn-delete" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 命中记录 -->
        <h3 class="gv-section gv-mt">命中记录 ({{ store.hits.length }})</h3>
        <el-table :data="store.hits" class="gv-table" size="small">
          <template #empty>
            <div class="gv-empty">
              <p class="gv-empty-text">暂无命中记录</p>
            </div>
          </template>
          <el-table-column prop="timestamp" label="时间" width="130">
            <template #default="{ row }">{{ relativeTime(row.timestamp) }}</template>
          </el-table-column>
          <el-table-column prop="policy_id" label="策略" min-width="140">
            <template #default="{ row }"><span class="gv-mono">{{ row.policy_id }}</span></template>
          </el-table-column>
          <el-table-column prop="action" label="动作" min-width="200">
            <template #default="{ row }"><span class="gv-mono">{{ row.action }}</span></template>
          </el-table-column>
          <el-table-column prop="run_id" label="运行" width="120">
            <template #default="{ row }"><span class="gv-mono">{{ row.run_id }}</span></template>
          </el-table-column>
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <span class="gv-result">
                <span class="gv-result-dot" :class="row.passed ? 'ok' : 'block'" />
                {{ row.passed ? '放行' : '拦截' }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 右：评估测试器 -->
      <div class="gv-side">
        <div class="gv-eval-card">
          <h3 class="gv-section">护栏评估测试</h3>
          <p class="gv-hint">输入一个拟执行动作（如 <code>host:isolate:WIN-EXP-01</code>），实时计算护栏结果。</p>
          <el-input
            v-model="evalAction"
            placeholder="action，如 host:isolate:WIN-EXP-01"
            class="gv-mono gv-eval-input"
            @keyup.enter="runEvaluate"
          >
            <template #prepend>action</template>
          </el-input>
          <el-button
            class="gv-btn-dark gv-eval-btn"
            :loading="store.submitting"
            @click="runEvaluate"
          >计算护栏结果</el-button>

          <div v-if="store.lastResult" class="gv-eval-result">
            <div class="gv-result-label">评估结果</div>
            <GuardrailChip :result="store.lastResult" />
          </div>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑 对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogMode === 'create' ? '新建护栏策略' : '编辑护栏策略'"
      width="560px"
      @closed="resetForm"
    >
      <el-form :model="form" label-width="96px" class="gv-form">
        <el-form-item label="策略 ID" v-if="dialogMode === 'create'">
          <el-input v-model="form.policy_id" placeholder="留空将自动生成 gp-xxxx" class="gv-mono" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="策略名称" />
        </el-form-item>
        <el-form-item label="动作模式">
          <el-input v-model="form.action_pattern" placeholder="如 host:isolate:*" class="gv-mono" />
        </el-form-item>
        <el-form-item label="白名单">
          <el-input
            v-model="whitelistText"
            type="textarea"
            :rows="2"
            placeholder="多个动作以逗号分隔，如 host:isolate:WIN-EXP-01,host:isolate:WIN-EXP-02"
            class="gv-mono"
          />
        </el-form-item>
        <el-form-item label="风险级别">
          <el-select v-model="form.risk_level" class="gv-full">
            <el-option label="低" value="low" />
            <el-option label="中" value="medium" />
            <el-option label="高" value="high" />
            <el-option label="严重" value="critical" />
          </el-select>
        </el-form-item>
        <el-form-item label="强制确认">
          <el-switch v-model="form.require_confirm" />
        </el-form-item>
        <el-form-item label="回滚预案">
          <el-input v-model="form.rollback_plan" type="textarea" :rows="2" placeholder="回滚预案描述" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button class="gv-btn-outline" @click="dialogVisible = false">取消</el-button>
        <el-button class="gv-btn-dark" :loading="store.submitting" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus as PlusIcon, WarningFilled } from '@element-plus/icons-vue'
import { useGuardrailStore } from '@/stores/guardrail'
import GuardrailChip from '@/components/agents/GuardrailChip.vue'
import { parseServerTime } from '@/utils/time'

const store = useGuardrailStore()

// ===== 评估测试器 =====
const evalAction = ref('host:isolate:WIN-EXP-01')

async function runEvaluate() {
  const action = evalAction.value.trim()
  if (!action) {
    ElMessage.warning('请输入待评估的动作')
    return
  }
  await store.evaluate(action, { run_id: 'eval' })
}

// ===== 策略 CRUD 对话框 =====
const dialogVisible = ref(false)
const dialogMode = ref('create') // create | edit
const whitelistText = ref('')
const form = ref(emptyForm())

function emptyForm() {
  return {
    policy_id: '',
    name: '',
    action_pattern: '',
    whitelist: [],
    risk_level: 'high',
    require_confirm: true,
    rollback_plan: '',
    enabled: true,
  }
}

function resetForm() {
  form.value = emptyForm()
  whitelistText.value = ''
}

function openCreate() {
  dialogMode.value = 'create'
  resetForm()
  dialogVisible.value = true
}

function openEdit(row) {
  dialogMode.value = 'edit'
  form.value = {
    policy_id: row.policy_id,
    name: row.name,
    action_pattern: row.action_pattern,
    whitelist: Array.isArray(row.whitelist) ? [...row.whitelist] : [],
    risk_level: row.risk_level,
    require_confirm: !!row.require_confirm,
    rollback_plan: row.rollback_plan || '',
    enabled: !!row.enabled,
  }
  whitelistText.value = form.value.whitelist.join(', ')
  dialogVisible.value = true
}

async function submitForm() {
  const whitelist = whitelistText.value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const payload = { ...form.value, whitelist }
  try {
    if (dialogMode.value === 'create') {
      await store.createPolicy(payload)
      ElMessage.success('策略已创建')
    } else {
      await store.updatePolicy(payload)
      ElMessage.success('策略已更新')
    }
    dialogVisible.value = false
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.message || e))
  }
}

async function toggleEnabled(row, val) {
  try {
    await store.updatePolicy({ ...row, enabled: val })
  } catch (e) {
    ElMessage.error('状态切换失败')
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除策略「${row.name}」( ${row.policy_id} )？`, '删除确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await store.deletePolicy(row.policy_id)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.message || e))
  }
}

// ===== 工具 =====
/** 命中记录相对时间：刚刚 / X 分钟前 / X 小时前 / X 天前 */
function relativeTime(iso) {
  if (!iso) return '—'
  const t = parseServerTime(iso)
  if (!t) return iso
  const diffMs = Date.now() - t.getTime()
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return '刚刚'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  return `${day} 天前`
}

async function refreshAll() {
  await Promise.all([store.fetchPolicies(), store.fetchHits()])
}

onMounted(refreshAll)
</script>

<style scoped>
.guardrail-view { padding: 16px; }

/* ===== 顶部操作栏 ===== */
.gv-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; gap: 8px; }
.gv-sub { font-size: 12px; color: var(--color-fg-subtle); }
.gv-actions { display: flex; gap: 8px; }

/* ===== 指标条：近黑等宽数字 ===== */
.gv-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.gv-stat {
  flex: 1; min-width: 150px; max-width: 200px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 6px;
  min-height: 82px; justify-content: center;
}
.gs-label { font-size: 12px; font-weight: 500; color: #6b7280; }
.gs-value {
  font-size: 20px; font-weight: 600; color: #111827;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  line-height: 1.2; letter-spacing: -0.3px;
}

/* ===== 主 / 次 / link 按钮 ===== */
.gv-btn-dark {
  --el-button-bg-color: #111827;
  --el-button-border-color: #111827;
  --el-button-text-color: #fff;
  --el-button-hover-bg-color: #1f2937;
  --el-button-hover-border-color: #1f2937;
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: #1f2937;
  --el-button-active-border-color: #1f2937;
}
.gv-btn-outline {
  --el-button-bg-color: #fff;
  --el-button-border-color: #d1d5db;
  --el-button-text-color: #111827;
  --el-button-hover-bg-color: #111827;
  --el-button-hover-border-color: #111827;
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: #1f2937;
  --el-button-active-border-color: #1f2937;
  --el-button-active-text-color: #fff;
}
.gv-btn-link {
  --el-button-text-color: #111827;
  --el-button-hover-text-color: #4b5563;
  font-size: 12px;
}
.gv-btn-delete {
  --el-button-text-color: #9ca3af;
  --el-button-hover-text-color: #dc2626;
  font-size: 12px;
}

/* ===== 布局 ===== */
.gv-body { display: flex; gap: 16px; align-items: flex-start; }
.gv-main { flex: 1; min-width: 0; }
.gv-side { width: 320px; flex-shrink: 0; }

.gv-section { font-size: 13px; font-weight: 600; margin: 0 0 10px; color: #111827; }
.gv-mt { margin-top: 22px; }

/* ===== 表格：近黑表头 / 紧凑行 ===== */
.gv-table {
  border-radius: 10px;
  --el-table-border-color: var(--color-border-default);
  --el-table-header-bg-color: var(--color-canvas-subtle);
  --el-table-header-text-color: #6b7280;
  --el-table-row-hover-bg-color: var(--color-canvas-subtle);
}
.gv-table :deep(th.el-table__cell) {
  font-size: 12px; font-weight: 500; padding: 8px 10px; height: 36px;
}
.gv-table :deep(td.el-table__cell) {
  padding: 8px 10px; font-size: 12px; color: var(--color-fg-default); height: 38px;
}

.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.gv-dim { color: var(--color-fg-subtle); }

/* 动作模式：代码块式 chip，非 el-tag */
.gv-pattern {
  display: inline-block; padding: 1px 6px; border-radius: 4px;
  background: var(--color-canvas-inset); color: #4b5563; font-size: 11px;
}

/* 风险：单色灰点 + 文字 */
.gv-risk { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #4b5563; }
.gv-risk-dot { width: 6px; height: 6px; border-radius: 50%; background: #9ca3af; flex-shrink: 0; }

.gv-confirm-icon { color: #9ca3af; font-size: 14px; }

/* 启停开关：active 色收敛为近黑 */
.gv-switch :deep(.el-switch.is-checked .el-switch__core) {
  background-color: #111827; border-color: #111827;
}

/* 命中结果：单色点 + 文字 */
.gv-result { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #4b5563; }
.gv-result-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.gv-result-dot.ok { background: #16a34a; }
.gv-result-dot.block { background: #dc2626; }

/* ===== 评估测试器 ===== */
.gv-eval-card {
  background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default);
  border-radius: 10px; padding: 16px;
}
.gv-hint { font-size: 12px; color: var(--color-fg-subtle); margin: 0 0 12px; line-height: 1.5; }
.gv-hint code, .gv-eval-card code { background: var(--color-canvas-inset); padding: 1px 5px; border-radius: 4px; }
.gv-eval-input :deep(.el-input-group__prepend) {
  background: var(--color-canvas-subtle); color: #6b7280; font-size: 12px; border-color: var(--color-border-default);
}
.gv-eval-input :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--color-border-default) inset; border-radius: 0 8px 8px 0;
}
.gv-eval-input :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px #111827 inset; }
.gv-eval-btn { width: 100%; margin-top: 12px; }
.gv-eval-result { margin-top: 14px; padding-top: 12px; border-top: 0.5px solid var(--color-border-default); }
.gv-result-label { font-size: 12px; color: var(--color-fg-subtle); margin-bottom: 8px; }

/* ===== 自定义空状态 ===== */
.gv-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 40px 0; }
.gv-empty-text { font-size: 13px; color: #9ca3af; margin: 0; }
.gv-empty-action {
  --el-button-text-color: #111827;
  --el-button-hover-text-color: #4b5563;
  font-size: 12px;
}

.gv-form { margin-top: 8px; }
.gv-full { width: 100%; }

@media (max-width: 1100px) {
  .gv-body { flex-direction: column; }
  .gv-side { width: 100%; }
}
</style>
