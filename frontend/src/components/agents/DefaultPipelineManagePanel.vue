<template>
  <div class="default-pipeline-manage">
    <el-card class="manage-card" shadow="never">
      <template #header>
        <div class="manage-header">
          <div class="manage-title">
            <el-icon><Connection /></el-icon>
            <span>默认闭环流程规则</span>
          </div>
          <div class="manage-actions">
            <el-button type="primary" :loading="store.loading" @click="onCreate">
              <el-icon><Plus /></el-icon> 新建规则
            </el-button>
            <el-button :loading="store.loading" @click="store.fetchRules()">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="!store.hasGlobalDefault"
        class="manage-alert"
        type="warning"
        :closable="false"
        show-icon
        title="尚未配置全局默认规则"
        description="未命中任何场景规则时，将回退到内置默认流程（分诊→调查→处置→报告）。建议至少配置一条全局默认规则。"
      />

      <el-table
        :data="store.rules"
        v-loading="store.loading"
        empty-text="暂无规则"
        class="rule-table"
      >
        <el-table-column label="名称" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="rule-name">{{ row.name || '（未命名）' }}</span>
            <el-tag v-if="row.is_global" size="small" type="warning" effect="dark" class="rule-global-tag">
              全局
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="preset_name" label="关联 Pipeline" min-width="160" show-overflow-tooltip />
        <el-table-column label="场景条件" min-width="210">
          <template #default="{ row }">
            <span v-if="row.is_global" class="cond-muted">全部场景（全局）</span>
            <span v-else>
              <el-tag v-if="row.scene_condition?.category" size="small" effect="plain">
                {{ row.scene_condition.category }}
              </el-tag>
              <el-tag
                v-if="row.scene_condition?.priority"
                size="small"
                type="danger"
                effect="plain"
                class="cond-priority"
              >
                {{ row.scene_condition.priority }}
              </el-tag>
              <span
                v-if="!row.scene_condition?.category && !row.scene_condition?.priority"
                class="cond-muted"
              >
                任意
              </span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="agent_count" label="智能体数" width="90" align="center" />
        <el-table-column prop="priority_order" label="优先级" width="90" align="center" />
        <el-table-column prop="created_at" label="创建时间" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建 / 编辑 弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑默认规则' : '新建默认规则'"
      width="540px"
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="关联 Pipeline" prop="preset_id">
          <el-select
            v-model="form.preset_id"
            placeholder="选择已保存的 pipeline 预设"
            filterable
            style="width: 100%"
          >
            <el-option v-for="p in presets" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="form-hint">
            若列表为空，请先在「智能体编排管理 → 设为默认」中保存 pipeline 预设。
          </div>
        </el-form-item>
        <el-form-item label="规则名称">
          <el-input v-model="form.name" placeholder="可选，便于辨识" />
        </el-form-item>
        <el-form-item label="事件分类">
          <el-select
            v-model="form.category"
            placeholder="任意分类（不限定）"
            clearable
            style="width: 100%"
          >
            <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="事件优先级">
          <el-select
            v-model="form.priority"
            placeholder="任意优先级（不限定）"
            clearable
            style="width: 100%"
          >
            <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="全局默认">
          <el-switch v-model="form.is_global" />
          <span class="form-hint inline">开启后对所有未命中场景规则的事件生效（全局唯一）。</span>
        </el-form-item>
        <el-form-item label="优先级排序">
          <el-input-number v-model="form.priority_order" :min="0" :max="999" />
          <span class="form-hint inline">数值越小越优先（同层场景规则之间排序）。</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">
          {{ isEdit ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Plus, Refresh } from '@element-plus/icons-vue'
import { useDefaultPipelineStore } from '@/stores/defaultPipeline'
import agentApi from '@/api/agent'

const store = useDefaultPipelineStore()
const presets = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const editingId = ref(null)
const formRef = ref(null)

// 场景条件可选项（P2 仅支持 category/priority 维度，预留其它字段扩展槽）
const categoryOptions = [
  '网络攻击',
  '恶意软件',
  '数据泄露',
  '内部威胁',
  '钓鱼',
  '勒索软件',
  '账号异常',
  '其他',
]
const priorityOptions = ['P0', 'P1', 'P2', 'P3']

const rules = {
  preset_id: [{ required: true, message: '请选择关联 Pipeline 预设', trigger: 'change' }],
}

function emptyForm() {
  return {
    preset_id: null,
    name: '',
    category: '',
    priority: '',
    is_global: false,
    priority_order: 0,
  }
}
const form = ref(emptyForm())

/** 拉取 pipeline 预设列表，供规则关联选择。 */
async function loadPresets() {
  try {
    const res = await agentApi.pipeline.getPresets()
    const data = res?.data ?? res
    presets.value = Array.isArray(data) ? data : data?.presets ?? []
  } catch (e) {
    presets.value = []
  }
}

onMounted(async () => {
  await Promise.all([store.fetchRules(), loadPresets()])
})

/** 由表单字段拼装 scene_condition（仅保留有值的维度）。 */
function buildSceneCondition() {
  const cond = {}
  if (form.value.category) cond.category = form.value.category
  if (form.value.priority) cond.priority = form.value.priority
  return cond
}

function onCreate() {
  isEdit.value = false
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function onEdit(row) {
  isEdit.value = true
  editingId.value = row.id
  form.value = {
    preset_id: row.preset_id ?? null,
    name: row.name || '',
    category: row.scene_condition?.category || '',
    priority: row.scene_condition?.priority || '',
    is_global: !!row.is_global,
    priority_order: row.priority_order ?? 0,
  }
  dialogVisible.value = true
}

function resetForm() {
  form.value = emptyForm()
  formRef.value?.clearValidate?.()
}

async function onSubmit() {
  try {
    await formRef.value?.validate?.()
  } catch (e) {
    return
  }
  submitting.value = true
  try {
    const payload = {
      preset_id: form.value.preset_id,
      name: form.value.name || undefined,
      scene_condition: buildSceneCondition(),
      is_global: form.value.is_global,
      priority_order: form.value.priority_order,
    }
    if (isEdit.value) {
      await store.updateRule(editingId.value, payload)
      ElMessage.success('规则已保存')
    } else {
      await store.createRule(payload)
      ElMessage.success('规则已创建')
    }
    dialogVisible.value = false
  } catch (e) {
    // 409 全局默认冲突等已由 axios 拦截器提示，这里做兜底文案
    const status = e?.response?.status
    if (status === 409) {
      ElMessage.error('已存在全局默认规则，请勿重复创建（编辑现有全局规则即可）')
    }
  } finally {
    submitting.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除规则「${row.name || '未命名'}」？` +
        (row.is_global ? '该规则为全局默认，删除后将回退到内置默认流程。' : ''),
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch (e) {
    return
  }
  try {
    const res = await store.deleteRule(row.id)
    ElMessage.success('规则已删除')
    if (res?.fell_back_to_hardcoded) {
      ElMessage.warning('已删除全局默认规则，未命中场景规则时将回退到内置默认流程')
    }
  } catch (e) {
    // 拦截器已提示
  }
}
</script>

<style scoped>
.manage-card {
  border-radius: 12px;
  border: 1px solid var(--color-border-default);
}

.manage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.manage-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.manage-actions {
  display: flex;
  gap: 8px;
}

.manage-alert {
  margin-bottom: 12px;
}

.rule-name {
  font-weight: 500;
  color: var(--color-fg-default);
}

.rule-global-tag {
  margin-left: 6px;
}

.cond-muted {
  color: var(--color-fg-muted);
  font-size: 13px;
}

.cond-priority {
  margin-left: 4px;
}

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-fg-muted);
  line-height: 1.5;
}

.form-hint.inline {
  margin-left: 8px;
  margin-top: 0;
}
</style>
