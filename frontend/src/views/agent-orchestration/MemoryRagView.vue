<template>
  <div class="memory-rag-view">
    <!-- 顶部 -->
    <div class="mr-toolbar">
      <div class="mr-title">
        <h2>记忆与 RAG</h2>
        <span class="mr-sub">长期记忆 / 知识库 / 向量库（真实数据）</span>
      </div>
      <el-button @click="store.fetchKnowledgeBases" :loading="store.loading">刷新</el-button>
    </div>

    <!-- 概览指标 -->
    <div class="mr-stats">
      <div class="mr-stat">
        <span class="gs-label">知识库</span>
        <span class="gs-value">{{ store.knowledgeBases.length }}</span>
      </div>
      <div class="mr-stat">
        <span class="gs-label">向量文档总数</span>
        <span class="gs-value gs-blue">{{ store.vectorDocCount.toLocaleString('zh-CN') }}</span>
      </div>
      <div class="mr-stat">
        <span class="gs-label">已批准草稿</span>
        <span class="gs-value gs-green">{{ (store.stats.approved_drafts || 0).toLocaleString('zh-CN') }}</span>
      </div>
      <div class="mr-stat">
        <span class="gs-label">索引状态</span>
        <span class="gs-value gs-sm" :class="store.collectionReady ? 'gs-ok' : 'gs-warn'">
          {{ store.collectionReady ? '就绪' : '未就绪/降级关键词检索' }}
        </span>
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
      <el-button type="primary" :loading="store.memorySearchLoading" @click="onSearch">搜索</el-button>
      <el-button type="primary" plain @click="openCreate">+ 写入记忆</el-button>
    </div>

    <el-table
      :data="store.memories"
      v-loading="store.memoryLoading || store.memorySearchLoading"
      border
      class="mem-table"
      empty-text="暂无记忆；流水线关键节点（root_cause/llm/reporter/responder/action）会自动沉淀，也可手动写入"
    >
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag :type="typeTagType(row.memory_type)" size="small">
            {{ TYPE_LABELS[row.memory_type] || row.memory_type }}
          </el-tag>
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
          <el-button link type="danger" @click="onDelete(row)">删除</el-button>
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
        <el-button type="primary" :loading="createSubmitting" @click="onCreate">提交</el-button>
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

// ── P2 长期记忆 ──
const MEMORY_TYPES = ['conclusion', 'summary', 'action', 'disposition']
const TYPE_LABELS = {
  conclusion: '结论',
  summary: '摘要',
  action: '处置动作',
  disposition: '处置记录',
}
const TYPE_TAG_MAP = {
  conclusion: 'danger',
  summary: 'primary',
  action: 'warning',
  disposition: 'success',
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

function typeTagType(t) {
  return TYPE_TAG_MAP[t] || 'info'
}

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
.mr-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.mr-title h2 { margin: 0; font-size: 18px; font-weight: 600; color: #111827; }
.mr-sub { display: block; font-size: 12px; color: var(--color-fg-subtle); margin-top: 2px; }

.mr-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.mr-stat {
  flex: 1; min-width: 150px; max-width: 240px; background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default); border-radius: 8px;
  padding: 12px 16px; display: flex; flex-direction: column; gap: 4px;
}
.gs-label { font-size: 12px; color: var(--color-fg-subtle); }
.gs-value { font-size: 22px; font-weight: 700; color: #111827; font-family: ui-monospace, monospace; }
.gs-sm { font-size: 15px; line-height: 1.6; }
.gs-blue { color: #3B82F6; }
.gs-green { color: #10B981; }
.gs-ok { color: #10B981; }
.gs-warn { color: #F59E0B; }

.mr-section { font-size: 14px; font-weight: 500; margin: 0 0 10px; color: #111827; }
.mr-mt { margin-top: 22px; }
.mr-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }

/* ── P2 长期记忆区块 ── */
.mem-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.mem-search { width: 260px; }
.mem-type-select { width: 140px; }
.mem-table { border-radius: 8px; }
.mem-pager { display: flex; justify-content: flex-end; margin-top: 12px; }

.mr-hint-card { border-radius: 10px; border: 1px solid var(--color-border-default); }
.mr-hint { font-size: 13px; color: var(--color-fg-muted); line-height: 1.7; margin: 0 0 12px; }
.mr-hint code { background: var(--color-canvas-inset); padding: 1px 5px; border-radius: 4px; font-family: ui-monospace, monospace; }
.mr-flow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mr-flow-node {
  font-size: 12px; padding: 5px 12px; border-radius: 16px;
  background: var(--color-canvas-subtle); color: var(--color-fg-default); border: 0.5px solid var(--color-border-default);
}
.mr-node-accent { background: var(--color-accent-subtle); color: var(--color-accent-fg); border-color: var(--color-accent-fg); }
</style>
