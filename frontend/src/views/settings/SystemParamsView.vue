<template>
  <div class="system-params-view">
    <div class="page-header">
      <h2>系统参数</h2>
    </div>

    <el-table :data="paramList" border stripe style="width: 100%" v-loading="loading">
      <el-table-column label="参数名" width="280">
        <template #default="{ row }">
          <code class="param-key">{{ row.key }}</code>
        </template>
      </el-table-column>
      <el-table-column label="当前值" width="200">
        <template #default="{ row }">
          <!-- bool 类型用 Switch -->
          <el-switch
            v-if="row.value_type === 'bool'"
            :model-value="row.value === 'true'"
            @change="(val) => handleChange(row, val ? 'true' : 'false')"
          />
          <!-- int 类型用 InputNumber -->
          <el-input-number
            v-else-if="row.value_type === 'int'"
            :model-value="Number(row.value)"
            :min="1"
            controls-position="right"
            style="width: 160px"
            @change="(val) => handleChange(row, String(val))"
          />
          <!-- string 类型用 Input -->
          <el-input
            v-else
            :model-value="row.value"
            style="width: 240px"
            @blur="(e) => handleChange(row, e.target.value)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="200" />
    </el-table>

    <!-- 数据遗忘操作：清空案件 -->
    <el-card class="purge-card" shadow="never" style="margin-top: 24px">
      <template #header>
        <div class="purge-card-header">
          <span class="purge-title">数据遗忘操作 · 清空案件</span>
          <el-tag type="danger" size="small" effect="plain">不可恢复</el-tag>
        </div>
      </template>

      <el-alert type="warning" :closable="false" show-icon
        title="被遗忘权 / 隐私合规"
        description="此操作将永久删除所选案件及其全部主机、日志、告警、安全事件、AI 分析、报告等约 30 张表的数据，仅保留清案审计留痕，不可恢复。" />

      <div class="purge-row">
        <el-select
          v-model="selectedCaseId"
          placeholder="选择要清空的案件"
          filterable
          clearable
          style="width: 340px"
          :loading="caseLoading"
        >
          <el-option
            v-for="c in caseOptions"
            :key="c.value"
            :label="`${c.value} - ${c.name}`"
            :value="c.value"
          >
            <span>{{ c.value }} - {{ c.name }}</span>
            <span class="purge-option-sub">
              日志 {{ c.log_count }} · 事件 {{ c.event_count }}
            </span>
          </el-option>
        </el-select>
        <el-button
          v-if="isAdmin"
          type="danger"
          :disabled="!selectedCaseId"
          @click="openPurgeDialog"
        >
          清空此案件（不可撤销）
        </el-button>
        <el-tag v-else type="info">仅管理员可执行</el-tag>
      </div>
    </el-card>

    <!-- 二次确认弹窗 -->
    <el-dialog
      v-model="purgeDialogVisible"
      title="确认清空案件"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-alert type="error" :closable="false" show-icon style="margin-bottom: 12px">
        <template #title>此操作不可撤销</template>
        将<strong>永久删除</strong>该案件及其全部主机、日志、告警、安全事件、AI 分析、报告与审计痕迹（清案审计除外），<strong>不可恢复</strong>。请确认已获得合规授权。
      </el-alert>

      <div v-if="previewData" class="purge-preview">
        <div class="purge-preview-head">
          预估删除行数（案件 #{{ previewData.case_id }} · {{ previewData.case_name }}）
        </div>
        <el-table :data="previewTableData" size="small" max-height="240" border>
          <el-table-column prop="table" label="数据表" min-width="220" />
          <el-table-column prop="rows" label="行数" width="100" align="right" />
        </el-table>
        <div class="purge-preview-total">合计约 {{ previewData.total_rows }} 行</div>
      </div>

      <el-form label-width="120px" style="margin-top: 12px">
        <el-form-item label="请输入案件 ID">
          <el-input
            v-model="confirmText"
            placeholder="请输入上方案件的数字 ID 以确认"
          />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="exportSnapshot">删除前导出 JSON 快照（合规留底）</el-checkbox>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="purgeDialogVisible = false">取消</el-button>
        <el-button
          type="danger"
          :loading="purging"
          :disabled="confirmText !== String(selectedCaseId)"
          @click="confirmPurge"
        >
          确认永久删除
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemSettings, updateSystemSetting } from '@/api/settings'
import casesApi from '@/api/cases'
import { useAuthStore } from '@/stores/auth'

