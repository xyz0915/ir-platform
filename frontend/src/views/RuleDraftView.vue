<template>
  <div class="rule-draft-view">
    <!-- 工具栏 -->
    <el-card shadow="never" class="toolbar">
      <div class="toolbar-row">
        <el-input
          v-model="category"
          placeholder="类别（可选，如 process / network）"
          clearable
          class="cat-input"
        />
        <el-select v-model="statusFilter" placeholder="状态筛选" clearable class="status-select">
          <el-option label="全部" value="" />
          <el-option label="草稿" value="draft" />
          <el-option label="影子运行" value="shadow" />
          <el-option label="待复审" value="pending_review" />
          <el-option label="已启用" value="enabled" />
          <el-option label="已驳回" value="rejected" />
        </el-select>
        <el-button type="primary" :loading="generating" @click="onGenerate">
          <el-icon><MagicStick /></el-icon>
          <span>AI 生成规则草稿</span>
        </el-button>
        <el-button :loading="loading" @click="fetchDrafts">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </div>
    </el-card>

    <!-- 草稿列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="drafts" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="规则名" min-width="180" />
        <el-table-column prop="label" label="中文名" min-width="160" show-overflow-tooltip />
        <el-table-column prop="rule_type" label="类型" width="110" />
        <el-table-column label="严重度" width="100">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="shadow_hit_count" label="影子命中" width="100" align="center" />
        <el-table-column prop="tuned_version" label="调优版本" width="100" align="center" />
        <el-table-column label="操作" min-width="320" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="onView(row)">查看 DSL</el-button>
            <el-button link type="primary" @click="onRunShadow(row)" :disabled="row.status === 'enabled' || row.status === 'rejected'">影子运行</el-button>
            <el-button link type="warning" @click="onTune(row)" :disabled="row.status === 'enabled' || row.status === 'rejected'">自动调优</el-button>
            <el-button
              v-if="isAdmin"
              link type="success"
              @click="onEnable(row)"
              :disabled="row.status === 'enabled' || row.status === 'rejected'"
            >启用</el-button>
            <el-button
              v-if="isAdmin"
              link type="danger"
              @click="onReject(row)"
              :disabled="row.status === 'enabled' || row.status === 'rejected'"
            >驳回</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager" v-if="total > pageSize">
        <el-pagination
          background
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </el-card>

    <!-- DSL 详情对话框 -->
    <el-dialog v-model="detailVisible" title="规则草稿详情" width="640px">
      <template v-if="current">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="规则名">{{ current.name }}</el-descriptions-item>
          <el-descriptions-item label="中文名">{{ current.label || '-' }}</el-descriptions-item>
          <el-descriptions-item label="类型 / 严重度">{{ current.rule_type }} / {{ current.severity }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusLabel(current.status) }}</el-descriptions-item>
          <el-descriptions-item label="影子命中数">{{ current.shadow_hit_count }}</el-descriptions-item>
          <el-descriptions-item label="说明">{{ current.rationale || '-' }}</el-descriptions-item>
          <el-descriptions-item label="DSL 校验" v-if="current.dsl">
            <span class="dsl-error">{{ current.dsl }}</span>
          </el-descriptions-item>
        </el-descriptions>
        <div class="dsl-block">
          <div class="dsl-title">condition（DSL）</div>
          <pre class="dsl-pre">{{ prettyCondition(current.condition) }}</pre>
        </div>
        <div class="dsl-block" v-if="current.sample_hits && current.sample_hits.length">
          <div class="dsl-title">影子运行样本命中</div>
          <pre class="dsl-pre">{{ JSON.stringify(current.sample_hits, null, 2) }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  generateRuleDraft,
  listRuleDrafts,
  runShadow,
  getShadowStats,
  tuneDraft,
  enableDraft,
  rejectDraft,
} from '@/api/ruleDrafts'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const drafts = ref([])
const loading = ref(false)
const generating = ref(false)
const category = ref('')
const statusFilter = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)

const detailVisible = ref(false)
const current = ref(null)

const SEVERITY_TAG = { critical: 'danger', high: 'warning', medium: 'info', low: '' }
const STATUS_TAG = {
  draft: 'info',
  shadow: 'primary',
  pending_review: 'warning',
  enabled: 'success',
  rejected: 'danger',
}
const STATUS_LABEL = {
  draft: '草稿',
  shadow: '影子运行',
  pending_review: '待复审',
  enabled: '已启用',
  rejected: '已驳回',
}

function severityType(s) { return SEVERITY_TAG[s] || 'info' }
function statusType(s) { return STATUS_TAG[s] || 'info' }
function statusLabel(s) { return STATUS_LABEL[s] || s }
function prettyCondition(c) {
  try { return JSON.stringify(c, null, 2) } catch { return String(c) }
}

async function fetchDrafts() {
  loading.value = true
  try {
    const res = await listRuleDrafts({
      status: statusFilter.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    drafts.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    // 错误已由拦截器提示
  } finally {
    loading.value = false
  }
}

async function onGenerate() {
  generating.value = true
  try {
    const res = await generateRuleDraft({ category: category.value || undefined })
    const draftsRes = res.data.drafts || []
    ElMessage.success(`已生成 ${draftsRes.length} 条规则草稿`)
    await fetchDrafts()
  } catch (e) {
    // 拦截器已提示
  } finally {
    generating.value = false
  }
}

async function onRunShadow(row) {
  try {
    const res = await runShadow(row.id)
    const stats = res.data || {}
    ElMessage.success(`影子运行完成：命中 ${stats.hit_count} 条（不产生告警）`)
    await fetchDrafts()
  } catch (e) {}
}

function onView(row) {
  current.value = row
  detailVisible.value = true
}

async function onTune(row) {
  try {
    await ElMessageBox.confirm(
      '将基于当前草稿与误报反馈生成新版本草稿（原草稿进入待复审），是否继续？',
      '自动调优',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await tuneDraft(row.id, { false_positive_examples: [] })
    ElMessage.success('已生成调优后的新版本草稿')
    await fetchDrafts()
  } catch (e) {}
}

async function onEnable(row) {
  try {
    await ElMessageBox.confirm(
      `确认将草稿「${row.name}」审批为正式启用的检测规则？`,
      '人审启用',
      { type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await enableDraft(row.id)
    ElMessage.success('草稿已审批启用')
    await fetchDrafts()
  } catch (e) {}
}

async function onReject(row) {
  try {
    const { value } = await ElMessageBox.prompt('请填写驳回原因', '驳回草稿', {
      inputType: 'textarea',
      confirmButtonText: '确认驳回',
      cancelButtonText: '取消',
    })
    await rejectDraft(row.id, { reason: value || '管理员驳回' })
    ElMessage.success('草稿已驳回')
    await fetchDrafts()
  } catch (e) {}
}

function onPageChange(p) {
  page.value = p
  fetchDrafts()
}

onMounted(fetchDrafts)
</script>

<style scoped>
.rule-draft-view {
  padding: 20px;
}
.toolbar {
  margin-bottom: 16px;
  border: none;
}
.toolbar-row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.cat-input {
  width: 260px;
}
.status-select {
  width: 160px;
}
.list-card {
  border: none;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.dsl-block {
  margin-top: 14px;
}
.dsl-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-fg-default);
  margin-bottom: 6px;
}
.dsl-pre {
  background: var(--color-canvas-subtle, #f6f8fa);
  border: 1px solid var(--color-border-default, #e5e7eb);
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
.dsl-error {
  color: var(--color-danger-fg, #dc2626);
  font-size: 12px;
}
</style>
