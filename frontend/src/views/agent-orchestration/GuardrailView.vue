<template>
  <div class="guardrail-view">
    <!-- 顶部操作栏 -->
    <div class="gv-toolbar">
      <div class="gv-title">
        <h2>护栏与安全</h2>
        <span class="gv-sub">F8 · 动作白名单 / 高危确认 / 回滚预案（Mock 适配层）</span>
      </div>
      <div class="gv-actions">
        <el-button type="primary" @click="openCreate" :icon="PlusIcon">新建策略</el-button>
        <el-button @click="refreshAll" :loading="store.loading">刷新</el-button>
      </div>
    </div>

    <!-- 指标条 -->
    <div class="gv-stats">
      <div class="gv-stat">
        <span class="gs-label">策略总数</span>
        <span class="gs-value">{{ store.policies.length }}</span>
      </div>
      <div class="gv-stat">
        <span class="gs-label">已启用</span>
        <span class="gs-value gs-green">{{ store.enabledCount }}</span>
      </div>
      <div class="gv-stat">
        <span class="gs-label">命中拦截</span>
        <span class="gs-value gs-red">{{ store.blockedCount }}</span>
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
          empty-text="暂无策略"
        >
          <el-table-column prop="policy_id" label="策略 ID" min-width="150">
            <template #default="{ row }">
              <span class="gv-mono">{{ row.policy_id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="action_pattern" label="动作模式" min-width="150">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" class="gv-mono">{{ row.action_pattern }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="风险" width="90">
            <template #default="{ row }">
              <span class="gv-risk" :style="{ color: riskColor(row.risk_level) }">
                {{ store.riskLabel(row.risk_level) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="确认" width="70">
            <template #default="{ row }">
              <el-icon v-if="row.require_confirm" color="#F59E0B"><WarningFilled /></el-icon>
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
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 命中记录 -->
        <h3 class="gv-section gv-mt">命中记录 ({{ store.hits.length }})</h3>
        <el-table :data="store.hits" class="gv-table" empty-text="暂无命中记录" size="small">
          <el-table-column prop="timestamp" label="时间" width="180">
            <template #default="{ row }">{{ fmtTime(row.timestamp) }}</template>
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
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag :type="row.passed ? 'success' : 'danger'" size="small" effect="light">
                {{ row.passed ? '放行' : '拦截' }}
              </el-tag>
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
            class="gv-mono"
            @keyup.enter="runEvaluate"
          >
            <template #prepend>action</template>
          </el-input>
          <el-button
            type="primary"
            class="gv-eval-btn"
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
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.submitting" @click="submitForm">保存</el-button>
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
function riskColor(level) {
  return { low: '#22C55E', medium: '#3B82F6', high: '#F59E0B', critical: '#EF4444' }[level] || '#94A3B8'
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

async function refreshAll() {
  await Promise.all([store.fetchPolicies(), store.fetchHits()])
}

onMounted(refreshAll)
</script>

<style scoped>
.guardrail-view { padding: 16px; }
.gv-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.gv-title h2 { margin: 0; font-size: 18px; font-weight: 600; }
.gv-sub { display: block; font-size: 12px; color: var(--color-fg-subtle); margin-top: 2px; }
.gv-actions { display: flex; gap: 8px; }

.gv-stats { display: flex; gap: 12px; margin-bottom: 16px; }
.gv-stat {
  flex: 1; max-width: 200px; background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default); border-radius: 8px;
  padding: 12px 16px; display: flex; flex-direction: column; gap: 4px;
}
.gs-label { font-size: 12px; color: var(--color-fg-subtle); }
.gs-value { font-size: 22px; font-weight: 700; color: var(--color-fg-default); font-family: ui-monospace, monospace; }
.gs-green { color: #22C55E; }
.gs-red { color: #EF4444; }

.gv-body { display: flex; gap: 16px; align-items: flex-start; }
.gv-main { flex: 1; min-width: 0; }
.gv-side { width: 320px; flex-shrink: 0; }

.gv-section { font-size: 14px; font-weight: 500; margin: 0 0 10px; }
.gv-mt { margin-top: 22px; }

.gv-table { background: var(--color-canvas-default); border-radius: 8px; }
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.gv-dim { color: var(--color-fg-subtle); }
.gv-risk { font-weight: 600; font-size: 13px; }

.gv-eval-card {
  background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default);
  border-radius: 8px; padding: 16px;
}
.gv-hint { font-size: 12px; color: var(--color-fg-subtle); margin: 0 0 12px; line-height: 1.5; }
.gv-hint code, .gv-eval-card code { background: var(--color-canvas-inset); padding: 1px 5px; border-radius: 4px; }
.gv-eval-btn { width: 100%; margin-top: 12px; }
.gv-eval-result { margin-top: 14px; padding-top: 12px; border-top: 0.5px solid var(--color-border-default); }
.gv-result-label { font-size: 12px; color: var(--color-fg-subtle); margin-bottom: 8px; }

.gv-form { margin-top: 8px; }
.gv-full { width: 100%; }

@media (max-width: 1100px) {
  .gv-body { flex-direction: column; }
  .gv-side { width: 100%; }
}
</style>
