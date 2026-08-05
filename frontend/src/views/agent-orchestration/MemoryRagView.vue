<template>
  <div class="memory-rag-view">
    <!-- 顶部（页面标题由 AgentOrchestrationLayout 顶部提供，此处仅保留操作按钮） -->
    <div class="mr-toolbar">
      <el-button @click="store.fetchKnowledgeBases" :loading="store.loading">刷新</el-button>
    </div>

    <!-- 概览指标：主色 #111827，单色状态点，无 gs-blue 强调 -->
    <div class="mr-stats">
      <div class="mr-stat">
        <span class="mr-stat-label">知识库</span>
        <span class="mr-stat-value">{{ store.knowledgeBases.length.toLocaleString('zh-CN') }}</span>
      </div>
      <div class="mr-stat">
        <span class="mr-stat-label">向量文档总数</span>
        <span class="mr-stat-value">{{ store.vectorDocCount.toLocaleString('zh-CN') }}</span>
      </div>
      <div class="mr-stat">
        <span class="mr-stat-label">已批准草稿</span>
        <span class="mr-stat-value">{{ (store.stats.approved_drafts || 0).toLocaleString('zh-CN') }}</span>
      </div>
      <div class="mr-stat">
        <span class="mr-stat-label">索引状态</span>
        <div class="mr-stat-status" :title="indexStatusTitle">
          <span class="mr-status-dot" :class="store.collectionReady ? 'ok' : 'off'" />
          <span class="mr-stat-value">{{ store.collectionReady ? '就绪' : '未就绪' }}</span>
        </div>
      </div>
    </div>

    <!-- 知识库卡片 -->
    <h3 class="mr-section">知识库 / 向量库 ({{ store.knowledgeBases.length }})</h3>
    <div class="mr-grid" v-loading="store.loading">
      <KnowledgeBaseCard
        v-for="kb in store.knowledgeBases"
        :key="kb.kb_id"
        :kb="kb"
      />
      <el-empty
        v-if="!store.loading && store.knowledgeBases.length === 0"
        description="向量库未初始化，当前使用关键词检索降级"
      />
    </div>

    <!-- 长期记忆（P2 agent_memories） -->
    <h3 class="mr-section mr-mt">长期记忆 ({{ store.memoryTotal }})</h3>
    <div class="mem-toolbar">
      <el-input
        v-model="searchQ"
        placeholder="检索记忆（内容 / 标签）"
        clearable
        class="mem-search"
        @keyup.enter="onSearch"
        @clear="onClearSearch"
      />
      <el-select
        v-model="typeFilter"
        placeholder="全部类型"
        clearable
        class="mem-type-select"
        @change="onTypeChange"
      >
        <el-option label="全部类型" value="" />
        <el-option v-for="t in MEMORY_TYPES" :key="t" :label="TYPE_LABELS[t]" :value="t" />
      </el-select>
      <el-button class="mem-btn-dark" :loading="store.memorySearchLoading" @click="onSearch">搜索</el-button>
      <el-button class="mem-btn-outline" @click="openCreate">+ 写入记忆</el-button>
    </div>

    <el-table
      :data="store.memories"
      v-loading="store.memoryLoading || store.memorySearchLoading"
      border
      class="mem-table"
    >
      <template #empty>
        <div class="mem-empty">
          <p class="mem-empty-text">{{ store.memoryMode === 'search' ? '未匹配记忆' : '暂无记忆' }}</p>
          <el-button link class="mem-empty-action" @click="openCreate">写入第一条记忆</el-button>
        </div>
      </template>
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <span class="mem-type-cell">
            <span class="mem-type-dot" />
            <span>{{ TYPE_LABELS[row.memory_type] || row.memory_type }}</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="内容" min-width="280" show-overflow-tooltip>
        <template #default="{ row }">{{ row.content }}</template>
      </el-table-column>
      <el-table-column label="来源 Agent" prop="agent_name" width="120" />
      <el-table-column label="节点" prop="source_node" width="110" />
      <el-table-column label="事件" prop="event_id" width="120" show-overflow-tooltip />
      <el-table-column label="主机" width="70">
        <template #default="{ row }">{{ row.host_id ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="写入人" prop="created_by" width="90" />
      <el-table-column label="时间" width="150">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link class="mem-delete" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="mem-pager">
      <el-pagination
        background
        layout="total, prev, pager, next"
        :total="store.memoryTotal"
        :page-size="store.memoryPageSize"
        :current-page="store.memoryPage"
        @current-change="onPageChange"
      />
    </div>

    <!-- 写入记忆对话框 -->
    <el-dialog v-model="createVisible" title="写入长期记忆" width="520px">
      <el-form label-width="96px">
        <el-form-item label="内容" required>
          <el-input
            v-model="createForm.content"
            type="textarea"
            :rows="4"
            placeholder="记忆正文（必填，截断 4000 字符）"
          />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.memory_type" class="mem-type-select">
            <el-option v-for="t in MEMORY_TYPES" :key="t" :label="TYPE_LABELS[t]" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源 Agent">
          <el-input v-model="createForm.agent_name" placeholder="可选，如 root_cause" />
        </el-form-item>
        <el-form-item label="节点">
          <el-input v-model="createForm.source_node" placeholder="可选，如 root_cause" />
        </el-form-item>
        <el-form-item label="事件 ID">
          <el-input v-model="createForm.event_id" placeholder="可选" />
        </el-form-item>
        <el-form-item label="主机 ID">
          <el-input v-model="createForm.host_id" placeholder="可选，数字" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="createForm.tags" placeholder="逗号分隔，如 powershell, C2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button class="mem-btn-dark" :loading="createSubmitting" @click="onCreate">提交</el-button>
      </template>
    </el-dialog>

    <!-- RAG 检索增强示意 -->
    <h3 class="mr-section mr-mt">检索增强 (RAG) 示意</h3>
    <el-card class="mr-hint-card" shadow="never">
      <p class="mr-hint">
        运行时，编排智能体可经由画布「知识库」节点从向量库检索相似上下文
        （文档块 + 向量相似度）注入到 Prompt，提升调查与处置的准确率。
        向量相似度检索服务由 <code>{{ vectorStore }}</code> 提供；
        知识增强注入需在流程中显式触发（画布知识库节点），自动注入开关见设置。
      </p>
      <div class="mr-flow">
        <span class="mr-flow-node">查询</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node">向量检索</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node">Top-K 文档块</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node">护栏评估</span>
        <el-icon><Right /></el-icon>
        <span class="mr-flow-node mr-node-accent">注入推理</span>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Right } from '@element-plus/icons-vue'
