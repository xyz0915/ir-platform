<template>
  <div class="policy-page">
    <!-- ===== 页面标题 ===== -->
    <div class="page-header">
      <div class="page-header-left">
        <div class="page-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
          策略配置
        </div>
        <div class="page-sub">检测策略 — 控制哪些规则在哪些场景下触发告警</div>
      </div>
    </div>

    <!-- ===== 双列布局 ===== -->
    <div class="layout">

      <!-- ===== 左侧：策略列表 ===== -->
      <div class="card">
        <div class="list-header">
          <div class="list-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
            检测策略
          </div>
          <button class="btn-icon-circle" title="创建策略" @click="showCreateDialog = true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
        </div>
        <div class="list-body">
          <div
            v-for="p in policies" :key="p.id"
            :class="['strategy-item', { active: selectedId === p.id }]"
            @click="selectPolicy(p.id)"
          >
            <div class="radio-dot" />
            <div class="strategy-name">
              {{ p.name }}
              <span v-if="p.is_active" class="badge badge-active">已激活</span>
            </div>
            <div class="strategy-desc">{{ p.description || '' }}</div>
            <div class="strategy-meta">
              <span style="font-size:11px;color:var(--color-fg-subtle);">{{ p.rule_count || 0 }} 条 · RAG {{ p.enable_rag ? '开' : '关' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== 右侧：策略详情 ===== -->
      <div class="card" v-if="detail">
        <!-- 详情头部 -->
        <div class="detail-header">
          <div class="detail-title">
            <input class="detail-name fi" v-model="editName" placeholder="策略名称" />
          </div>
          <div class="detail-actions">
            <button v-if="!detail.is_active" class="btn btn-primary" @click="handleActivate">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="6"/></svg>
              激活
            </button>
            <button v-else class="btn btn-primary" disabled>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="6"/></svg>
              已激活
            </button>
            <button class="btn btn-default" @click="handleDuplicate">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              复制派生
            </button>
            <button class="btn btn-ghost" @click="handleDelete">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              删除
            </button>
          </div>
        </div>

        <!-- 描述 -->
        <div style="padding:0 20px 16px;">
          <textarea class="fta" v-model="editDesc" placeholder="策略描述" style="min-height:60px;"></textarea>
          <div style="display:flex;gap:8px;margin-top:8px;" v-if="dirty">
            <button class="btn btn-primary" @click="handleSave">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              保存修改
            </button>
            <button class="btn btn-default" @click="cancelEdit">取消</button>
          </div>
        </div>

        <!-- 开关 -->
        <div style="padding:0 20px 20px;">
          <div class="section-title">策略开关</div>
          <div class="toggle-row">
            <label class="toggle">
              <input type="checkbox" v-model="editRag" @change="markDirty" />
              <div class="toggle-slider"></div>
            </label>
            <div class="tl-info">
              <div class="tl-title">RAG 语义分析</div>
              <div class="tl-desc">调用知识库进行语义匹配，增强检测深度 · 增加 30-60s 分析耗时</div>
            </div>
          </div>
          <div class="toggle-row">
            <label class="toggle">
              <input type="checkbox" v-model="editAttackChain" @change="markDirty" />
              <div class="toggle-slider"></div>
            </label>
            <div class="tl-info">
              <div class="tl-title">攻击链检测</div>
              <div class="tl-desc">关联多个发现项，还原攻击者完整攻击链</div>
            </div>
          </div>
        </div>

        <!-- 规则选择 -->
        <div style="padding:0 20px 20px;">
          <div class="section-title">
            规则选择
            <span class="count">已选 <strong style="color:var(--color-success-fg)">{{ selectedRuleIds.length }}</strong> 条 / 策略含 <strong>{{ detail?.rule_count || 0 }}</strong> 条</span>
          </div>

          <div class="rule-filter">
            <select class="select" v-model="filterCategory" @change="fetchRules" style="width:110px;">
              <option value="">全部分类</option>
              <option v-for="c in categories" :key="c" :value="c">{{ catLabel(c) }}</option>
            </select>
            <select class="select" v-model="filterSeverity" @change="fetchRules" style="width:100px;">
              <option value="">全部严重度</option>
              <option value="critical">严重</option>
              <option value="high">高危</option>
              <option value="medium">中危</option>
            </select>
            <div class="search-bar" style="width:160px;">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input v-model="filterKeyword" placeholder="规则名/关键词" @keyup.enter="fetchRules" />
            </div>
            <button class="btn btn-primary" @click="fetchRules">筛选</button>
            <button class="btn btn-default" @click="resetFilters">重置</button>
            <button class="btn btn-primary" @click="saveRules" :disabled="!dirtyRules">保存规则选择</button>
          </div>

          <!-- 规则列表 -->
          <div class="rule-list" v-if="rules.length">
            <div v-for="r in rules" :key="r.id" :class="['rule-item', { checked: r._checked }]">
              <div class="rule-icon">
                <svg v-if="r.category === 'process' || r.category === 'webshell'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 17l6-6-6-6"/><path d="M12 19h8"/></svg>
                <svg v-else-if="r.category === 'connection'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/></svg>
                <svg v-else-if="r.category === 'file'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <svg v-else-if="r.category === 'persistence'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
                <svg v-else-if="r.category === 'logon'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              </div>
              <div class="rule-text">
                <div class="rule-en">{{ r.label || r.name }}</div>
                <div class="rule-cn">{{ r.name }}</div>
              </div>
              <span class="rule-tag">{{ catLabel(r.category) }}</span>
              <span class="sev-dots"><span :class="['sev-dot', r.severity]"></span></span>
              <span style="font-size:10px;color:var(--color-fg-subtle);width:24px;">{{ sevLabel(r.severity) }}</span>
              <label class="toggle">
                <input type="checkbox" :checked="r._checked" @change="onRuleCheck(r, $event.target.checked)" />
                <div class="toggle-slider"></div>
              </label>
            </div>
          </div>
          <div v-else style="padding:24px 0;text-align:center;font-size:12px;color:var(--color-fg-light);">暂无匹配规则</div>

          <!-- 分页 -->
          <div class="rule-page" v-if="ruleTotal > 50">
            <button class="pg-btn" @click="rulePage > 1 && (rulePage--, fetchRules())" :disabled="rulePage <= 1">上一页</button>
            <span class="pg-info">第 {{ rulePage }} / {{ Math.ceil(ruleTotal / 50) || 1 }} 页</span>
            <button class="pg-btn" @click="rulePage < Math.ceil(ruleTotal / 50) && (rulePage++, fetchRules())" :disabled="rulePage >= Math.ceil(ruleTotal / 50)">下一页</button>
          </div>
        </div>

        <!-- info-tip -->
        <div class="info-tip">
          <strong>策略激活提示</strong>：激活策略后分析引擎只执行该策略内的规则。切换策略时当前策略自动停用。无激活策略时降级为全量检测。
          <br><strong>复制派生</strong>：点击"复制派生" → 生成包含完全相同配置和规则的新策略 → 可单独修改规则后独立保存。
        </div>
      </div>

      <!-- 无选中时 -->
      <div class="card empty" v-else>
        <div class="empty-hint">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
          <div class="title">在左侧选择或创建策略</div>
          <div class="desc">选择已有策略查看详情，或创建新策略</div>
        </div>
      </div>
    </div>

    <!-- ===== 新建策略弹窗 ===== -->
    <div v-if="showCreateDialog" class="modal-overlay" @click.self="showCreateDialog = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">新建策略</div>
          <button class="modal-close" @click="showCreateDialog = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="fg">
            <label class="fl">名称</label>
            <input class="fi" v-model="createForm.name" placeholder="输入策略名称" />
          </div>
          <div class="fg" style="margin-bottom:0;">
            <label class="fl">描述</label>
            <textarea class="fta" v-model="createForm.description" placeholder="策略描述"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="showCreateDialog = false">取消</button>
          <button class="btn btn-primary" @click="handleCreate">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getPolicies, getPolicy, createPolicy, updatePolicy,
  deletePolicy, activatePolicy, deactivatePolicy, duplicatePolicy,
  setPolicyRules, getRuleSelector
} from '@/api/policies'

const policies = ref([])
const selectedId = ref(null)
const detail = ref(null)
const showCreateDialog = ref(false)
const createForm = reactive({ name: '', description: '' })

// 编辑缓存
const editName = ref('')
const editDesc = ref('')
const editRag = ref(false)
const editAttackChain = ref(false)
const dirty = ref(false)

// 规则选择
const rules = ref([])
const ruleTotal = ref(0)
const rulePage = ref(1)
const selectedRuleIds = ref([])
const dirtyRules = ref(false)
const filterCategory = ref('')
const filterSeverity = ref('')
const filterKeyword = ref('')
const categories = ['process', 'connection', 'logon', 'file', 'persistence', 'ioc', 'webshell', 'memory']

function sevType(s) { return { critical: 'danger', high: 'warning', medium: 'primary' }[s] || 'info' }
function sevLabel(s) { return { critical: '严重', high: '高危', medium: '中危', low: '低危' }[s] || s || '信息' }
const CAT_LABELS = { process: '进程行为', connection: '网络连接', logon: '登录事件', file: '文件操作', persistence: '持久化', ioc: 'IOC', webshell: 'WebShell', memory: '内存', behavior: '行为', discovery: '发现' }
const TYPE_LABELS = { regex: '正则匹配', list: '列表匹配', behavior: '行为分析', threshold: '阈值检测', attack_chain: '攻击链', composite: '复合规则' }
function catLabel(c) { return CAT_LABELS[c] || c || '-' }
function typeLabel(t) { return TYPE_LABELS[t] || t || '-' }
function catType(c) {
  const m = { process: 'primary', connection: 'warning', logon: 'success', file: 'info', persistence: 'danger', ioc: 'danger', webshell: 'danger', memory: 'warning' }
  return m[c] || ''
}
function typeType(t) {
  const m = { regex: '', list: 'info', behavior: 'primary', threshold: 'warning', attack_chain: 'danger', composite: 'success' }
  return m[t] || ''
}
function markDirty() { dirty.value = true }
function onRuleCheck(row, checked) {
  selectedRuleIds.value = checked
    ? Array.from(new Set([...selectedRuleIds.value, row.id]))
    : selectedRuleIds.value.filter(id => id !== row.id)
  dirtyRules.value = true
}
function rowClass({ row }) {
  return row._checked ? 'rule-row-checked' : ''
}

async function loadPolicies() {
  const res = await getPolicies()
  policies.value = res.data || []
  if (!selectedId.value && policies.value.length > 0) {
    selectedId.value = policies.value[0].id
  }
}

async function selectPolicy(id) {
  if (dirty.value || dirtyRules.value) {
    try {
      await ElMessageBox.confirm('有未保存的修改，是否放弃？', '提示', { confirmButtonText: '放弃', cancelButtonText: '取消', type: 'warning' })
    } catch { return }
  }
  selectedId.value = id
  dirty.value = false
  dirtyRules.value = false
  const res = await getPolicy(id)
  detail.value = res.data || null
  if (detail.value) {
    editName.value = detail.value.name
    editDesc.value = detail.value.description || ''
    editRag.value = !!detail.value.enable_rag
    editAttackChain.value = !!detail.value.enable_attack_chain
    selectedRuleIds.value = (detail.value.rules || []).map(r => r.id)
  }
  await fetchRules()
}

async function fetchRules() {
  const params = { page: rulePage.value, page_size: 50 }
  if (filterCategory.value) params.category = filterCategory.value
  if (filterSeverity.value) params.severity = filterSeverity.value
  if (filterKeyword.value) params.keyword = filterKeyword.value
  const res = await getRuleSelector(params)
  rules.value = (res.data?.items || []).map(r => ({
    ...r,
    // 标记已选中
    _checked: selectedRuleIds.value.includes(r.id)
  }))
  ruleTotal.value = res.data?.total || 0
}

function onRuleSelect(selection) {
  // Element Plus el-table 切换分页时会重置 selection，配合 _checked 字段做最终同步
  const pageIds = rules.value.map(r => r.id)
  const pageSelectedIds = selection.map(r => r.id)
  // 当前页已选的 id = 来自 selectedRuleIds 且在当前页里的
  const fromOtherPages = selectedRuleIds.value.filter(id => !pageIds.includes(id))
  const newSelected = Array.from(new Set([...fromOtherPages, ...pageSelectedIds]))
  // 同步每行 _checked
  rules.value.forEach(r => { r._checked = newSelected.includes(r.id) })
  selectedRuleIds.value = newSelected
  dirtyRules.value = true
}

function resetFilters() {
  filterCategory.value = ''
  filterSeverity.value = ''
  filterKeyword.value = ''
  rulePage.value = 1
  fetchRules()
}

async function saveRules() {
  await setPolicyRules(selectedId.value, selectedRuleIds.value)
  dirtyRules.value = false
  ElMessage.success('规则已保存')
  await selectPolicy(selectedId.value)
}

async function handleSave() {
  await updatePolicy(selectedId.value, {
    name: editName.value,
    description: editDesc.value,
    enable_rag: editRag.value ? 1 : 0,
    enable_attack_chain: editAttackChain.value ? 1 : 0,
  })
  dirty.value = false
  ElMessage.success('已保存')
  await loadPolicies()
}

function cancelEdit() {
  if (detail.value) {
    editName.value = detail.value.name
    editDesc.value = detail.value.description || ''
    editRag.value = !!detail.value.enable_rag
    editAttackChain.value = !!detail.value.enable_attack_chain
  }
  dirty.value = false
}

async function handleActivate() {
  await activatePolicy(selectedId.value)
  ElMessage.success('策略已激活，其余策略已自动停用')
  await loadPolicies()
  await selectPolicy(selectedId.value)
}

async function handleDuplicate() {
  const res = await duplicatePolicy(selectedId.value)
  ElMessage.success('策略已复制派生')
  await loadPolicies()
  selectedId.value = res.data?.id
  await selectPolicy(selectedId.value)
}

async function handleDelete() {
  try {
    await ElMessageBox.confirm('确认删除该策略？', '确认', { type: 'warning' })
  } catch { return }
  await deletePolicy(selectedId.value)
  ElMessage.success('已删除')
  selectedId.value = null
  detail.value = null
  await loadPolicies()
}

async function handleCreate() {
  if (!createForm.name) { ElMessage.warning('请输入策略名称'); return }
  const res = await createPolicy({ name: createForm.name, description: createForm.description })
  showCreateDialog.value = false
  createForm.name = ''
  createForm.description = ''
  ElMessage.success('策略已创建')
  await loadPolicies()
  selectedId.value = res.data?.id
  await selectPolicy(selectedId.value)
}

onMounted(loadPolicies)
</script>

<style scoped>
.policy-page { height: 100%; }

/* ── Header ── */
.page-header { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 20px; padding: 0 2px; }
.page-header-left { flex: 1; }
.page-title { display: flex; align-items: center; gap: 10px; font-size: 20px; font-weight: 500; color: var(--color-fg-default); }
.page-title svg { width: 18px; height: 18px; color: var(--color-fg-muted); }
.page-sub { font-size: 12px; font-weight: 400; color: var(--color-fg-subtle); margin-top: 3px; }

/* ── Layout Grid ── */
.layout { display: grid; grid-template-columns: 320px 1fr; gap: 20px; height: calc(100% - 56px); }

/* ── Buttons ── */
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 30px; padding: 0 12px; font-size: 12px; font-weight: 500; border-radius: 6px; cursor: pointer; transition: all 0.12s; white-space: nowrap; border: 0.5px solid transparent; font-family: inherit; }
.btn:disabled { opacity: 0.4; pointer-events: none; }
.btn-default { background: var(--color-canvas-default); color: var(--color-fg-default); border-color: var(--color-border-default); }
.btn-default:hover { background: var(--color-canvas-subtle); border-color: var(--color-fg-light); }
.btn-primary { background: var(--color-accent-fg); color: white; border-color: var(--color-accent-fg); }
.btn-primary:hover { background: #1d4ed8; }
.btn-ghost { background: transparent; color: var(--color-fg-muted); border-color: transparent; }
.btn-ghost:hover { background: var(--color-canvas-inset); }
.btn-icon-circle { width: 28px; height: 28px; border-radius: 50%; border: 0.5px solid var(--color-accent-fg); background: var(--color-canvas-default); color: var(--color-accent-fg); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.btn-icon-circle:hover { background: var(--color-accent-subtle); }
.btn-icon-circle svg { width: 14px; height: 14px; }
.btn svg { width: 13px; height: 13px; }

/* ── Card ── */
.card { background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default); border-radius: 10px; overflow: hidden; }
.card.empty { display: flex; align-items: center; justify-content: center; }

/* ── Left: Strategy List ── */
.list-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 0.5px solid var(--color-border-default); }
.list-title { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; }
.list-title svg { width: 14px; height: 14px; color: var(--color-fg-muted); }
.list-body { padding: 8px; overflow-y: auto; flex: 1; max-height: calc(100vh - 240px); }