const loading = ref(false)
const paramList = ref([])

async function fetchParams() {
  loading.value = true
  try {
    const res = await getSystemSettings()
    paramList.value = res.data || []
  } catch (e) {
    console.error('获取系统参数失败', e)
  } finally {
    loading.value = false
  }
}

async function handleChange(row, newValue) {
  const oldValue = row.value
  if (String(newValue) === String(oldValue)) return

  row.value = String(newValue)
  try {
    await updateSystemSetting(row.key, { value: String(newValue) })
    ElMessage.success(`${row.key} 已更新`)
  } catch (e) {
    row.value = oldValue
    console.error('更新参数失败', e)
  }
}

onMounted(() => {
  fetchParams()
  loadCases()
})

// ── 数据遗忘操作：清空案件 ──────────────────────────────
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const caseLoading = ref(false)
const caseOptions = ref([])
const selectedCaseId = ref(null)
const purgeDialogVisible = ref(false)
const purging = ref(false)
const confirmText = ref('')
const exportSnapshot = ref(true)
const previewData = ref(null)

const TABLE_LABELS = {
  rules_reset: '规则命中归零',
}

const previewTableData = computed(() => {
  if (!previewData.value) return []
  return Object.entries(previewData.value.table_counts || {}).map(
    ([table, rows]) => ({ table: TABLE_LABELS[table] || table, rows })
  )
})

async function loadCases() {
  caseLoading.value = true
  try {
    const res = await casesApi.getCasesWithHosts()
    caseOptions.value = (res.data || []).map((c) => ({
      value: c.value,
      name: c.name,
      log_count: c.log_count || 0,
      event_count: c.event_count || 0,
    }))
  } catch (e) {
    console.error('获取案件列表失败', e)
  } finally {
    caseLoading.value = false
  }
}

async function openPurgeDialog() {
  if (!selectedCaseId.value) return
  confirmText.value = ''
  previewData.value = null
  purgeDialogVisible.value = true
  try {
    const res = await casesApi.purgePreview(selectedCaseId.value)
    previewData.value = res.data
  } catch (e) {
    console.error('获取清案预览失败', e)
  }
}

async function confirmPurge() {
  if (confirmText.value !== String(selectedCaseId.value)) {
    ElMessage.error('输入的案件 ID 与所选案件不一致')
    return
  }
  purging.value = true
  try {
    await casesApi.purge({
      case_id: selectedCaseId.value,
      confirm_text: confirmText.value,
      export_snapshot: exportSnapshot.value,
    })
    ElMessage.success('案件已清空（不可恢复）')
    purgeDialogVisible.value = false
    selectedCaseId.value = null
    await loadCases()
  } catch (e) {
    console.error('清空案件失败', e)
  } finally {
    purging.value = false
  }
}
</script>

<style scoped>
.system-params-view {
  max-width: 900px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}

.param-key {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  background: var(--color-canvas-subtle, #f3f4f6);
  padding: 2px 6px;
  border-radius: 4px;
}

.purge-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.purge-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
}

.purge-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.purge-option-sub {
  float: right;
  color: var(--color-fg-subtle, #888888);
  font-size: 12px;
  font-weight: 400;
}

.purge-preview {
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  /* 6px 圆角档位复用已定义的 --r-btn（theme.css 仅定义 6/10/12 三档） */
  border-radius: var(--r-btn, 6px);
  padding: 8px 12px;
  margin-bottom: 4px;
}

.purge-preview-head {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-fg-default, #111111);
  margin-bottom: 8px;
}

.purge-preview-total {
  text-align: right;
  font-size: 12px;
  color: var(--color-fg-subtle, #888888);
  margin-top: 6px;
}
</style>
