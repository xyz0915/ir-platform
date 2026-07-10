<template>
  <div class="page-container">
    <!-- 案件信息 -->
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">案件详情</h2>
        <el-button @click="$router.push('/')">
          <el-icon><Back /></el-icon> 返回
        </el-button>
      </div>
      <el-descriptions :column="2" border v-loading="loading">
        <el-descriptions-item label="案件名称">{{ caseData?.name }}</el-descriptions-item>
        <el-descriptions-item label="案件编号">{{ caseData?.case_number || '未分配' }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="caseData?.status === 'open' ? 'success' : 'info'" size="small">
            {{ caseData?.status === 'open' ? '进行中' : '已关闭' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ caseData?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">{{ caseData?.description || '无' }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 主机列表 -->
    <div class="card-box">
      <div class="flex-between mb-20">
        <h3>主机列表</h3>
        <div>
          <!-- P2-07: 批量AI分析按钮 -->
          <el-button
            type="warning"
            :disabled="selectedHosts.length < 2 || selectedHosts.length > 5"
            @click="openBatchAnalysis"
          >
            <el-icon><DataAnalysis /></el-icon>
            批量AI分析 ({{ selectedHosts.length }})
          </el-button>
          <el-button type="success" @click="agentDialogRef?.show()">
            <el-icon><Download /></el-icon> 下载 Agent
          </el-button>
          <el-button type="primary" @click="showAddHostDialog">
            <el-icon><Plus /></el-icon> 添加主机
          </el-button>
        </div>
      </div>
      <el-table
        :data="hosts"
        border
        stripe
        v-loading="hostsLoading"
        @selection-change="handleSelectionChange"
        ref="hostTableRef"
      >
        <!-- P2-07: 多选列 -->
        <el-table-column type="selection" width="50" />
        <el-table-column prop="hostname" label="主机名" min-width="120" />
        <el-table-column prop="ip_address" label="IP 地址" width="140" />
        <el-table-column prop="os_type" label="系统类型" width="100" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="agent_version" label="Agent版本" width="100" />
        <el-table-column prop="collection_time" label="采集时间" width="180" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="goToHost(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 添加主机对话框 -->
    <el-dialog v-model="addHostDialogVisible" title="添加主机" width="500px">
      <el-form :model="hostForm" label-width="80px">
        <el-form-item label="主机名" required>
          <el-input v-model="hostForm.hostname" placeholder="请输入主机名" />
        </el-form-item>
        <el-form-item label="IP 地址">
          <el-input v-model="hostForm.ip_address" placeholder="如 192.168.1.100" />
        </el-form-item>
        <el-form-item label="系统类型">
          <el-select v-model="hostForm.os_type" placeholder="选择系统类型">
            <el-option label="Windows" value="windows" />
            <el-option label="Linux" value="linux" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统版本">
          <el-input v-model="hostForm.os_version" placeholder="如 Windows 10 Pro" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addHostDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="handleAddHost">添加</el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- P2-07: 批量AI分析对话框 -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="batchDialogVisible"
      title="批量AI对比分析"
      width="700px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="resetBatchState"
    >
      <!-- 步骤 1：确认 -->
      <div v-if="batchStep === 'confirm'">
        <el-alert type="warning" :closable="false" class="mb-15" show-icon>
          将对选中的 {{ selectedHosts.length }} 台主机进行 AI 对比分析，数据将发送至外部 AI 服务
        </el-alert>

        <div class="batch-host-list mb-20">
          <h4 class="batch-subtitle">已选主机：</h4>
          <el-tag
            v-for="h in selectedHosts"
            :key="h.id"
            type="info"
            size="default"
            class="batch-host-tag"
          >
            {{ h.hostname || `主机 #${h.id}` }}
            <span class="batch-host-ip" v-if="h.ip_address">({{ h.ip_address }})</span>
          </el-tag>
        </div>

        <div class="batch-dimensions mb-20">
          <h4 class="batch-subtitle">对比维度（默认全选）：</h4>
          <el-checkbox-group v-model="batchDimensions" class="batch-checkbox-group">
            <el-checkbox label="risk" border>🛡️ 风险评估对比</el-checkbox>
            <el-checkbox label="threat" border>🔍 威胁模式对比</el-checkbox>
            <el-checkbox label="timeline" border>⏱️ 时间线对比</el-checkbox>
            <el-checkbox label="recommendation" border>💡 处置建议对比</el-checkbox>
          </el-checkbox-group>
        </div>

        <div class="flex-center">
          <el-button @click="batchDialogVisible = false">取消</el-button>
          <el-button type="warning" @click="startBatchAnalysis" :loading="batchLoading">
            开始对比分析
          </el-button>
        </div>
      </div>

      <!-- 步骤 2：流式结果 -->
      <div v-else-if="batchStep === 'streaming'">
        <div class="batch-stream-header mb-10">
          <span class="batch-stream-title">对比分析进行中...</span>
          <el-tag v-if="batchCompareResult" type="success" size="small">已完成</el-tag>
        </div>

        <!-- 进度 -->
        <el-progress
          :percentage="batchProgress"
          :stroke-width="8"
          :status="batchDone ? 'success' : ''"
          :striped="!batchDone"
          :striped-flow="!batchDone"
          class="mb-15"
        />

        <!-- 结构化报告（解析成功） -->
        <template v-if="batchDone && batchReport">
          <el-divider />

          <!-- 总览卡片 -->
          <el-alert type="info" :closable="false" class="mb-15">
            {{ batchReport.overview?.summary }}
          </el-alert>

          <!-- 风险对比 — 表格 + 色条 -->
          <el-card header="🛡️ 风险评估对比" class="mb-15">
            <el-table :data="batchReport.risk_comparison?.hosts || []" size="small">
              <el-table-column prop="hostname" label="主机" />
              <el-table-column prop="risk_level" label="风险等级" width="100">
                <template #default="{ row }">
                  <el-tag
                    :type="row.risk_level === 'critical' ? 'danger' : 'warning'"
                    size="small"
                  >
                    {{ row.risk_level }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="risk_score" label="评分" width="80" />
              <el-table-column prop="analysis" label="分析" min-width="200" show-overflow-tooltip />
            </el-table>
          </el-card>

          <!-- 威胁对比 — 共性列表 + 差异表格 -->
          <el-card header="🔍 威胁模式对比" class="mb-15">
            <div class="mb-10"><strong>共性威胁：</strong></div>
            <el-tag
              v-for="t in batchReport.threat_comparison?.common_threats"
              :key="t"
              class="mr-5 mb-5"
              type="danger"
            >
              {{ t }}
            </el-tag>
            <div v-if="batchReport.threat_comparison?.unique_threats" class="mt-10">
              <strong>差异威胁：</strong>
              <span
                v-if="Object.keys(batchReport.threat_comparison.unique_threats).length === 0"
                class="text-muted"
              >无</span>
              <div
                v-for="(threats, hid) in batchReport.threat_comparison.unique_threats"
                :key="hid"
                class="mt-5"
              >
                <strong>主机 {{ hid }}：</strong>
                <el-tag
                  v-for="t in threats"
                  :key="t"
                  size="small"
                  type="warning"
                  class="ml-5"
                >{{ t }}</el-tag>
              </div>
            </div>
          </el-card>

          <!-- 攻击路径对比 -->
          <el-card header="⏱️ 攻击路径对比" class="mb-15">
            <el-timeline>
              <el-timeline-item
                v-for="p in batchReport.attack_path_comparison?.paths"
                :key="p.host_id"
                :timestamp="p.hostname"
                placement="top"
              >
                <el-card shadow="hover" class="attack-path-card">
                  {{ p.attack_chain || '无攻击链' }}
                </el-card>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </template>

        <!-- 回退：原始 Markdown 渲染（JSON 无法解析时） -->
        <div class="batch-result" v-if="batchCompareResult && !batchReport">
          <div class="batch-result-content markdown-body" v-html="renderBatchMarkdown(batchCompareResult)" />
        </div>

        <!-- 流式进行中的实时展示 -->
        <div class="batch-result" v-if="batchCompareResult && !batchDone">
          <div class="batch-result-content markdown-body" v-html="renderBatchMarkdown(batchCompareResult)" />
        </div>

        <div class="flex-center mt-20">
          <el-button @click="stopBatchStream" :disabled="batchDone" type="danger" plain>
            取消
          </el-button>
          <el-button @click="batchDialogVisible = false" type="primary" :disabled="!batchDone && !batchCompareResult">
            关闭
          </el-button>
        </div>
      </div>
    </el-dialog>

    <AgentDownloadDialog ref="agentDialogRef" />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataAnalysis } from '@element-plus/icons-vue'
import casesApi from '@/api/cases'
import hostsApi from '@/api/hosts'
import { compareHosts, streamCompare } from '@/api/ai'
import { renderMarkdown } from '@/utils/markdown'
import AgentDownloadDialog from '@/components/AgentDownloadDialog.vue'

const route = useRoute()
const router = useRouter()

const caseData = ref(null)
const loading = ref(false)
const hosts = ref([])
const hostsLoading = ref(false)

const addHostDialogVisible = ref(false)
const adding = ref(false)
const hostForm = reactive({
  hostname: '',
  ip_address: '',
  os_type: 'windows',
  os_version: ''
})

const agentDialogRef = ref(null)
const hostTableRef = ref(null)

// ============================================================
// P2-07: 批量AI分析状态
// ============================================================
const selectedHosts = ref([])
const batchDialogVisible = ref(false)
const batchStep = ref('confirm')           // 'confirm' | 'streaming'
const batchDimensions = ref(['risk', 'threat', 'timeline', 'recommendation'])
const batchLoading = ref(false)
const batchProgress = ref(0)
const batchCompareResult = ref('')
const batchDone = ref(false)
const batchReport = ref(null)
let batchStreamController = null

onMounted(() => {
  loadCase()
  loadHosts()
})

async function loadCase() {
  loading.value = true
  try {
    const res = await casesApi.get(route.params.id)
    caseData.value = res.data
  } catch (error) {
    // handled
  } finally {
    loading.value = false
  }
}

async function loadHosts() {
  hostsLoading.value = true
  try {
    const res = await hostsApi.listByCase(route.params.id)
    hosts.value = res.data
  } catch (error) {
    // handled
  } finally {
    hostsLoading.value = false
  }
}

function showAddHostDialog() {
  hostForm.hostname = ''
  hostForm.ip_address = ''
  hostForm.os_type = 'windows'
  hostForm.os_version = ''
  addHostDialogVisible.value = true
}

async function handleAddHost() {
  if (!hostForm.hostname) {
    ElMessage.warning('请输入主机名')
    return
  }
  adding.value = true
  try {
    await hostsApi.create(route.params.id, { ...hostForm })
    ElMessage.success('主机添加成功')
    addHostDialogVisible.value = false
    loadHosts()
  } catch (error) {
    // handled
  } finally {
    adding.value = false
  }
}

function goToHost(id) {
  router.push(`/hosts/${id}`)
}

function statusType(status) {
  const map = {
    pending: 'info',
    imported: 'warning',
    analyzed: 'success'
  }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = {
    pending: '待采集',
    imported: '已导入',
    analyzed: '已分析'
  }
  return map[status] || status
}

// ============================================================
// P2-07: 批量AI分析
// ============================================================
function handleSelectionChange(rows) {
  selectedHosts.value = rows
}

function openBatchAnalysis() {
  if (selectedHosts.value.length < 2) {
    ElMessage.warning('请至少选择 2 台主机')
    return
  }
  if (selectedHosts.value.length > 5) {
    ElMessage.warning('最多选择 5 台主机进行对比分析')
    return
  }
  batchStep.value = 'confirm'
  batchDialogVisible.value = true
}

function resetBatchState() {
  batchStep.value = 'confirm'
  batchDimensions.value = ['risk', 'threat', 'timeline', 'recommendation']
  batchLoading.value = false
  batchProgress.value = 0
  batchCompareResult.value = ''
  batchDone.value = false
  batchReport.value = null
  stopBatchStream()
}

async function startBatchAnalysis() {
  if (batchDimensions.value.length === 0) {
    ElMessage.warning('请至少选择一个对比维度')
    return
  }

  batchLoading.value = true
  try {
    const hostIds = selectedHosts.value.map((h) => Number(h.id))
    const res = await compareHosts(hostIds, batchDimensions.value)
    const taskId = res.data?.task_id || res.task_id

    if (!taskId) {
      ElMessage.error('创建对比任务失败')
      return
    }

    batchStep.value = 'streaming'
    batchProgress.value = 0
    batchCompareResult.value = ''
    batchDone.value = false

    // 启动 SSE 流式获取结果
    batchStreamController = streamCompare(
      taskId,
      // onProgress
      (data) => {
        if (data.progress !== undefined) {
          batchProgress.value = data.progress
        }
        if (data.content) {
          batchCompareResult.value += data.content
        }
      },
      // onComplete
      (data) => {
        batchProgress.value = 100
        batchDone.value = true
        if (data.result) {
          batchCompareResult.value = data.result
          // 尝试解析为结构化报告
          try {
            batchReport.value = typeof data.result === 'string'
              ? JSON.parse(data.result)
              : data.result
          } catch { batchReport.value = null }
        }
      },
      // onError
      (data) => {
        ElMessage.error(data.message || '对比分析失败')
        batchProgress.value = 100
        batchDone.value = true
        if (!batchCompareResult.value) {
          batchCompareResult.value = `> ⚠️ 分析失败：${data.message || '未知错误'}`
        }
        // 尝试解析已有结果为结构化报告
        if (batchCompareResult.value) {
          try {
            batchReport.value = typeof batchCompareResult.value === 'string'
              ? JSON.parse(batchCompareResult.value)
              : batchCompareResult.value
          } catch { batchReport.value = null }
        }
      }
    )
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '提交对比任务失败')
  } finally {
    batchLoading.value = false
  }
}

function stopBatchStream() {
  if (batchStreamController) {
    batchStreamController.abort()
    batchStreamController = null
  }
  batchDone.value = true
}

/** 渲染批量对比结果的 Markdown */
function renderBatchMarkdown(text) {
  if (!text) return ''
  return renderMarkdown(text)
}
</script>

<style scoped>
/* ============================================================
   P2-07: Batch Analysis
   ============================================================ */
.batch-host-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.batch-subtitle {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-fg-default);
  margin: 0 0 8px;
}
.batch-host-tag {
  margin-right: 0;
}
.batch-host-ip {
  font-size: 11px;
  opacity: 0.7;
}

.batch-checkbox-group {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.batch-stream-header {
  display: flex;
  align-items: center;
  gap: 10px;
}
.batch-stream-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.batch-result {
  background: var(--color-canvas-inset);
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  padding: 16px;
  max-height: 50vh;
  overflow-y: auto;
}
.batch-result-content {
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-fg-default);
}

/* Markdown styles for batch result */
.batch-result-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
}
.batch-result-content :deep(th),
.batch-result-content :deep(td) {
  border: 1px solid var(--color-border-default);
  padding: 8px 12px;
  text-align: left;
}
.batch-result-content :deep(th) {
  background: var(--color-canvas-subtle);
  font-weight: 600;
}
.batch-result-content :deep(pre) {
  background: var(--color-code-bg);
  border-radius: 6px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
}
.batch-result-content :deep(code) {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
}
.batch-result-content :deep(h1),
.batch-result-content :deep(h2),
.batch-result-content :deep(h3),
.batch-result-content :deep(h4) {
  margin: 12px 0 6px;
  color: var(--color-fg-default);
}
.batch-result-content :deep(blockquote) {
  border-left: 4px solid var(--color-accent-emphasis);
  padding: 4px 12px;
  color: var(--color-fg-muted);
  background: var(--color-accent-subtle);
  margin: 8px 0;
}

.flex-center {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
}
.mb-10 { margin-bottom: 10px; }
.mb-15 { margin-bottom: 15px; }
.mb-20 { margin-bottom: 20px; }
.mt-5 { margin-top: 5px; }
.mt-10 { margin-top: 10px; }
.mt-20 { margin-top: 20px; }
.mr-5 { margin-right: 5px; }
.ml-5 { margin-left: 5px; }

.text-muted { color: var(--color-fg-muted); }

.attack-path-card {
  font-size: 14px;
  line-height: 1.6;
}
</style>
