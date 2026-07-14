<template>
  <div class="page-container">
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">
          <span class="title-emoji">📏</span>
          <span>规则管理</span>
          <el-tag class="title-tag" type="primary" effect="plain" size="small">核心引擎</el-tag>
        </h2>
        <div class="toolbar">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索规则名称 / 中文名 / 描述"
            clearable
            style="width: 240px"
            @keyup.enter="loadRules"
            @clear="loadRules"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-button @click="loadRules">
            <el-icon><Search /></el-icon> 搜索
          </el-button>
          <el-select v-model="filterCategory" placeholder="按类别筛选" clearable style="width: 180px" @change="loadRules">
            <el-option label="进程" value="process" />
            <el-option label="执行" value="execution" />
            <el-option label="网络" value="network" />
            <el-option label="启动项" value="startup" />
            <el-option label="持久化" value="persistence" />
            <el-option label="IOC" value="ioc" />
            <el-option label="行为" value="behavior" />
            <el-option label="凭据" value="credential" />
            <el-option label="横向移动" value="lateral" />
            <el-option label="数据窃取" value="exfiltration" />
            <el-option label="发现" value="discovery" />
            <el-option label="防御规避" value="defense_evasion" />
            <el-option label="权限提升" value="privilege_escalation" />
            <el-option label="影响" value="impact" />
          </el-select>
          <el-button v-if="isAdmin" type="warning" @click="handleReset">
            <el-icon><RefreshLeft /></el-icon> 重置为默认
          </el-button>
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon> 新增规则
          </el-button>
        </div>
      </div>

      <!-- 批量操作条 -->
      <div v-if="selectedRows.length" class="bulk-bar">
        <span>已选 {{ selectedRows.length }} 条</span>
        <el-button size="small" type="success" @click="handleBulkEnable(true)">批量启用</el-button>
        <el-button size="small" type="warning" @click="handleBulkEnable(false)">批量禁用</el-button>
        <el-button size="small" @click="clearSelection">取消选择</el-button>
      </div>

      <el-table
        :data="rules"
        border
        stripe
        v-loading="loading"
        @selection-change="handleSelectionChange"
        ref="tableRef"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column label="规则名称" min-width="200">
          <template #default="{ row }">
            <div class="rule-name">
              <span class="rule-label">{{ row.label || row.name }}</span>
              <span v-if="row.label && row.label !== row.name" class="rule-key">{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="类别" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rule_type" label="类型" width="100" />
        <el-table-column prop="severity" label="严重程度" width="100">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" size="small">{{ severityLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="MITRE ATT&amp;CK" width="130">
          <template #default="{ row }">
            <el-tag
              v-if="getMitreAttack(row)"
              type="info"
              size="small"
              effect="plain"
            >
              {{ getMitreAttack(row) }}
            </el-tag>
            <span v-else style="color: #c0c4cc">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.source === 'default'" type="info" size="small">内置默认</el-tag>
            <el-tag v-else type="success" size="small">用户规则</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              @change="(val) => handleToggle(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="showDetail(row)">查看</el-button>
            <el-popconfirm
              title="仅用户规则可删除，确认删除？"
              @confirm="handleDelete(row)"
            >
              <template #reference>
                <el-button size="small" type="danger" link :disabled="row.source === 'default'">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 规则详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="规则详情" width="640px">
      <el-descriptions :column="1" border v-if="currentRule">
        <el-descriptions-item label="名称（英文键）">{{ currentRule.name }}</el-descriptions-item>
        <el-descriptions-item v-if="currentRule.label" label="中文名称">{{ currentRule.label }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ currentRule.description }}</el-descriptions-item>
        <el-descriptions-item label="类别">{{ currentRule.category }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ currentRule.rule_type }}</el-descriptions-item>
        <el-descriptions-item label="严重程度">{{ severityLabel(currentRule.severity) }}</el-descriptions-item>
        <el-descriptions-item v-if="getMitreAttack(currentRule)" label="MITRE ATT&amp;CK">
          {{ getMitreAttack(currentRule) }}
        </el-descriptions-item>
        <el-descriptions-item label="来源">
          <el-tag v-if="currentRule.source === 'default'" type="info" size="small">内置默认</el-tag>
          <el-tag v-else type="success" size="small">用户规则</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="条件">
          <pre class="condition-json">{{ JSON.stringify(currentRule.condition, null, 2) }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- 新增规则对话框 -->
    <el-dialog v-model="createDialogVisible" title="新增规则" width="640px">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="规则名称" required>
          <el-input v-model="createForm.name" placeholder="英文技术键，唯一（如 suspicious_powershell）" />
        </el-form-item>
        <el-form-item label="中文名称">
          <el-input v-model="createForm.label" placeholder="中文展示名（可选）" />
        </el-form-item>
        <el-form-item label="类别" required>
          <el-select v-model="createForm.category">
            <el-option label="进程" value="process" />
            <el-option label="执行" value="execution" />
            <el-option label="网络" value="network" />
            <el-option label="启动项" value="startup" />
            <el-option label="持久化" value="persistence" />
            <el-option label="IOC" value="ioc" />
            <el-option label="行为" value="behavior" />
            <el-option label="凭据" value="credential" />
            <el-option label="横向移动" value="lateral" />
            <el-option label="数据窃取" value="exfiltration" />
            <el-option label="发现" value="discovery" />
            <el-option label="防御规避" value="defense_evasion" />
            <el-option label="权限提升" value="privilege_escalation" />
            <el-option label="影响" value="impact" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则类型" required>
          <el-select v-model="createForm.rule_type">
            <el-option label="正则匹配" value="regex" />
            <el-option label="列表匹配" value="list" />
            <el-option label="阈值检测" value="threshold" />
            <el-option label="行为检测" value="behavior" />
            <el-option label="组合条件" value="composite" />
            <el-option label="存在性检查" value="exists" />
          </el-select>
        </el-form-item>
        <el-form-item label="严重程度">
          <el-select v-model="createForm.severity">
            <el-option label="严重" value="critical" />
            <el-option label="高危" value="high" />
            <el-option label="中危" value="medium" />
            <el-option label="低危" value="low" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="条件 JSON">
          <el-input
            v-model="createForm.conditionStr"
            type="textarea"
            :rows="8"
            :placeholder="conditionPlaceholder"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, RefreshLeft } from '@element-plus/icons-vue'
