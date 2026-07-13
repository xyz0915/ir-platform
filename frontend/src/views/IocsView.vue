<template>
  <div class="ioc-view">
    <div class="card-box">
      <div class="flex-between mb-16">
        <h2 class="page-title">
          <span class="title-emoji">⚡</span>
          <span>IOC 指标管理</span>
          <el-tag class="title-tag" type="danger" effect="plain" size="small">🎯 威胁情报</el-tag>
        </h2>
        <div>
          <el-button
            type="warning"
            size="small"
            :disabled="enrichableSelection.length === 0"
            :loading="batchLoading"
            @click="handleBatchEnrich"
          >
            批量查询情报 ({{ enrichableSelection.length }})
          </el-button>
          <el-button type="success" size="small" @click="showImportDialog = true">批量导入</el-button>
          <el-button type="primary" size="small" @click="showAddDialog = true">添加 IOC</el-button>
        </div>
      </div>

      <!-- 类型筛选 -->
      <el-radio-group v-model="typeFilter" size="small" class="mb-12" @change="loadIocs">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button label="ip">IP</el-radio-button>
        <el-radio-button label="domain">域名</el-radio-button>
        <el-radio-button label="url">URL</el-radio-button>
        <el-radio-button label="hash">文件哈希</el-radio-button>
        <el-radio-button label="cert">证书</el-radio-button>
      </el-radio-group>

      <!-- IOC 表格 -->
      <el-table
        :data="iocData"
        border
        stripe
        size="small"
        v-loading="loading"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="ioc_type" label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="typeTagType(row.ioc_type)">
              {{ typeLabel(row.ioc_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ioc_value" label="指标值" min-width="260" show-overflow-tooltip />
        <el-table-column label="威胁等级" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.threatLevel" size="small" :type="threatLevelTagType(row.threatLevel)">
              {{ threatLevelLabel(row.threatLevel) }}
            </el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="风险评分" width="100">
          <template #default="{ row }">
            <span v-if="row.riskScore !== null && row.riskScore !== undefined">
              <el-tag size="small" :type="riskScoreTagType(row.riskScore)">{{ row.riskScore }}</el-tag>
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.source === 'default'" type="info" size="small">内置默认</el-tag>
            <el-tag v-else type="success" size="small">用户添加</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
        <el-table-column prop="enabled" label="启用" width="90">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="(val) => handleToggleEnabled(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button
              v-if="row.ioc_type === 'ip' || row.ioc_type === 'domain'"
              type="primary"
              link
              size="small"
              :loading="row._enriching"
              @click="handleEnrich(row)"
            >
              查询情报
            </el-button>
            <el-tooltip v-else content="仅支持 ip/domain 类型外联查询" placement="top">
              <span>
                <el-button type="info" link size="small" disabled>查询情报</el-button>
              </span>
            </el-tooltip>
            <el-button type="primary" link size="small" @click="openDetail(row)">详情</el-button>
            <el-popconfirm
              title="确认删除该 IOC？"
              @confirm="handleDelete(row)"
            >
              <template #reference>
                <el-button type="danger" link size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 添加 IOC 对话框 -->
    <el-dialog
      v-model="showAddDialog"
      title="添加 IOC"
      width="500px"
      destroy-on-close
    >
      <el-form :model="addForm" label-width="80px" size="small">
        <el-form-item label="类型">
          <el-select v-model="addForm.ioc_type" placeholder="选择类型">
            <el-option label="IP" value="ip" />
            <el-option label="域名" value="domain" />
            <el-option label="URL" value="url" />
            <el-option label="文件哈希" value="hash" />
            <el-option label="证书" value="cert" />
          </el-select>
        </el-form-item>
        <el-form-item label="指标值">
          <el-input v-model="addForm.ioc_value" placeholder="输入 IOC 指标值" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="addForm.description" placeholder="输入描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleAdd">确定</el-button>
      </template>
    </el-dialog>

    <!-- 批量导入对话框 -->
    <el-dialog
      v-model="showImportDialog"
      title="批量导入 IOC"
      width="560px"
      destroy-on-close
    >
      <el-form :model="importForm" label-width="80px" size="small">
        <el-form-item label="类型">
          <el-select v-model="importForm.ioc_type" placeholder="选择类型">
            <el-option label="IP" value="ip" />
            <el-option label="域名" value="domain" />
            <el-option label="URL" value="url" />
            <el-option label="文件哈希" value="hash" />
            <el-option label="证书" value="cert" />
          </el-select>
        </el-form-item>
        <el-form-item label="指标值">
          <el-input
            v-model="importForm.raw"
            type="textarea"
            :rows="10"
            placeholder="每行一个指标值，例如：&#10;8.8.8.8&#10;1.1.1.1&#10;evil.example.com"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="handleImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog
      v-model="showDetailDialog"
      title="IOC 详情"
      width="720px"
      destroy-on-close
      @open="loadDetailThreatIntel"
    >
      <template v-if="detailRow">
        <el-descriptions :column="2" border size="small" class="mb-16">
          <el-descriptions-item label="ID">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ typeLabel(detailRow.ioc_type) }}</el-descriptions-item>
          <el-descriptions-item label="指标值" :span="2">{{ detailRow.ioc_value }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ detailRow.source }}</el-descriptions-item>
          <el-descriptions-item label="启用">{{ detailRow.enabled ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="描述" :span="2">{{ detailRow.description || '—' }}</el-descriptions-item>
        </el-descriptions>

        <el-tabs v-model="detailTab">
          <el-tab-pane label="威胁情报" name="threat">
            <div v-loading="detailTiLoading">
              <el-empty v-if="!detailThreatIntel.length" description="暂无威胁情报查询结果" />
              <el-timeline v-else>
                <el-timeline-item
                  v-for="ti in detailThreatIntel"
                  :key="ti.id"
                  :timestamp="ti.queried_at"
                  placement="top"
                >
                  <el-card shadow="never" size="small">
                    <div class="ti-row">
                      <span>Provider:</span><el-tag size="small">{{ ti.provider }}</el-tag>
                      <span class="ml">威胁等级:</span>
                      <el-tag v-if="ti.threat_level" size="small" :type="threatLevelTagType(ti.threat_level)">
                        {{ threatLevelLabel(ti.threat_level) }}
                      </el-tag>
                      <span v-else class="muted">—</span>
                      <span class="ml">风险评分:</span>
                      <el-tag size="small" :type="riskScoreTagType(ti.risk_score)">{{ ti.risk_score }}</el-tag>
                    </div>
                    <div class="ti-row">
                      <span>判定:</span>
                      <el-tag
                        v-for="j in (ti.judgments || [])"
                        :key="j"
                        size="small"
                        :type="judgmentTagType(j)"
                        class="mr"
                      >{{ j }}</el-tag>
                      <span v-if="!ti.judgments || !ti.judgments.length" class="muted">—</span>
                    </div>
                    <div class="ti-row">
                      <span>标签:</span>
                      <el-tag
                        v-for="t in (ti.tags || [])"
                        :key="t"
                        size="small"
                        type="info"
                        class="mr"
                      >{{ t }}</el-tag>
                      <span v-if="!ti.tags || !ti.tags.length" class="muted">—</span>
                    </div>
                    <div class="ti-row">
                      <span>团伙:</span>
                      <span>{{ (ti.company && ti.company.length) ? ti.company.join(', ') : '—' }}</span>
                      <span class="ml">置信度:</span>
                      <span>{{ ti.confidence }}</span>
                    </div>
                    <div v-if="ti.raw_summary" class="ti-summary">
                      <span>原始摘要:</span> {{ ti.raw_summary }}
                    </div>
                  </el-card>
                </el-timeline-item>
              </el-timeline>
            </div>
          </el-tab-pane>
          <el-tab-pane label="基本信息" name="basic">
            <pre class="raw-json">{{ JSON.stringify(detailRow, null, 2) }}</pre>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import iocApi from '@/api/iocs'

const iocData = ref([])
const loading = ref(false)
const typeFilter = ref('')
const showAddDialog = ref(false)
const showImportDialog = ref(false)
const saving = ref(false)
const importing = ref(false)
const batchLoading = ref(false)

const selectedRows = ref([])

const showDetailDialog = ref(false)
const detailRow = ref(null)
const detailTab = ref('threat')
const detailThreatIntel = ref([])
const detailTiLoading = ref(false)

const addForm = ref({
  ioc_type: 'ip',
  ioc_value: '',
  description: ''
})
const importForm = ref({
  ioc_type: 'ip',
  raw: ''
})

const enrichableSelection = computed(() =>
  selectedRows.value.filter((r) => r.ioc_type === 'ip' || r.ioc_type === 'domain')
)

onMounted(() => {
  loadIocs()
})

async function loadIocs() {
  loading.value = true
  try {
    const params = {}
    if (typeFilter.value) {
      params.ioc_type = typeFilter.value
    }
    const res = await iocApi.getIocs(params)
    const list = res.data || []
    iocData.value = list
    // 拉取每个 ip/domain 行的最新威胁情报（用于列表威胁等级/风险评分列）
    for (const row of list) {
      if (row.ioc_type === 'ip' || row.ioc_type === 'domain') {
        await loadThreatIntelForRow(row)
      }
    }
  } catch (error) {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

async function loadThreatIntelForRow(row) {
  try {
    const res = await iocApi.getThreatIntel(row.id)
    const list = res.data || []
    if (list.length) {
      const latest = list[0]
      row.threatLevel = latest.threat_level
      row.riskScore = latest.risk_score
    } else {
      row.threatLevel = null
      row.riskScore = null
    }
  } catch (error) {
    row.threatLevel = null
    row.riskScore = null
  }
}

async function handleAdd() {
  if (!addForm.value.ioc_type || !addForm.value.ioc_value) {
    ElMessage.warning('请填写类型和指标值')
    return
  }
  saving.value = true
  try {
    await iocApi.createIoc({
      ioc_type: addForm.value.ioc_type,
      ioc_value: addForm.value.ioc_value.trim(),
      description: addForm.value.description
    })
    ElMessage.success('添加成功')
    showAddDialog.value = false
    addForm.value = { ioc_type: 'ip', ioc_value: '', description: '' }
    loadIocs()
  } catch (error) {
    // handled by interceptor
  } finally {
    saving.value = false
  }
}

async function handleImport() {
  const values = (importForm.value.raw || '')
    .split('\n')
    .map((v) => v.trim())
    .filter((v) => v.length > 0)
  if (values.length === 0) {
    ElMessage.warning('请至少输入一个指标值')
    return
  }
  const items = values.map((v) => ({
    ioc_type: importForm.value.ioc_type,
    ioc_value: v
  }))
  importing.value = true
  try {
    const res = await iocApi.importIocs(items)
    const inserted = res.data?.inserted ?? 0
    ElMessage.success(`导入完成，新增 ${inserted} 条（重复已跳过）`)
    showImportDialog.value = false
    importForm.value = { ioc_type: 'ip', raw: '' }
    loadIocs()
  } catch (error) {
    // handled by interceptor
  } finally {
    importing.value = false
  }
}

async function handleDelete(row) {
  try {
    await iocApi.deleteIoc(row.id)
    ElMessage.success('删除成功')
    loadIocs()
  } catch (error) {
    // handled by interceptor
  }
}

async function handleToggleEnabled(row, val) {
  try {
    await iocApi.updateIoc(row.id, { enabled: val })
    row.enabled = val
    ElMessage.success(val ? '已启用' : '已禁用')
  } catch (error) {
    ElMessage.error('更新启用状态失败')
  }
}

async function handleEnrich(row) {
  if (row.ioc_type !== 'ip' && row.ioc_type !== 'domain') {
    ElMessage.warning('仅支持 ip/domain 类型查询情报')
    return
  }
  row._enriching = true
  try {
    await iocApi.enrichIoc(row.id, {})
    ElMessage.success('查询成功')
    await loadThreatIntelForRow(row)
  } catch (error) {
    // handled by interceptor（含 400/429/500 提示）
  } finally {
    row._enriching = false
  }
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

async function handleBatchEnrich() {
  const ids = enrichableSelection.value.map((r) => r.id)
  if (!ids.length) {
    ElMessage.warning('请选择 IP/域名 类型的 IOC')
    return
  }
  batchLoading.value = true
  try {
    const res = await iocApi.enrichBatch({ ids })
    const d = res.data || {}
    ElMessage.success(
      `批量查询完成：共 ${d.total || 0}，成功 ${d.enriched || 0}，跳过 ${d.skipped || 0}，失败 ${d.failed || 0}`
    )
    await loadIocs()
  } catch (error) {
    // handled by interceptor
  } finally {
    batchLoading.value = false
  }
}

function openDetail(row) {
  detailRow.value = row
  detailTab.value = 'threat'
  showDetailDialog.value = true
}

async function loadDetailThreatIntel() {
  if (!detailRow.value) return
  detailTiLoading.value = true
  detailThreatIntel.value = []
  try {
    const res = await iocApi.getThreatIntel(detailRow.value.id)
    detailThreatIntel.value = res.data || []
  } catch (error) {
    detailThreatIntel.value = []
  } finally {
    detailTiLoading.value = false
  }
}

function typeLabel(type) {
  const map = { ip: 'IP', domain: '域名', url: 'URL', hash: '文件哈希', cert: '证书' }
  return map[type] || type
}

function typeTagType(type) {
  const map = { ip: 'danger', domain: 'warning', url: 'warning', hash: 'primary', cert: 'success' }
  return map[type] || 'info'
}

function threatLevelLabel(level) {
  const map = { high: '高危', medium: '可疑', low: '低危' }
  return map[level] || level || '—'
}

function threatLevelTagType(level) {
  const map = { high: 'danger', medium: 'warning', low: 'info' }
  return map[level] || 'info'
}

function riskScoreTagType(score) {
  const s = Number(score || 0)
  if (s >= 80) return 'danger'
  if (s >= 60) return 'warning'
  if (s > 0) return 'info'
  return 'info'
}

function judgmentTagType(judgment) {
  const map = { malicious: 'danger', suspicious: 'warning', clean: 'success', unknown: 'info' }
  return map[String(judgment).toLowerCase()] || 'info'
}
</script>

<style scoped>
.ioc-view {
  padding: 0;
}
.card-box {
  background: #fff;
  border-radius: 4px;
  padding: 20px;
}
.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mb-12 {
  margin-bottom: 12px;
}
.mb-16 {
  margin-bottom: 16px;
}
.page-title {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
  margin: 0;
}
.muted {
  color: #c0c4cc;
}
.ml {
  margin-left: 12px;
}
.mr {
  margin-right: 6px;
}
.ti-row {
  margin-bottom: 6px;
  font-size: 13px;
  color: #606266;
}
.ti-summary {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  word-break: break-all;
}
.raw-json {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 360px;
  overflow: auto;
}
</style>