.strategy-item { padding: 12px 14px; border-radius: 6px; cursor: pointer; border: 0.5px solid transparent; transition: all 0.12s; margin-bottom: 4px; position: relative; }
.strategy-item:hover { background: var(--color-canvas-inset); }
.strategy-item.active { background: var(--color-accent-subtle); border-color: var(--color-accent-fg); }
.strategy-item .radio-dot { position: absolute; left: -3px; top: 16px; width: 6px; height: 6px; border-radius: 50%; background: var(--color-fg-light); }
.strategy-item.active .radio-dot { background: var(--color-accent-fg); }
.strategy-name { font-size: 13px; font-weight: 500; color: var(--color-fg-default); margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
.strategy-item.active .strategy-name { color: var(--color-accent-fg); }
.strategy-desc { font-size: 11px; color: var(--color-fg-subtle); }
.strategy-meta { display: flex; align-items: center; gap: 8px; margin-top: 6px; }

/* ── Badge ── */
.badge { display: inline-flex; align-items: center; gap: 3px; height: 18px; padding: 0 6px; font-size: 10px; font-weight: 500; border-radius: 3px; white-space: nowrap; }
.badge-active { background: var(--color-success-subtle); color: var(--color-success-fg); }

/* ── Right: Detail ── */
.detail-header { padding: 16px 20px; border-bottom: 0.5px solid var(--color-border-default); display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.detail-title { flex: 1; min-width: 0; }
.detail-name { font-size: 14px; font-weight: 500; width: 100%; }
.detail-actions { display: flex; gap: 6px; flex-shrink: 0; }

/* ── Section Title ── */
.section-title { font-size: 12px; font-weight: 500; color: var(--color-fg-default); margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; padding-top: 16px; }
.section-title .count { font-size: 11px; font-weight: 400; color: var(--color-fg-subtle); }

/* ── Toggle Row ── */
.toggle-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; }
.toggle-row + .toggle-row { border-top: 0.5px solid var(--color-border-default); }

.tl-info { flex: 1; }
.tl-title { font-size: 13px; font-weight: 500; }
.tl-desc { font-size: 11px; color: var(--color-fg-subtle); margin-top: 2px; }

/* ── Toggle Switch ── */
.toggle { position: relative; display: inline-block; width: 28px; height: 16px; cursor: pointer; flex-shrink: 0; }
.toggle input { opacity: 0; width: 0; height: 0; position: absolute; }
.toggle-slider { position: absolute; inset: 0; background: var(--color-border-default); border-radius: 999px; transition: 0.15s; }
.toggle-slider::before { content: ''; position: absolute; left: 2px; top: 2px; width: 12px; height: 12px; background: white; border-radius: 50%; transition: 0.15s; }
.toggle input:checked + .toggle-slider { background: var(--color-success-fg); }
.toggle input:checked + .toggle-slider::before { transform: translateX(12px); }

/* ── Rule Filter ── */
.rule-filter { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }

/* ── Select ── */
.select { height: 30px; padding: 0 28px 0 10px; font-size: 12px; color: var(--color-fg-default); background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default); border-radius: 6px; outline: none; cursor: pointer; appearance: none; background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23888' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 8px center; }

/* ── Search Bar ── */
.search-bar { display: flex; align-items: center; gap: 8px; height: 30px; padding: 0 10px; background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default); border-radius: 6px; transition: border-color 0.12s; }
.search-bar:focus-within { border-color: var(--color-accent-fg); }
.search-bar svg { width: 12px; height: 12px; color: var(--color-fg-light); flex-shrink: 0; }
.search-bar input { border: none; outline: none; flex: 1; font-size: 12px; background: transparent; color: var(--color-fg-default); }
.search-bar input::placeholder { color: var(--color-fg-light); }

