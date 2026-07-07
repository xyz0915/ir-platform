<template>
  <el-dialog
    v-model="visible"
    title="AI 一键分析"
    width="700px"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <!-- 确认阶段 -->
    <div v-if="stage === 'confirm'">
      <el-alert type="warning" :closable="false" class="mb-20">
        <strong>⚠️ 数据安全提醒</strong>
        开启 AI 分析后，该主机的取证数据（进程、网络连接、注册表、日志、IOC 等）将发送至您配置的外部 AI 服务进行深度分析。
      </el-alert>

      <div class="confirm-info">
        <h4>将发送以下数据进行分析：</h4>
        <ul>
          <li>主机基础信息（主机名、IP、系统版本）</li>
          <li>本地分析引擎的发现（异常进程、可疑外连、持久化痕迹）</li>
          <li>IOC 命中记录</li>
          <li>攻击时间线事件</li>
          <li>风险评级和分数</li>
        </ul>
      </div>

      <div class="flex-center mt-20">
        <el-button @click="close">取消</el-button>
        <el-button type="warning" @click="handleConfirmAnalyze" :loading="loading">
          确认发送至 AI 分析
        </el-button>
      </div>
    </div>

    <!-- 分析进度阶段 -->
    <div v-if="stage === 'analyzing'" class="center-box">
      <el-icon class="analyzing-icon" :size="48"><Loading /></el-icon>
      <h3>AI 正在分析中...</h3>
      <p class="tip-text">数据已发送至 AI 服务，正在等待分析结果（通常需要 30-60 秒）</p>
    </div>

    <!-- 分析完成阶段 -->
    <div v-if="stage === 'done'">
      <el-alert
        :type="report ? 'success' : 'error'"
        :closable="false"
        class="mb-20"
      >
        {{ report ? 'AI 分析完成' : 'AI 分析失败' }}
      </el-alert>

      <!-- AI报告展示 -->
      <div v-if="report" class="ai-report">
        <div class="report-meta mb-10">
          <el-tag type="info" size="small">模型: {{ report.model_used }}</el-tag>
          <el-tag type="info" size="small">消耗 Token: {{ report.tokens_used }}</el-tag>
          <el-tag size="small">时间: {{ report.created_at }}</el-tag>
        </div>

        <!-- 风险评估 -->
        <div v-if="report.risk_assessment" class="report-section">
          <h4 class="section-title">🛡️ 风险评估</h4>
          <div class="section-content" v-html="formatMarkdown(report.risk_assessment)"></div>
        </div>

        <!-- 威胁分析 -->
        <div v-if="report.threat_analysis" class="report-section">
          <h4 class="section-title">🔍 威胁分析</h4>
          <div class="section-content" v-html="formatMarkdown(report.threat_analysis)"></div>
        </div>

        <!-- 时间线解读 -->
        <div v-if="report.timeline_analysis" class="report-section">
          <h4 class="section-title">⏱️ 时间线解读</h4>
          <div class="section-content" v-html="formatMarkdown(report.timeline_analysis)"></div>
        </div>

        <!-- 处置建议 -->
        <div v-if="report.recommendations" class="report-section">
          <h4 class="section-title">💡 处置建议</h4>
          <div class="section-content" v-html="formatMarkdown(report.recommendations)"></div>
        </div>

        <!-- 完整回复（折叠） -->
        <el-collapse class="mt-10">
          <el-collapse-item title="查看 AI 完整回复">
            <pre class="raw-content">{{ report.raw_response }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- 错误信息 -->
      <div v-else-if="errorMsg" class="error-box">
        <el-alert type="error" :closable="false">{{ errorMsg }}</el-alert>
      </div>

      <div class="flex-center mt-20">
        <el-button @click="close">关闭</el-button>
        <el-button v-if="report" type="danger" @click="handleDelete">删除 AI 报告</el-button>
        <el-button v-if="!report" type="warning" @click="stage = 'confirm'">重新分析</el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiAnalyze, getAiReport, deleteAiReport } from '@/api/ai'

const visible = ref(false)
const stage = ref('confirm') // confirm / analyzing / done
const loading = ref(false)
const report = ref(null)
const errorMsg = ref('')
const hostId = ref(0)

function show(id) {
  hostId.value = id
  stage.value = 'confirm'
  report.value = null
  errorMsg.value = ''
  loading.value = false
  visible.value = true
}

function close() {
  visible.value = false
}

async function handleConfirmAnalyze() {
  stage.value = 'analyzing'
  loading.value = true
  try {
    const res = await aiAnalyze(hostId.value)
    report.value = res.data
    stage.value = 'done'
    ElMessage.success('AI 分析完成')
  } catch (error) {
    if (error.code === 'ECONNABORTED' || (error.message && error.message.includes('timeout'))) {
      errorMsg.value = 'AI 分析超时（请求时间超过 120 秒），请稍后重试或检查 AI 服务 API 地址是否正确'
    } else {
      errorMsg.value = error.response?.data?.message || error.message || 'AI 分析失败，请检查配置'
    }
    stage.value = 'done'
  } finally {
    loading.value = false
  }
}

async function handleDelete() {
  try {
    await ElMessageBox.confirm('确认删除该主机的 AI 分析报告？', '删除确认', { type: 'warning' })
    await deleteAiReport(hostId.value)
    report.value = null
    ElMessage.success('AI 报告已删除')
  } catch {
    // cancelled
  }
}

function formatMarkdown(text) {
  if (!text) return ''
  // Simple markdown-like formatting
  let html = text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.*?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
  return html
}

defineExpose({ show })
</script>

<style scoped>
.confirm-info {
  background: #f5f7fa;
  padding: 15px;
  border-radius: 8px;
}
.confirm-info h4 {
  color: #303133;
  margin-bottom: 10px;
}
.confirm-info ul {
  padding-left: 20px;
  color: #606266;
  line-height: 1.8;
}
.center-box {
  text-align: center;
  padding: 40px 0;
}
.analyzing-icon {
  color: #409EFF;
  animation: spin 1s linear infinite;
}
.tip-text {
  color: #909399;
  margin-top: 10px;
}
.report-section {
  margin-bottom: 15px;
}
.section-title {
  color: #303133;
  margin-bottom: 8px;
  font-size: 15px;
}
.section-content {
  background: #fafafa;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  line-height: 1.8;
  color: #303133;
}
.raw-content {
  background: #f5f5f5;
  padding: 12px;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 13px;
  line-height: 1.6;
  max-height: 400px;
  overflow-y: auto;
}
.error-box {
  padding: 10px;
}
.flex-center {
  display: flex;
  justify-content: center;
  gap: 10px;
}
.mb-20 { margin-bottom: 20px; }
.mb-10 { margin-bottom: 10px; }
.mt-10 { margin-top: 10px; }
.mt-20 { margin-top: 20px; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