import request from '@/api/index'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const rules = ref([])
const loading = ref(false)
const filterCategory = ref('')
const searchKeyword = ref('')
const selectedRows = ref([])
const tableRef = ref(null)

const detailDialogVisible = ref(false)
const currentRule = ref(null)

const createDialogVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  name: '',
  label: '',
  category: 'process',
  rule_type: 'regex',
  severity: 'medium',
  description: '',
  conditionStr: '{}'
})

/** 根据选中的 rule_type 动态切换 placeholder */
const conditionPlaceholder = computed(() => {
  const placeholders = {
    regex: '{"field": "command_line", "pattern": "powershell.*-enc", "flags": "ignorecase"}',
    list: '{"field": "remote_port", "values": [4444, 1337], "match_mode": "exact"}',
    threshold: '{"field": "connection_count", "operator": ">", "value": 50}',
    behavior: '{"pattern": "orphan_process", "description": "孤立进程检测"}',
    composite: '{"logic": "AND", "sub_rules": [{"type": "regex", "field": "command_line", "pattern": "mimikatz"}, {"type": "exists", "field": "remote_address"}]}',
    exists: '{"field": "remote_address"}'
  }
  return placeholders[createForm.rule_type] || '{}'
})

onMounted(() => {
  loadRules()
})

async function loadRules() {
  loading.value = true
  try {
    const params = {}
    if (filterCategory.value) params.category = filterCategory.value
    if (searchKeyword.value.trim()) params.q = searchKeyword.value.trim()
    const res = await request.get('/rules', { params })
    rules.value = res.data
  } catch (error) {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selectedRows.value = []
}

async function handleBulkEnable(enabled) {
  const ids = selectedRows.value.map((r) => r.id)
  if (!ids.length) return
  try {
    await request.put('/rules/bulk-enable', { ids, enabled })
    ElMessage.success(`已${enabled ? '启用' : '禁用'} ${ids.length} 条规则`)
    loadRules()
  } catch (error) {
    // handled by interceptor
  }
}

async function handleReset() {
  try {
    await request.post('/rules/reset')
    ElMessage.success('已重置为默认规则（用户规则保留）')
    loadRules()
  } catch (error) {
    // handled by interceptor (403 非管理员等)
  }
}

function showDetail(rule) {
  currentRule.value = rule
  detailDialogVisible.value = true
}

function showCreateDialog() {
  createForm.name = ''
  createForm.label = ''
  createForm.category = 'process'
  createForm.rule_type = 'regex'
  createForm.severity = 'medium'
  createForm.description = ''
  createForm.conditionStr = '{}'
  createDialogVisible.value = true
}

/**
 * 从规则中提取 MITRE ATT&CK 编号（T-P2-3 顶层字段优先，兼容 condition 内嵌）.
 * 读取优先级：顶层 mitre_attack → condition._meta.mitre_attack → condition.mitre_attack
 */
function getMitreAttack(rule) {
  if (!rule) return null
  if (rule.mitre_attack) return rule.mitre_attack
  if (!rule.condition) return null
  const cond = typeof rule.condition === 'string'
    ? (() => { try { return JSON.parse(rule.condition) } catch { return {} } })()
    : rule.condition
  if (cond._meta && cond._meta.mitre_attack) {
    return cond._meta.mitre_attack
  }
  if (cond.mitre_attack) {
    return cond.mitre_attack
  }
  return null
}

async function handleCreate() {
  if (!createForm.name) {
    ElMessage.warning('请输入规则名称')
    return
  }
  let condition
  try {
    condition = JSON.parse(createForm.conditionStr)
  } catch (error) {
    ElMessage.error('条件 JSON 格式错误')
    return
  }
  creating.value = true
  try {
    await request.post('/rules', {
      name: createForm.name,
      label: createForm.label || undefined,
      category: createForm.category,
      rule_type: createForm.rule_type,
      condition,
      severity: createForm.severity,
      description: createForm.description
    })
    ElMessage.success('规则创建成功')
    createDialogVisible.value = false
    loadRules()
  } catch (error) {
    // handled by interceptor
  } finally {
    creating.value = false
  }
}

async function handleToggle(rule, enabled) {
  try {
    await request.put(`/rules/${rule.id}`, { enabled })
    ElMessage.success(`规则已${enabled ? '启用' : '禁用'}`)
  } catch (error) {
    rule.enabled = !enabled
  }
}

async function handleDelete(rule) {
  if (rule.source === 'default') {
    ElMessage.warning('默认规则不可删除，请使用「重置为默认」')
    return
  }
  try {
    await request.delete(`/rules/${rule.id}`)
    ElMessage.success('规则已删除')
    loadRules()
  } catch (error) {
    // handled by interceptor
  }
}

function severityType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary'
  }
  return map[severity] || 'info'
}

function severityLabel(severity) {
  const map = {
    critical: '严重',
    high: '高危',
    medium: '中危',
    low: '低危'
  }
  return map[severity] || severity
}
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.bulk-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #ecf5ff;
  border-radius: 4px;
  font-size: 13px;
  color: #409eff;
}
.rule-name {
  display: flex;
  flex-direction: column;
}
.rule-label {
  font-weight: 600;
}
.rule-key {
  font-size: 12px;
  color: #909399;
}
.condition-json {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
