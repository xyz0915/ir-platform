<template>
  <div class="knowledge-view">
    <div class="card-box">
      <div class="flex-between mb-16">
        <h2 class="page-title">知识库管理</h2>
        <div class="action-buttons">
          <el-button type="primary" size="small" @click="showImportDialog = true">
            <el-icon><Upload /></el-icon> 手动导入
          </el-button>
          <el-dropdown @command="handleSync" trigger="click">
            <el-button type="warning" size="small" :loading="syncLoading">
              <el-icon><Connection /></el-icon> 第三方同步
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="virustotal">
                  <el-icon><Link /></el-icon> VirusTotal
                </el-dropdown-item>
                <el-dropdown-item command="abuseipdb">
                  <el-icon><Link /></el-icon> AbuseIPDB
                </el-dropdown-item>
                <el-dropdown-item command="alienvault_otx">
                  <el-icon><Link /></el-icon> AlienVault OTX
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>

      <!-- 四个 Tab -->
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <!-- 已入库 -->
        <el-tab-pane name="approved">
          <template #label>
            <span>已入库 <el-badge :value="approvedCount" :hidden="approvedCount === 0" class="tab-badge" /></span>
          </template>
          <el-table :data="approvedList" border stripe size="small" v-loading="tabLoading" empty-text="暂无已入库条目">
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
            <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ truncate(row.description, 60) }}</template>
            </el-table-column>
            <el-table-column prop="category" label="分类" width="100">
              <template #default="{ row }"><el-tag size="small" type="info">{{ row.category || 'auto' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="severity" label="严重程度" width="90">
              <template #default="{ row }"><el-tag size="small" :type="severityType(row.severity)">{{ severityLabel(row.severity) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="90">
              <template #default="{ row }"><el-tag size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="reviewed_at" label="审核时间" width="150" />
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <el-button type="warning" size="small" link @click="handleRecall(row)">撤回</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 待审核 -->
        <el-tab-pane name="pending">
          <template #label>
            <span>待审核 <el-badge :value="pendingCount" :hidden="pendingCount === 0" class="tab-badge" /></span>
          </template>
          <!-- 批量操作栏 -->
          <div v-if="selectedIds.length > 0" class="batch-bar">
            <span>已选 <strong>{{ selectedIds.length }}</strong> 条</span>
            <el-button type="success" size="small" @click="handleBatch('approve')">批量批准</el-button>
            <el-button type="danger" size="small" @click="handleBatch('reject')">批量拒绝</el-button>
            <el-button size="small" @click="clearSelection">取消选择</el-button>
          </div>
          <el-table
            ref="pendingTableRef"
            :data="pendingList"
            border stripe size="small"
            v-loading="tabLoading"
            empty-text="暂无待审核条目"
            @selection-change="handleSelectionChange"
          >
            <el-table-column type="selection" width="45" />
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
            <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ truncate(row.description, 60) }}</template>
            </el-table-column>
            <el-table-column prop="category" label="分类" width="100">
              <template #default="{ row }"><el-tag size="small" type="info">{{ row.category || 'auto' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="severity" label="严重程度" width="90">
              <template #default="{ row }"><el-tag size="small" :type="severityType(row.severity)">{{ severityLabel(row.severity) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="90">
              <template #default="{ row }"><el-tag size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="150" />
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button type="success" size="small" @click="handleSingleAction(row, 'approve')">批准</el-button>
                <el-button type="danger" size="small" @click="handleSingleAction(row, 'reject')">拒绝</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 已拒绝 -->
        <el-tab-pane name="rejected">
          <template #label>
            <span>已拒绝 <el-badge :value="rejectedCount" :hidden="rejectedCount === 0" class="tab-badge" /></span>
          </template>
          <el-table :data="rejectedList" border stripe size="small" v-loading="tabLoading" empty-text="暂无已拒绝条目">
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
            <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ truncate(row.description, 60) }}</template>
            </el-table-column>
            <el-table-column prop="category" label="分类" width="100">
              <template #default="{ row }"><el-tag size="small" type="info">{{ row.category || 'auto' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="severity" label="严重程度" width="90">
              <template #default="{ row }"><el-tag size="small" :type="severityType(row.severity)">{{ severityLabel(row.severity) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="source" label="来源" width="90">
              <template #default="{ row }"><el-tag size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="reviewed_at" label="拒绝时间" width="150" />
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <el-button type="warning" size="small" link @click="handleRecall(row)">撤回</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 种子数据 -->
        <el-tab-pane name="seeds">
          <template #label>
            <span>种子数据 <el-badge :value="seedCount" :hidden="seedCount === 0" class="tab-badge" /></span>
          </template>
          <el-table :data="seedList" border stripe size="small" v-loading="seedLoading" empty-text="种子数据为空">
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
            <el-table-column prop="description" label="描述" min-width="280" show-overflow-tooltip>
              <template #default="{ row }">{{ truncate(row.description, 80) }}</template>
            </el-table-column>
            <el-table-column prop="category" label="分类" width="130">
              <template #default="{ row }">
                <el-tag size="small" :type="categoryTagType(row.category)">{{ categoryLabel(row.category) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="severity" label="严重程度" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="severityType(row.severity)">{{ severityLabel(row.severity) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="tactic" label="战术阶段" width="140" show-overflow-tooltip />
            <el-table-column prop="id" label="MITRE ID" width="120" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 手动导入对话框 -->
    <el-dialog v-model="showImportDialog" title="手动导入知识条目" width="600px" destroy-on-close>
      <el-tabs v-model="importMode">
        <el-tab-pane label="粘贴文本" name="text">
          <el-input
            v-model="importText"
            type="textarea"
            :rows="8"
            placeholder="每行一个条目：&#10;标题：描述内容&#10;恶意C2通信检测：攻击者通过加密C2通道与远程服务器通信&#10;..."
          />
        </el-tab-pane>
        <el-tab-pane label="JSON 文件" name="file">
          <el-upload
            :auto-upload="false"
            :on-change="handleFileChange"
            :limit="1"
            accept=".json"
            drag
          >
            <el-icon size="40"><UploadFilled /></el-icon>
            <div>拖拽或点击上传 JSON 文件</div>
          </el-upload>
          <div v-if="filePreview" class="file-preview mt-8">
            <el-tag size="small" type="info">{{ filePreview.name }} ({{ filePreview.count }} 条)</el-tag>
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button type="primary" :loading="importLoading" @click="handleImport">提交导入</el-button>
      </template>
    </el-dialog>

    <!-- 导入结果对话框 -->
    <el-dialog v-model="showImportResult" title="导入结果" width="500px">
      <el-result
        :icon="importResult.imported > 0 ? 'success' : 'warning'"
        :title="`导入 ${importResult.imported} 条待审核知识条目，${importResult.skipped} 条跳过`"
      >
        <template v-if="importResult.skipped_reasons?.length" #sub-title>
          <div class="skipped-reasons">
            <p v-for="(r, i) in importResult.skipped_reasons" :key="i" class="reason-item">
              {{ r }}
            </p>
          </div>
        </template>
      </el-result>
      <template #footer>
        <el-button type="primary" @click="showImportResult = false; refreshCurrentTab()">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Connection, Link, UploadFilled } from '@element-plus/icons-vue'
import knowledgeApi from '@/api/knowledge'

// ── 状态 ──
const activeTab = ref('pending')
const tabLoading = ref(false)
const seedLoading = ref(false)
const syncLoading = ref(false)
const importLoading = ref(false)

const pendingList = ref([])
const approvedList = ref([])
const rejectedList = ref([])
const seedList = ref([])

const pendingTableRef = ref(null)
const selectedIds = ref([])

// 导入
const showImportDialog = ref(false)
const showImportResult = ref(false)
const importMode = ref('text')
const importText = ref('')
const fileData = ref(null)
const filePreview = ref(null)
const importResult = reactive({ imported: 0, skipped: 0, skipped_reasons: [] })

// ── 计数 ──
const pendingCount = computed(() => pendingList.value.length)
const approvedCount = computed(() => approvedList.value.length)
const rejectedCount = computed(() => rejectedList.value.length)
const seedCount = computed(() => seedList.value.length)

// ── 数据加载 ──
onMounted(() => { loadAll() })

async function loadAll() {
  await Promise.all([
    loadByStatus('pending'),
    loadByStatus('approved'),
    loadByStatus('rejected'),
    loadSeeds()
  ])
}

async function loadByStatus(status) {
  try {
    const res = await knowledgeApi.getDrafts({ status })
    const data = res.data || []
    if (status === 'pending') pendingList.value = data
    else if (status === 'approved') approvedList.value = data
    else if (status === 'rejected') rejectedList.value = data
  } catch (error) { /* handled */ }
}

async function loadSeeds() {
  seedLoading.value = true
  try {
    const res = await knowledgeApi.getSeeds()
    seedList.value = res.data || []
  } catch (error) { seedList.value = [] }
  finally { seedLoading.value = false }
}

async function refreshCurrentTab() {
  if (activeTab.value === 'seeds') await loadSeeds()
  else await loadByStatus(activeTab.value)
}

function handleTabChange() {
  selectedIds.value = []
  if (activeTab.value !== 'seeds') loadByStatus(activeTab.value)
}

// ── 单条操作 ──
async function handleSingleAction(row, action) {
  try {
    if (action === 'approve') {
      await knowledgeApi.approveDraft(row.id)
      ElMessage.success('已批准')
    } else {
      await knowledgeApi.rejectDraft(row.id)
      ElMessage.success('已拒绝')
    }
    await loadAll()
  } catch (error) { /* handled */ }
}

// ── 撤回 ──
async function handleRecall(row) {
  try {
    await ElMessageBox.confirm(
      `确认将「${row.title}」撤回至待审核？`,
      '撤回确认',
      { confirmButtonText: '确认撤回', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  try {
    await knowledgeApi.recallDraft(row.id)
    ElMessage.success('已撤回至待审核')
    await loadAll()
  } catch (error) { /* handled */ }
}

// ── 批量操作 ──
function handleSelectionChange(rows) {
  selectedIds.value = rows.map(r => r.id)
}

function clearSelection() {
  selectedIds.value = []
  if (pendingTableRef.value) {
    pendingTableRef.value.clearSelection()
  }
}

async function handleBatch(action) {
  if (selectedIds.value.length === 0) return
  const label = action === 'approve' ? '批准' : '拒绝'
  try {
    await ElMessageBox.confirm(
      `确认批量${label} ${selectedIds.value.length} 条草稿？`,
      `批量${label}`,
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  tabLoading.value = true
  try {
    const res = await knowledgeApi.batchAction(selectedIds.value, action)
    ElMessage.success(`已成功${label} ${res.data?.success || selectedIds.value.length} 条`)
    selectedIds.value = []
    await loadAll()
  } catch (error) { /* handled */ }
  finally { tabLoading.value = false }
}

// ── 导入 ──
function handleFileChange(file) {
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result)
      const items = Array.isArray(data) ? data : (data.items || [data])
      fileData.value = items
      filePreview.value = { name: file.name, count: items.length }
    } catch (err) {
      ElMessage.error('JSON 文件解析失败')
      fileData.value = null
      filePreview.value = null
    }
  }
  reader.readAsText(file.raw)
}

async function handleImport() {
  const payload = {}
  let hasContent = false

  if (importMode.value === 'text' && importText.value.trim()) {
    payload.text = importText.value.trim()
    hasContent = true
  } else if (importMode.value === 'file' && fileData.value?.length) {
    payload.items = fileData.value
    hasContent = true
  }

  if (!hasContent) {
    ElMessage.warning('请输入或上传导入内容')
    return
  }

  importLoading.value = true
  try {
    const res = await knowledgeApi.importData(payload)
    const d = res.data || {}
    importResult.imported = d.imported || 0
    importResult.skipped = d.skipped || 0
    importResult.skipped_reasons = d.skipped_reasons || []
    showImportDialog.value = false
    showImportResult.value = true
    importText.value = ''
    fileData.value = null
    filePreview.value = null
  } catch (error) { /* handled */ }
  finally { importLoading.value = false }
}

// ── 第三方同步 ──
async function handleSync(provider) {
  syncLoading.value = true
  try {
    const res = await knowledgeApi.syncProvider(provider)
    const d = res.data || {}
    ElMessage.success(`${provider}: ${d.message || '同步完成'}`)
    if (d.synced > 0) await loadByStatus('pending')
  } catch (error) { /* handled */ }
  finally { syncLoading.value = false }
}

// ── 工具函数 ──
function truncate(str, len) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '...' : str
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

function sourceTagType(src) {
  const map = { ai_suggest: 'warning', manual: '', external: 'success' }
  return map[src] || 'info'
}

function categoryLabel(cat) {
  const map = { mitre_attack: 'MITRE ATT&CK', c2_framework: 'C2 框架', malware_behavior: '恶意软件行为', auto: '自动' }
  return map[cat] || cat || '自动'
}

function categoryTagType(cat) {
  const map = { mitre_attack: 'danger', c2_framework: 'warning', malware_behavior: 'danger', auto: 'info' }
  return map[cat] || 'info'
}
</script>

<style scoped>
.action-buttons {
  display: flex;
  gap: 8px;
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 10px;
  background: var(--el-color-primary-light-9);
  border-radius: 6px;
  border: 1px solid var(--el-color-primary-light-5);
  font-size: 13px;
}

.tab-badge {
  margin-left: 4px;
}

.file-preview { margin-top: 8px; }
.mt-8 { margin-top: 8px; }
.mb-16 { margin-bottom: 16px; }

.skipped-reasons {
  text-align: left;
  max-height: 200px;
  overflow-y: auto;
  font-size: 12px;
  color: var(--color-fg-muted);
}

.reason-item {
  margin: 2px 0;
  padding: 2px 0;
  border-bottom: 1px dashed var(--color-border-default);
}

.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
</style>
