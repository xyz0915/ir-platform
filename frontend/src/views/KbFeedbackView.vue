<template>
  <div class="kb-feedback-view">
    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num">{{ stats.total }}</div>
          <div class="stat-label">反馈总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num stat-ok">{{ stats.applied }}</div>
          <div class="stat-label">已沉淀入 KB</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num stat-warn">{{ stats.unapplied }}</div>
          <div class="stat-label">待自进化</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num">{{ stats.false_positive }}</div>
          <div class="stat-label">误报反馈</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 工具栏 -->
    <el-card shadow="never" class="toolbar">
      <div class="toolbar-row">
        <el-select v-model="typeFilter" placeholder="类型筛选" clearable class="type-select">
          <el-option label="全部" value="" />
          <el-option label="误报" value="false_positive" />
          <el-option label="真阳性" value="true_positive" />
          <el-option label="抑制" value="suppress" />
        </el-select>
        <el-select v-model="appliedFilter" placeholder="沉淀状态" clearable class="applied-select">
          <el-option label="全部" value="" />
          <el-option label="已沉淀" :value="1" />
          <el-option label="未沉淀" :value="0" />
        </el-select>
        <el-button type="primary" @click="onSubmit">
          <el-icon><Edit /></el-icon>
          <span>提交反馈</span>
        </el-button>
        <el-button type="success" :loading="evolving" @click="onEvolve">
          <el-icon><MagicStick /></el-icon>
          <span>触发自进化</span>
        </el-button>
        <el-button :loading="loading" @click="refreshAll">
          <el-icon><Refresh /></el-icon>
          <span>刷新</span>
        </el-button>
      </div>
    </el-card>

    <!-- 反馈列表 -->
    <el-card shadow="never" class="list-card">
      <el-table :data="feedbacks" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="feedback_type" label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="typeTag(row.feedback_type)" size="small">{{ typeLabel(row.feedback_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rule_name" label="规则名" min-width="160" show-overflow-tooltip />
        <el-table-column prop="content" label="反馈内容" min-width="220" show-overflow-tooltip />
        <el-table-column prop="source_user" label="提交人" width="120" />
        <el-table-column label="是否已沉淀" width="110">
          <template #default="{ row }">
            <el-tag :type="row.applied_to_kb ? 'success' : 'info'" size="small">
              {{ row.applied_to_kb ? '已沉淀' : '未沉淀' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="kb_entry_id" label="沉淀条目" width="140" show-overflow-tooltip />
        <el-table-column prop="created_at" label="提交时间" width="170" />
        <el-table-column label="操作" min-width="160" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="success"
              :disabled="row.applied_to_kb"
              @click="onEvolveOne(row)"
            >自进化</el-button>
            <el-button link type="primary" @click="onView(row)">详情</el-button>
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

    <!-- 沉淀结果 -->
    <el-card shadow="never" class="deposit-card" v-if="stats.deposits && stats.deposits.length">
      <template #header>近期沉淀条目（越用越聪明）</template>
      <el-table :data="stats.deposits" stripe style="width: 100%">
        <el-table-column prop="feedback_type" label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="typeTag(row.feedback_type)" size="small">{{ typeLabel(row.feedback_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rule_name" label="规则名" min-width="160" show-overflow-tooltip />
        <el-table-column prop="kb_entry_id" label="条目引用" width="160" show-overflow-tooltip />
        <el-table-column prop="summary" label="沉淀摘要" min-width="260" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" width="170" />
      </el-table>
    </el-card>

    <!-- 提交反馈对话框 -->
    <el-dialog v-model="submitVisible" title="提交知识反馈" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="反馈类型" required>
          <el-select v-model="form.feedback_type" placeholder="请选择" style="width: 100%">
            <el-option label="误报" value="false_positive" />
            <el-option label="真阳性（有效）" value="true_positive" />
            <el-option label="抑制" value="suppress" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则名">
          <el-input v-model="form.rule_name" placeholder="关联规则名（误报/抑制将用于自动抑制）" />
        </el-form-item>
        <el-form-item label="主机 ID">
          <el-input v-model.number="form.host_id" placeholder="定向抑制的主机 ID（留空=全局）" />
        </el-form-item>
        <el-form-item label="关联事件">
          <el-input v-model="form.event_id" placeholder="可选：事件 ID" />
        </el-form-item>
        <el-form-item label="反馈内容">
          <el-input v-model="form.content" type="textarea" :rows="3" placeholder="分析师备注 / 误报原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="submitVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="doSubmit">提交</el-button>
      </template>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailVisible" title="反馈详情" width="600px">
      <template v-if="current">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="ID">{{ current.id }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ typeLabel(current.feedback_type) }}</el-descriptions-item>
          <el-descriptions-item label="规则名">{{ current.rule_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="主机 ID">{{ current.host_id ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="提交人">{{ current.source_user || '-' }}</el-descriptions-item>
          <el-descriptions-item label="是否已沉淀">
            <el-tag :type="current.applied_to_kb ? 'success' : 'info'" size="small">
              {{ current.applied_to_kb ? '已沉淀' : '未沉淀' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="抑制 ID">{{ current.suppression_id ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="知识草稿 ID">{{ current.knowledge_draft_id ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="沉淀条目">{{ current.kb_entry_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="沉淀摘要">{{ current.summary || '-' }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ current.created_at }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  submitKbFeedback,
  listKbFeedback,
  evolveKb,
  getKbStats,
} from '@/api/kbFeedback'

const feedbacks = ref([])
const loading = ref(false)
const evolving = ref(false)
const submitting = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)

const typeFilter = ref('')
const appliedFilter = ref('')

const stats = ref({
  total: 0, applied: 0, unapplied: 0,
  false_positive: 0, suppress: 0, true_positive: 0, deposits: [],
})

const submitVisible = ref(false)
const detailVisible = ref(false)
const current = ref(null)
const form = ref({
  feedback_type: 'false_positive',
  rule_name: '',
  host_id: null,
  event_id: '',
  content: '',
})

const TYPE_TAG = {
  false_positive: 'warning',
  true_positive: 'success',
  suppress: 'danger',
}
const TYPE_LABEL = {
  false_positive: '误报',
  true_positive: '真阳性',
  suppress: '抑制',
}
function typeTag(t) { return TYPE_TAG[t] || 'info' }
function typeLabel(t) { return TYPE_LABEL[t] || t }

async function refreshStats() {
  try {
    const res = await getKbStats()
    stats.value = res.data || stats.value
  } catch (e) { /* 拦截器已提示 */ }
}

async function fetchFeedbacks() {
  loading.value = true
  try {
    const res = await listKbFeedback({
      feedback_type: typeFilter.value || undefined,
      applied: appliedFilter.value === '' ? undefined : appliedFilter.value,
      page: page.value,
      page_size: pageSize.value,
    })
    feedbacks.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) { /* 拦截器已提示 */ }
  finally { loading.value = false }
}

async function refreshAll() {
  await Promise.all([refreshStats(), fetchFeedbacks()])
}

function onSubmit() {
  form.value = {
    feedback_type: 'false_positive',
    rule_name: '',
    host_id: null,
    event_id: '',
    content: '',
  }
  submitVisible.value = true
}

async function doSubmit() {
  if (!form.value.feedback_type) {
    ElMessage.warning('请选择反馈类型')
    return
  }
  submitting.value = true
  try {
    await submitKbFeedback({ ...form.value })
    ElMessage.success('反馈已提交')
    submitVisible.value = false
    await refreshAll()
  } catch (e) { /* 拦截器已提示 */ }
  finally { submitting.value = false }
}

async function onEvolve() {
  try {
    await ElMessageBox.confirm(
      '将把全部未沉淀反馈自动沉淀为抑制 + 知识条目（approved），是否继续？',
      '触发自进化',
      { type: 'warning' }
    )
  } catch {
    return
  }
  evolving.value = true
  try {
    const res = await evolveKb({})
    const d = res.data || {}
    ElMessage.success(`自进化完成：处理 ${d.processed} 条，沉淀 ${d.applied} 条`)
    await refreshAll()
  } catch (e) { /* 拦截器已提示 */ }
  finally { evolving.value = false }
}

async function onEvolveOne(row) {
  evolving.value = true
  try {
    const res = await evolveKb({ feedback_id: row.id })
    const d = res.data || {}
    const detail = (d.details || [])[0] || {}
    if (detail.applied_to_kb) {
      ElMessage.success(`反馈 #${row.id} 已沉淀（条目 ${detail.entry_ref || '-'}）`)
    } else {
      ElMessage.info(`反馈 #${row.id} 未产生沉淀`)
    }
    await refreshAll()
  } catch (e) { /* 拦截器已提示 */ }
  finally { evolving.value = false }
}

function onView(row) {
  current.value = row
  detailVisible.value = true
}

function onPageChange(p) {
  page.value = p
  fetchFeedbacks()
}

onMounted(refreshAll)
</script>

<style scoped>
.kb-feedback-view { padding: 20px; }
.stat-row { margin-bottom: 16px; }
.stat-card {
  border: none;
  text-align: center;
}
.stat-num { font-size: 28px; font-weight: 700; color: var(--color-fg-default); }
.stat-ok { color: var(--color-success-fg, #16a34a); }
.stat-warn { color: var(--color-warning-fg, #d97706); }
.stat-label { font-size: 13px; color: var(--color-fg-muted); margin-top: 4px; }
.toolbar { margin-bottom: 16px; border: none; }
.toolbar-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.type-select { width: 160px; }
.applied-select { width: 150px; }
.list-card { border: none; }
.deposit-card { margin-top: 16px; border: none; }
.pager { margin-top: 16px; display: flex; justify-content: flex-end; }
</style>