import { useMemoryStore } from '@/stores/memory'
import KnowledgeBaseCard from '@/components/agents/KnowledgeBaseCard.vue'

const store = useMemoryStore()
const vectorStore = computed(() => store.stats.vector_store || 'Chroma')

// 索引状态提示：就绪/未就绪 均用单色状态点，长说明放 title 保持卡片紧凑
const indexStatusTitle = computed(() =>
  store.collectionReady
    ? '向量库集合可用'
    : '向量库未就绪，当前使用关键词检索降级',
)

// ── P2 长期记忆 ──
const MEMORY_TYPES = ['conclusion', 'summary', 'action', 'disposition']
const TYPE_LABELS = {
  conclusion: '结论',
  summary: '摘要',
  action: '处置动作',
  disposition: '处置记录',
}

const searchQ = ref('')
const typeFilter = ref('')
const createVisible = ref(false)
const createSubmitting = ref(false)
const createForm = reactive({
  content: '',
  memory_type: 'summary',
  agent_name: '',
  source_node: '',
  event_id: '',
  host_id: '',
  tags: '',
})

onMounted(() => {
  // 初始加载（fail-safe：失败仅由拦截器提示，不产生 unhandled rejection）
  store.fetchKnowledgeBases().catch(() => {})
  store.fetchMemories().catch(() => {})
})

function currentFilters() {
  return { memory_type: typeFilter.value || undefined }
}

function showError(err) {
  // 后端 400/404 错误信封为 {detail:...}（HTTPException），统一读取兜底
  const msg =
    (err && err.response && err.response.data && err.response.data.detail) ||
    (err && err.message) ||
    '操作失败'
  ElMessage.error(msg)
}

async function onSearch() {
  const q = searchQ.value.trim()
  if (!q) {
    ElMessage.warning('请输入检索关键词')
    return
  }
  try {
    await store.searchMemories(q, currentFilters())
  } catch (err) {
    showError(err)
  }
}

async function onClearSearch() {
  try {
    await store.fetchMemories(currentFilters())
  } catch (err) {
    showError(err)
  }
}

async function onTypeChange() {
  if (store.memoryMode === 'search' && searchQ.value.trim()) {
    await onSearch()
  } else {
    try {
      await store.fetchMemories(currentFilters())
    } catch (err) {
      showError(err)
    }
  }
}

async function onPageChange(page) {
  store.memoryPage = page
  try {
    if (store.memoryMode === 'search' && searchQ.value.trim()) {
      await store.searchMemories(searchQ.value.trim(), currentFilters())
    } else {
      await store.fetchMemories(currentFilters())
    }
  } catch (err) {
    showError(err)
  }
}

function openCreate() {
  createForm.content = ''
  createForm.memory_type = 'summary'
  createForm.agent_name = ''
  createForm.source_node = ''
  createForm.event_id = ''
  createForm.host_id = ''
  createForm.tags = ''
  createVisible.value = true
}