/* ── Rule List ── */
.rule-list { margin-top: 4px; }
.rule-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 0.5px solid var(--color-border-default); border-radius: 6px; margin-bottom: 6px; transition: background 0.12s; }
.rule-item:hover { background: var(--color-canvas-subtle); }
.rule-item.checked { background: var(--color-success-subtle); border-color: #bbf7d0; }
.rule-icon { width: 24px; height: 24px; border-radius: 5px; background: var(--color-canvas-inset); display: flex; align-items: center; justify-content: center; flex-shrink: 0; color: var(--color-fg-muted); }
.rule-icon svg { width: 12px; height: 12px; }
.rule-text { flex: 1; min-width: 0; }
.rule-en { font-size: 12px; font-weight: 500; color: var(--color-fg-default); }
.rule-cn { font-size: 10px; color: var(--color-fg-subtle); }
.rule-tag { font-size: 10px; padding: 1px 6px; height: 16px; border-radius: 3px; background: var(--color-canvas-inset); color: var(--color-fg-subtle); white-space: nowrap; }

/* ── Severity Dots ── */
.sev-dots { display: inline-flex; gap: 2px; }
.sev-dot { width: 8px; height: 8px; border-radius: 50%; }
.sev-dot.critical { background: #dc2626; }
.sev-dot.high { background: #ef4444; }
.sev-dot.medium { background: var(--color-warning-fg); }
.sev-dot.low { background: var(--color-accent-fg); }
.sev-dot.info { background: var(--color-fg-light); }

/* ── Pagination ── */
.rule-page { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 14px; }
.pg-btn { height: 26px; padding: 0 10px; font-size: 11px; font-weight: 500; border: 0.5px solid var(--color-border-default); border-radius: 4px; background: var(--color-canvas-default); color: var(--color-fg-default); cursor: pointer; transition: 0.12s; }
.pg-btn:hover:not(:disabled) { background: var(--color-canvas-subtle); border-color: var(--color-fg-light); }
.pg-btn:disabled { opacity: 0.35; cursor: default; }
.pg-info { font-size: 11px; color: var(--color-fg-subtle); }

/* ── Empty ── */
.empty-hint { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 20px; color: var(--color-fg-light); }
.empty-hint svg { width: 32px; height: 32px; color: var(--color-fg-light); margin-bottom: 12px; opacity: 0.6; }
.empty-hint .title { font-size: 13px; font-weight: 500; color: var(--color-fg-subtle); }
.empty-hint .desc { font-size: 11px; margin-top: 4px; }

/* ── Info Tip ── */
.info-tip { font-size: 11px; color: #92400e; background: #fffbeb; border-left: 3px solid #f59e0b; padding: 10px 14px; border-radius: 0 6px 6px 0; line-height: 1.5; margin: 0 20px 20px; }

/* ── Modal ── */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.18); z-index: 2000; display: flex; align-items: center; justify-content: center; }
.modal { background: var(--color-canvas-default); border: 0.5px solid var(--color-border-default); border-radius: 12px; max-width: 480px; width: 90%; }
.modal-header { padding: 18px 22px 0; display: flex; align-items: center; justify-content: space-between; }
.modal-title { font-size: 14px; font-weight: 500; }
.modal-close { width: 22px; height: 22px; border: none; background: transparent; cursor: pointer; border-radius: 4px; color: var(--color-fg-light); display: flex; align-items: center; justify-content: center; }
.modal-close:hover { background: var(--color-canvas-inset); color: var(--color-fg-default); }
.modal-close svg { width: 14px; height: 14px; }
.modal-body { padding: 14px 22px 18px; }
.modal-footer { padding: 10px 22px; border-top: 0.5px solid var(--color-border-default); display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.fg { margin-bottom: 12px; }
.fl { display: block; font-size: 11px; font-weight: 500; color: var(--color-fg-default); margin-bottom: 5px; }
.fi { width: 100%; height: 30px; padding: 0 10px; border: 0.5px solid var(--color-border-default); border-radius: 6px; font-size: 12px; outline: none; background: var(--color-canvas-default); color: var(--color-fg-default); font-family: inherit; }
.fi:focus { border-color: var(--color-accent-fg); }
.fta { width: 100%; padding: 8px 10px; border: 0.5px solid var(--color-border-default); border-radius: 6px; font-size: 12px; outline: none; resize: vertical; font-family: var(--font-mono); line-height: 1.5; min-height: 60px; background: var(--color-canvas-default); color: var(--color-fg-default); }
.fta:focus { border-color: var(--color-accent-fg); }

/* ── Responsive ── */
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
</style>
