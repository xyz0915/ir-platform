<template>
  <div class="policy-page">
    <div class="policy-layout">
      <!-- ===== 左侧：策略列表 ===== -->
      <div class="policy-sidebar">
        <div class="sidebar-head">
          <span>📋 检测策略</span>
          <el-button size="small" type="primary" circle @click="showCreateDialog = true">+</el-button>
        </div>
        <div class="sidebar-list">
          <div
            v-for="p in policies" :key="p.id"
            :class="['policy-item', { active: selectedId === p.id }]"
            @click="selectPolicy(p.id)"
          >
            <span :class="['status-dot', p.is_active ? 'active' : '']" />
            <div class="pi-info">
              <div class="pi-name">{{ p.name }}</div>
              <div class="pi-meta">{{ p.rule_count || 0 }} 条 · RAG {{ p.enable_rag ? '开' : '关' }}</div>
            </div>
            <el-tag v-if="p.is_active" size="small" type="success" effect="dark">已激活</el-tag>
          </div>
        </div>
      </div>

      <!-- ===== 右侧：策略详情 ===== -->
      <div class="policy-main" v-if="detail">
        <!-- 基本信息 -->
        <div class="card">
          <div class="ph-top">
            <div class="ph-left">
              <el-input v-model="editName" placeholder="策略名称" size="large" style="font-size:18px;font-weight:600" />
              <el-input v-model="editDesc" :rows="2" type="textarea" placeholder="策略描述" style="margin-top:6px" />
            </div>
            <div class="ph-actions">
              <el-button v-if="!detail.is_active" type="success" @click="handleActivate">● 激活</el-button>
              <el-button v-else type="success" disabled>● 已激活</el-button>
              <el-button @click="handleDuplicate">📋 复制派生</el-button>
              <el-button type="danger" plain @click="handleDelete">🗑 删除</el-button>
            </div>
          </div>
          <div class="ph-save" v-if="dirty">
            <el-button type="primary" size="small" @click="handleSave">💾 保存修改</el-button>
            <el-button size="small" @click="cancelEdit">取消</el-button>
          </div>
        </div>

        <!-- 开关 -->
        <div class="card">
          <div class="toggle-row">
            <el-switch v-model="editRag" @change="markDirty" />
            <div class="tl-info">
              <div class="tl-title">🧠 RAG 语义分析</div>
              <div class="tl-desc">调用知识库进行语义匹配，增强检测深度 · 增加 30-60s 分析耗时</div>
            </div>
          </div>
          <div class="toggle-row">
            <el-switch v-model="editAttackChain" @change="markDirty" />
            <div class="tl-info">
              <div class="tl-title">🔗 攻击链检测</div>
              <div class="tl-desc">关联多个发现项，还原攻击者完整攻击链</div>
            </div>
          </div>
        </div>

        <!-- 规则选择 -->
        <div class="card">
          <div class="rule-head">
            <span style="font-weight:500;font-size:14px">规则选择</span>
            <span style="font-size:12px;color:#6b7280">已选 <strong style="color:#059669">{{ selectedRuleIds.length }}</strong> 条 / 策略含 <strong>{{ detail?.rule_count || 0 }}</strong> 条</span>
          </div>

          <div class="rule-filter">
            <el-select v-model="filterCategory" placeholder="全部分类" clearable size="small" style="width:110px" @change="fetchRules">
              <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
            </el-select>
            <el-select v-model="filterSeverity" placeholder="全部严重度" clearable size="small" style="width:100px" @change="fetchRules">
              <el-option label="严重" value="critical" />
              <el-option label="高危" value="high" />
              <el-option label="中危" value="medium" />
            </el-select>
            <el-input v-model="filterKeyword" placeholder="🔍 规则名/关键词" size="small" style="width:160px" clearable @keyup.enter="fetchRules" />
            <el-button size="small" type="primary" @click="fetchRules">筛选</el-button>
            <el-button size="small" @click="resetFilters">重置</el-button>
            <el-button size="small" type="success" @click="saveRules" :disabled="!dirtyRules">保存规则选择</el-button>
          </div>

          <el-table :data="rules" stripe border size="small" @selection-change="onRuleSelect" style="margin-top:8px" :row-class-name="rowClass">
            <el-table-column type="selection" width="40" :selectable="() => true" />
            <el-table-column label="是否检测" width="80" align="center">
              <template #default="{row}">
                <el-checkbox v-model="row._checked" @change="onRuleCheck(row, $event)" />
              </template>
            </el-table-column>
            <el-table-column label="规则名称" min-width="240">
              <template #default="{row}">
                <div style="font-weight:600;font-size:13px;color:#1f2937;line-height:1.5">{{ row.label || row.name }}</div>
                <div style="font-size:11px;color:#6b7280;line-height:1.4;margin-top:2px;font-family:monospace">{{ row.name }}</div>
              </template>
            </el-table-column>
            <el-table-column label="严重度" width="80" align="center">
              <template #default="{row}"><el-tag :type="sevType(row.severity)" size="small">{{ sevLabel(row.severity) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="分类" width="110" align="center">
              <template #default="{row}"><el-tag size="small" effect="plain" :type="catType(row.category)">{{ catLabel(row.category) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="类型" width="110" align="center">
              <template #default="{row}"><el-tag size="small" :type="typeType(row.rule_type)">{{ typeLabel(row.rule_type) }}</el-tag></template>
            </el-table-column>
          </el-table>
          <div class="rule-page">
            <el-pagination v-model:current-page="rulePage" :page-size="50" :total="ruleTotal" layout="prev,pager,next" small background @current-change="fetchRules" />
          </div>
        </div>

        <div class="info-tip">
          💡 <strong>策略激活提示</strong>：激活策略后分析引擎只执行该策略内的规则。切换策略时当前策略自动停用。无激活策略时降级为全量检测。
          <br>🔄 <strong>复制派生</strong>：点击"复制派生" → 生成包含完全相同配置和规则的新策略 → 可单独修改规则后独立保存。
        </div>
      </div>

      <!-- 无选中时 -->
      <div class="policy-main empty" v-else>
        <div class="empty-hint">⬅ 在左侧选择或创建策略</div>
      </div>
    </div>

    <!-- 新建策略对话框 -->
    <el-dialog v-model="showCreateDialog" title="新建策略" width="400px">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="输入策略名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
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
.policy-layout { display: flex; height: 100%; gap: 16px; }