async function onCreate() {
  if (!createForm.content.trim()) {
    ElMessage.warning('记忆内容不能为空')
    return
  }
  createSubmitting.value = true
  try {
    const tags = createForm.tags
      ? createForm.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      : []
    const payload = {
      content: createForm.content.trim(),
      memory_type: createForm.memory_type,
      agent_name: createForm.agent_name.trim() || undefined,
      source_node: createForm.source_node.trim() || undefined,
      event_id: createForm.event_id.trim() || undefined,
      host_id: createForm.host_id ? Number(createForm.host_id) : undefined,
      tags,
    }
    await store.addMemory(payload)
    createVisible.value = false
    ElMessage.success('记忆已写入')
  } catch (err) {
    showError(err)
  } finally {
    createSubmitting.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm('确认删除这条记忆？删除后不可恢复。', '删除记忆', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return // 用户取消
  }
  try {
    await store.removeMemory(row.id)
    ElMessage.success('已删除')
  } catch (err) {
    showError(err)
  }
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}
</script>

<style scoped>
.memory-rag-view { padding: 16px; }
.mr-toolbar { display: flex; align-items: center; justify-content: flex-end; margin-bottom: 12px; }

/* ===== 概览指标（紧凑 4 卡，主色 #111827） ===== */
.mr-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.mr-stat {
  flex: 1; min-width: 150px; max-width: 240px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 6px;
  min-height: 82px;
  justify-content: center;
}
.mr-stat-label { font-size: 12px; font-weight: 500; color: #6b7280; }
.mr-stat-value {
  font-size: 20px; font-weight: 600; color: #111827;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  line-height: 1.2; letter-spacing: -0.3px;
}
.mr-stat-status { display: flex; align-items: center; gap: 8px; min-height: 24px; }
.mr-status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.mr-status-dot.ok { background: #16a34a; }
.mr-status-dot.off { background: #9ca3af; }

/* ===== 分区标题 ===== */
.mr-section { font-size: 13px; font-weight: 600; margin: 0 0 10px; color: #111827; }
.mr-mt { margin-top: 22px; }
.mr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }

/* ===== P2 长期记忆：工具栏 ===== */
.mem-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.mem-search { flex: 1; max-width: 360px; }
.mem-search :deep(.el-input__wrapper) {
  border-radius: 8px;
  background: var(--color-canvas-default);
  box-shadow: 0 0 0 1px var(--color-border-default) inset;
  transition: box-shadow 0.15s;
}
.mem-search :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px #d1d5db inset; }
.mem-search :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px #111827 inset; }
.mem-search :deep(.el-input__inner) { font-size: 12px; color: var(--color-fg-default); }
.mem-search :deep(.el-input__inner::placeholder) { color: #9ca3af; }
.mem-type-select { width: 140px; }
.mem-type-select :deep(.el-select__wrapper) {
  border-radius: 8px;
  font-size: 12px;
  box-shadow: 0 0 0 1px var(--color-border-default) inset;
  transition: box-shadow 0.15s;
}
.mem-type-select :deep(.el-select__wrapper:hover) { box-shadow: 0 0 0 1px #d1d5db inset; }
.mem-type-select :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px #111827 inset; }

/* 主按钮：黑底白字；次按钮：白底黑边，hover 反色 */
.mem-btn-dark {
  --el-button-bg-color: #111827;
  --el-button-border-color: #111827;
  --el-button-text-color: #fff;
  --el-button-hover-bg-color: #1f2937;
  --el-button-hover-border-color: #1f2937;
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: #1f2937;
  --el-button-active-border-color: #1f2937;
}
.mem-btn-outline {
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

/* ===== P2 长期记忆：表格 ===== */
.mem-table {
  border-radius: 10px;
  --el-table-border-color: var(--color-border-default);
  --el-table-header-bg-color: var(--color-canvas-subtle);
  --el-table-header-text-color: #6b7280;
  --el-table-row-hover-bg-color: var(--color-canvas-subtle);
}
.mem-table :deep(th.el-table__cell) {
  font-size: 12px;
  font-weight: 500;
  padding: 8px 10px;
  height: 36px;
}
.mem-table :deep(td.el-table__cell) {
  padding: 8px 10px;
  font-size: 12px;
  color: var(--color-fg-default);
  height: 38px;
}
.mem-type-cell { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--color-fg-default); }
.mem-type-dot { width: 6px; height: 6px; border-radius: 50%; background: #9ca3af; flex-shrink: 0; }

.mem-delete {
  --el-button-text-color: #9ca3af;
  --el-button-hover-text-color: #dc2626;
  font-size: 12px;
}

/* 自定义空状态：去大图标，仅居中灰色文字 + 主操作链接 */
.mem-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 40px 0; }
.mem-empty-text { font-size: 13px; color: #9ca3af; margin: 0; }
.mem-empty-action {
  --el-button-text-color: #111827;
  --el-button-hover-text-color: #4b5563;
  font-size: 12px;
}

.mem-pager { display: flex; justify-content: flex-end; margin-top: 12px; }

/* ===== RAG 示意 ===== */
.mr-hint-card { border-radius: 10px; border: 1px solid var(--color-border-default); }
.mr-hint { font-size: 13px; color: var(--color-fg-muted); line-height: 1.7; margin: 0 0 12px; }
.mr-hint code { background: var(--color-canvas-inset); padding: 1px 5px; border-radius: 4px; font-family: ui-monospace, monospace; }
.mr-flow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mr-flow-node {
  font-size: 12px; padding: 5px 12px; border-radius: 16px;
  background: var(--color-canvas-subtle); color: var(--color-fg-default); border: 0.5px solid var(--color-border-default);
}
.mr-node-accent { background: #111827; color: #fff; border-color: #111827; }
</style>
