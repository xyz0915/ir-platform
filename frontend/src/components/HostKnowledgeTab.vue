<template>
  <div class="host-knowledge-tab">
    <!-- 顶部操作栏 -->
    <div class="tab-toolbar">
      <span class="tab-hint">
        共 <strong>{{ drafts.length }}</strong> 条 AI 生成的待审核知识草稿
      </span>
      <el-button
        type="success"
        size="small"
        :disabled="drafts.length === 0"
        :loading="batchLoading"
        @click="handleApproveAll"
      >
        全部批准
      </el-button>
    </div>

    <!-- 草稿列表 -->
    <el-table
      :data="drafts"
      border
      stripe
      size="small"
      v-loading="loading"
      empty-text="暂无待审核草稿"
      max-height="500"
    >
      <el-table-column type="index" label="#" width="50" />
      <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
      <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="desc-preview">{{ truncate(row.description, 80) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="category" label="分类" width="110">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.category || 'auto' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="severity" label="严重程度" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="severityType(row.severity)">
            {{ severityLabel(row.severity) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source === 'ai_suggest' ? 'warning' : 'info'">
            {{ sourceLabel(row.source) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160" />
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button
            type="success"
            size="small"
            :loading="actionLoading === row.id + '_approve'"
            @click="handleApprove(row)"
          >
            批准
          </el-button>
          <el-button
            type="danger"
            size="small"
            :loading="actionLoading === row.id + '_reject'"
            @click="handleReject(row)"
          >
            拒绝
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import knowledgeApi from '@/api/knowledge'

const props = defineProps({
  hostId: { type: [String, Number], required: true }
})

const drafts = ref([])
const loading = ref(false)
const batchLoading = ref(false)
const actionLoading = ref(null)

async function loadDrafts() {
  loading.value = true
  try {
    const res = await knowledgeApi.getDrafts({ host_id: String(props.hostId), status: 'pending' })
    drafts.value = res.data || []
  } catch (error) {
    drafts.value = []
  } finally {
    loading.value = false
  }
}

async function handleApprove(row) {
  actionLoading.value = row.id + '_approve'
  try {
    await knowledgeApi.approveDraft(row.id)
    ElMessage.success('已批准')
    await loadDrafts()
  } catch (error) {
    // handled by interceptor
  } finally {
    actionLoading.value = null
  }
}

async function handleReject(row) {
  actionLoading.value = row.id + '_reject'
  try {
    await knowledgeApi.rejectDraft(row.id)
    ElMessage.success('已拒绝')
    await loadDrafts()
  } catch (error) {
    // handled by interceptor
  } finally {
    actionLoading.value = null
  }
}

async function handleApproveAll() {
  try {
    await ElMessageBox.confirm(
      `确认批准全部 ${drafts.value.length} 条知识草稿？`,
      '批量批准',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  batchLoading.value = true
  const ids = drafts.value.map(d => d.id)
  try {
    const res = await knowledgeApi.batchAction(ids, 'approve')
    ElMessage.success(`已成功批准 ${res.data?.success || ids.length} 条`)
    await loadDrafts()
  } catch (error) {
    // handled
  } finally {
    batchLoading.value = false
  }
}

function severityType(sev) {
  const map = { low: 'info', medium: 'warning', high: 'danger', critical: 'danger' }
  return map[sev] || 'info'
}

function severityLabel(sev) {
  const map = { low: '低', medium: '中', high: '高', critical: '严重' }
  return map[sev] || sev || '中'
}

function sourceLabel(src) {
  const map = { ai_suggest: 'AI 建议', manual: '手动', external: '外部同步' }
  return map[src] || src || 'AI 建议'
}

function truncate(str, len) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '...' : str
}

onMounted(loadDrafts)
watch(() => props.hostId, loadDrafts)
</script>

<style scoped>
.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--color-canvas-subtle);
  border-radius: 6px;
  border: 1px solid var(--color-border-default);
}
.tab-hint {
  font-size: 13px;
  color: var(--color-fg-muted);
}
.desc-preview {
  color: var(--color-fg-muted);
  font-size: 12px;
}
</style>