/* 左侧 */
.policy-sidebar { width: 260px; min-width: 260px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; display: flex; flex-direction: column; }
.sidebar-head { display: flex; justify-content: space-between; align-items: center; padding: 14px 14px 8px; font-size: 14px; font-weight: 600; }
.sidebar-list { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
.policy-item { display: flex; align-items: center; gap: 8px; padding: 10px; border-radius: 6px; cursor: pointer; transition: .15s; }
.policy-item:hover { background: #f9fafb; }
.policy-item.active { background: #ecfdf5; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: #d1d5db; }
.status-dot.active { background: #059669; box-shadow: 0 0 6px rgba(5,150,105,.4); }
.pi-info { flex: 1; min-width: 0; }
.pi-name { font-size: 13px; font-weight: 600; color: #1f2937; }
.pi-meta { font-size: 11px; color: #6b7280; }

/* 右侧 */
.policy-main { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
.policy-main.empty { justify-content: center; align-items: center; }
.empty-hint { font-size: 15px; color: #9ca3af; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }
.ph-top { display: flex; justify-content: space-between; gap: 16px; }
.ph-left { flex: 1; }
.ph-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.ph-save { margin-top: 10px; padding-top: 10px; border-top: 1px solid #f3f4f6; display: flex; gap: 8px; }

.toggle-row { display: flex; align-items: center; gap: 12px; }
.toggle-row + .toggle-row { margin-top: 14px; padding-top: 14px; border-top: 1px solid #f3f4f6; }
.tl-info { flex: 1; }
.tl-title { font-size: 13px; font-weight: 500; }
.tl-desc { font-size: 11px; color: #6b7280; margin-top: 2px; }

.rule-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.rule-filter { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.rule-page { display: flex; justify-content: center; margin-top: 10px; }

.info-tip { font-size: 11px; color: #92400e; background: #fffbeb; border-left: 3px solid #f59e0b; padding: 10px 14px; border-radius: 0 6px 6px 0; line-height: 1.5; }

/* 规则表样式优化 */
:deep(.el-table) { font-size: 12px; }
:deep(.el-table .el-table__cell) { padding: 8px 0; }
:deep(.rule-row-checked) { background: #ecfdf5 !important; }
:deep(.rule-row-checked:hover > td) { background: #d1fae5 !important; }
:deep(.el-table .el-table__row:hover > td) { background: #f9fafb !important; }
</style>
