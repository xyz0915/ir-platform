<template>
  <div class="page-container">
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">规则管理</h2>
        <div>
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
          <el-button type="primary" @click="showCreateDialog">
            <el-icon><Plus /></el-icon> 新增规则
          </el-button>
        </div>
      </div>
      <el-table :data="rules" border stripe v-loading="loading">
        <el-table-column prop="name" label="规则名称" min-width="180" />
        <el-table-column prop="category" label="类别" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rule_type" label="类型" width="100" />
        <el-table-column prop="severity" label="严重程度" width="100">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" size="small">{{ row.severity }}</el-tag>
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
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              @change="(val) => handleToggle(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="showDetail(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 规则详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="规则详情" width="640px">
      <el-descriptions :column="1" border v-if="currentRule">
        <el-descriptions-item label="名称">{{ currentRule.name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ currentRule.description }}</el-descriptions-item>
        <el-descriptions-item label="类别">{{ currentRule.category }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ currentRule.rule_type }}</el-descriptions-item>
        <el-descriptions-item label="严重程度">{{ currentRule.severity }}</el-descriptions-item>
        <el-descriptions-item v-if="getMitreAttack(currentRule)" label="MITRE ATT&amp;CK">
          {{ getMitreAttack(currentRule) }}
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
          <el-input v-model="createForm.name" />
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
import request from '@/api/index'

const rules = ref([])
const loading = ref(false)
const filterCategory = ref('')

const detailDialogVisible = ref(false)
const currentRule = ref(null)

const createDialogVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  name: '',
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
    const res = await request.get('/rules', { params })
    rules.value = res.data
  } catch (error) {
    // handled
  } finally {
    loading.value = false
  }
}

function showDetail(rule) {
  currentRule.value = rule
  detailDialogVisible.value = true
}

function showCreateDialog() {
  createForm.name = ''
  createForm.category = 'process'
  createForm.rule_type = 'regex'
  createForm.severity = 'medium'
  createForm.description = ''
  createForm.conditionStr = '{}'
  createDialogVisible.value = true
}

/**
 * 从规则的 condition._meta.mitre_attack 中提取 MITRE ATT&CK 编号.
 * 支持两种存储位置：
 * 1. condition._meta.mitre_attack（新增规则）
 * 2. 直接存储在 condition.mitre_attack（兼容旧格式）
 */
function getMitreAttack(rule) {
  if (!rule || !rule.condition) return null
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
    // handled
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

function severityType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary'
  }
  return map[severity] || 'info'
}
</script>

<style scoped>
.condition-json {
  background: #f5f7fa;
  padding: 10px;
  border-radius: 4px;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
