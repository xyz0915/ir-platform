<template>
  <el-dialog
    :model-value="dialogVisible"
    @update:model-value="handleClose"
    :title="dialogTitle"
    :width="dialogWidth"
    :close-on-click-modal="false"
    :close-on-press-escape="stage !== 'analyzing'"
    :show-close="stage !== 'analyzing'"
    destroy-on-close
    class="ai-analysis-dialog"
  >
    <div class="dialog-body">
      <!-- ============================================================ -->
      <!-- 阶段 1：确认 -->
      <!-- ============================================================ -->
      <div v-if="stage === 'confirm'" class="stage-confirm">
        <el-alert type="warning" :closable="false" class="mb-20">
          <template #title>
            <strong>⚠️ 数据安全提醒</strong>
          </template>
          开启 AI 分析后，该主机的取证数据（进程、网络连接、注册表、日志、IOC 等）将发送至您配置的外部 AI 服务进行深度分析。
        </el-alert>

        <div class="confirm-info">
          <div class="confirm-host">
            <span class="confirm-label">分析主机：</span>
            <span class="confirm-value">{{ currentHostName || `主机 #${currentHostId}` }}</span>
          </div>

          <h4 class="mt-15 mb-10">将发送以下数据进行分析：</h4>
          <ul v-if="currentMode === 'module' && currentFocusArea">
            <li>{{ MODULE_DATA_DESC[currentFocusArea] || '模块相关数据' }}</li>
          </ul>
          <ul v-else>
            <li>主机基础信息（主机名、IP、系统版本）</li>
            <li>本地分析引擎的发现（异常进程、可疑外连、持久化痕迹）</li>
            <li>IOC 命中记录</li>
            <li>攻击时间线事件</li>
            <li>风险评级和分数</li>
          </ul>
        </div>

        <div class="confirm-options mt-15">
          <div class="option-row">
            <span class="option-label">脱敏模式：</span>
            <el-switch v-model="maskedMode" active-text="开启" inactive-text="关闭" />
            <span class="option-hint ml-10">开启后 IP、域名等敏感信息将被脱敏处理</span>
          </div>
        </div>

        <div class="flex-center mt-25">
          <el-button @click="handleClose">取消</el-button>
          <el-button type="warning" @click="handleStartAnalysis" :loading="confirmLoading">
            开始 AI 分析
          </el-button>
        </div>
      </div>

      <!-- ============================================================ -->
      <!-- 阶段 2：分析中（流式输出 + 阶段时间线） -->
      <!-- ============================================================ -->
      <div v-if="stage === 'analyzing'" class="stage-analyzing">
        <!-- Token 统计 -->
        <div class="stream-token-bar mb-10">
          <span class="token-item">
            <span class="token-dot prompt"></span>
            输入: {{ formatNumber(store.tokenUsage.prompt) }}
          </span>
          <span class="token-item">
            <span class="token-dot completion"></span>
            输出: {{ formatNumber(store.tokenUsage.completion) }}
          </span>
          <span class="token-item">
            总计: {{ formatNumber(store.tokenUsage.total) }}
          </span>
        </div>

        <!-- 阶段时间线（P2-10） -->
        <div class="stage-timeline mb-15">
          <div class="timeline-header">分析进度</div>
          <div class="timeline-steps">
            <div
              v-for="(s, idx) in allTimelineStages"
              :key="s.stage"
              class="timeline-step"
              :class="{
                'is-completed': s.status === 'completed',
                'is-active': s.status === 'active',
                'is-waiting': s.status === 'wait',
              }"
            >
              <!-- 连接线 -->
              <div v-if="idx > 0" class="step-line" :class="{ filled: s.status !== 'wait' }"></div>
              <!-- 图标区域 -->
              <div class="step-icon-wrapper">
                <div class="step-icon" :class="s.status">
                  <el-icon v-if="s.status === 'completed'" class="step-icon-svg"><CircleCheck /></el-icon>
                  <el-icon v-else-if="s.status === 'active'" class="step-icon-svg is-spinning"><Loading /></el-icon>
                  <span v-else class="step-icon-num">{{ idx + 1 }}</span>
                </div>
                <div class="step-label">{{ s.name }}</div>
                <div class="step-elapsed" v-if="s.elapsed_ms != null">
                  {{ formatElapsed(s.elapsed_ms) }}
                </div>
                <div class="step-elapsed placeholder" v-else-if="s.status === 'active'">
                  进行中...
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 终端风格输出区域 -->
        <div class="terminal-output" ref="terminalRef">
          <div class="terminal-content">
            <pre class="terminal-text">{{ displayedContent }}<span class="cursor-blink">█</span></pre>
          </div>
        </div>

        <!-- 进度条 -->
        <div class="stream-progress mt-15">
          <el-progress
            :percentage="store.taskProgress"
            :stroke-width="8"
            :status="progressStatus"
            :striped="store.taskStatus === 'analyzing'"
            :striped-flow="store.taskStatus === 'analyzing'"
          />
        </div>

        <!-- 取消按钮 -->
        <div class="flex-center mt-20">
          <el-popconfirm
            title="确认取消当前 AI 分析？"
            @confirm="handleCancelAnalysis"
          >
            <template #reference>
              <el-button type="danger" plain>取消分析</el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>

      <!-- ============================================================ -->
      <!-- 阶段 3：完成 -->
      <!-- ============================================================ -->
      <div v-if="stage === 'done'" class="stage-done">
        <!-- 状态提示 -->
        <el-alert
          :type="store.taskStatus === 'completed' ? 'success' : 'error'"
          :closable="false"
          class="mb-20"
        >
          {{ store.taskStatus === 'completed' ? 'AI 分析完成' : errorMessage }}
        </el-alert>

        <!-- 报告展示（成功时） -->
        <div v-if="store.taskStatus === 'completed' && currentReport" class="ai-report">
          <!-- 报告元信息 -->
          <div class="report-meta mb-15">
            <el-tag type="info" size="small" v-if="currentReport.model_used">
              模型: {{ currentReport.model_used }}
            </el-tag>
            <el-tag type="info" size="small" v-if="currentReport.tokens_used">
              消耗 Token: {{ formatNumber(currentReport.tokens_used) }}
            </el-tag>
            <el-tag size="small" v-if="currentReport.created_at">
              时间: {{ formatTime(currentReport.created_at) }}
            </el-tag>
            <span class="ml-10">
              <AudienceToggle v-model="selectedAudience" />
            </span>
          </div>

          <!-- v1.3.0 BugFix: 受众切换驱动条件渲染 -->
          <div v-if="hasAudienceContent" class="audience-section mb-15">
            <!-- 技术受众视图 -->
            <div v-if="selectedAudience === 'technical' || selectedAudience === 'both'" class="audience-panel technical">
              <div class="audience-panel-header">🔧 技术视图</div>
              <div v-if="techCommands.length" class="audience-block">
                <div class="audience-block-title">可执行命令</div>
                <pre class="audience-code" v-for="(cmd, i) in techCommands" :key="'cmd-'+i">{{ cmd }}</pre>
              </div>
              <div v-if="techIocs.length" class="audience-block">
                <div class="audience-block-title">IOC 清单</div>
                <el-tag v-for="(ioc, i) in techIocs" :key="'ioc-'+i" size="small" effect="plain" class="mr-5 mb-5">{{ ioc }}</el-tag>
              </div>
              <div v-if="techScripts.length" class="audience-block">
                <div class="audience-block-title">处置脚本</div>
                <pre class="audience-code" v-for="(scr, i) in techScripts" :key="'scr-'+i">{{ scr }}</pre>
              </div>
            </div>
            <!-- 管理层视图 -->
            <div v-if="selectedAudience === 'executive' || selectedAudience === 'both'" class="audience-panel executive">
              <div class="audience-panel-header">📊 管理层视图</div>
              <div v-if="execImpact" class="audience-block">
                <div class="audience-block-title">业务影响</div>
                <p class="audience-text">{{ execImpact }}</p>
              </div>
              <div v-if="execRecommendations" class="audience-block">
                <div class="audience-block-title">建议措施</div>
                <p class="audience-text">{{ execRecommendations }}</p>
              </div>
              <div v-if="execBusinessLanguage" class="audience-block">
                <div class="audience-block-title">业务语言摘要</div>
                <p class="audience-text">{{ execBusinessLanguage }}</p>
              </div>
            </div>
          </div>

          <div class="structured-grid mb-15">
            <InputQualityPanel
              :quality="parsedRiskAssessment.input_quality || {}"
              :suggestions="parsedRecommendations.input_suggestions || []"
            />
            <CoverageGapPanel
              :gaps="parsedRiskAssessment.coverage_gaps || []"
              :miss-risk="parsedRiskAssessment.miss_risk || {}"
            />
            <EvidenceTracePanel :evidence-trace="parsedThreatAnalysis.evidence_trace || {}" />
            <StructuredTimelinePanel :timeline="parsedTimelineAnalysis" />
          </div>

          <!-- v1.3.0 作战化：风险结论卡 + 稀有高危卡 -->
          <div class="ops-grid mb-15">
            <RiskConclusionCard
              :risk-assessment="parsedRiskAssessment"
              :escalation-conditions="parsedEscalation"
              @toggle-escalation="onToggleEscalation"
            />
            <RareSignalCard v-if="parsedRareSignals.length" :rare-signals="parsedRareSignals" />
          </div>

          <!-- v1.3.0 作战化：ATT&CK 矩阵 + 攻击链叙述 -->
          <div class="mb-15">
            <AttckMatrix
              :mitre-attack="parsedMitreAttack"
              :attack-chain-hits="parsedAttackChainHits"
            />
          </div>
          <div class="mb-15">
            <AttackChainNarrative :attack-chain-hits="parsedAttackChainHits" />
          </div>

          <!-- v1.3.0 作战化：缺口即动作（可派发只读采集） -->
          <div class="mb-15">
            <DataGapActionCard
              :data-gaps="parsedDataGaps"
              :host-id="currentHostId"
              @dispatched="onDispatched"
            />
          </div>

          <DeepDiveQuestionPanel
            class="mb-15"
            :questions="parsedRecommendations.recommended_questions || []"
            @select="handleSelectRecommendedQuestion"
          />

          <!-- Markdown 渲染报告 — 折叠面板 -->
          <el-collapse v-model="activeCollapse" class="report-collapse">
            <el-collapse-item
              v-if="hasReadableSection(currentReport.risk_assessment)"
              title="🛡️ 风险评估"
              name="risk"
            >
              <div class="report-content markdown-body" v-html="renderMarkdown(getReadableSectionContent(currentReport.risk_assessment))" />
            </el-collapse-item>

            <el-collapse-item
              v-if="hasReadableSection(currentReport.threat_analysis)"
              title="🔍 威胁分析"
              name="threat"
            >
              <div class="report-content markdown-body" v-html="renderMarkdown(getReadableSectionContent(currentReport.threat_analysis))" />
            </el-collapse-item>

            <el-collapse-item
              v-if="hasReadableSection(currentReport.timeline_analysis)"
              title="⏱️ 时间线解读"
              name="timeline"
            >
              <div class="report-content markdown-body" v-html="renderMarkdown(getReadableSectionContent(currentReport.timeline_analysis))" />
            </el-collapse-item>

            <el-collapse-item
              v-if="hasReadableSection(currentReport.recommendations)"
              title="💡 处置建议"
              name="recommendations"
            >
              <div class="report-content markdown-body" v-html="renderMarkdown(getReadableSectionContent(currentReport.recommendations))" />
            </el-collapse-item>

            <el-collapse-item
              v-if="currentReport.raw_response"
              title="📄 完整回复"
              name="raw"
            >
              <pre class="raw-content">{{ currentReport.raw_response }}</pre>
            </el-collapse-item>
          </el-collapse>

          <!-- 操作按钮区 -->
          <div class="report-actions mt-20">
            <el-button type="warning" @click="handleReanalyze">重新分析</el-button>
            <el-button type="primary" @click="handleExportPdf" :loading="exportLoading">
              导出 PDF
            </el-button>
            <el-select
              v-model="selectedVersion"
              placeholder="历史版本"
              class="version-select ml-10"
              @change="handleSwitchVersion"
              :loading="versionLoading"
              @visible-change="onVersionSelectVisible"
            >
              <el-option
                v-for="v in reportVersions"
                :key="v.version || v.id"
                :label="v.label || `版本 ${v.version}`"
                :value="v.version || v.id"
              />
            </el-select>
            <el-tooltip content="脱敏模式仅在确认阶段可修改" placement="top">
              <span class="masked-hint ml-10">
                脱敏：{{ maskedMode ? '开启' : '关闭' }}
              </span>
            </el-tooltip>
          </div>
        </div>

        <!-- 错误信息 -->
        <div v-else class="error-section">
          <div class="flex-center mt-20">
            <el-button @click="handleClose">关闭</el-button>
            <el-button type="warning" @click="stage = 'confirm'">重新分析</el-button>
          </div>
        </div>

        <!-- ============================================================ -->
        <!-- P2-01：多轮对话 UI -->
        <!-- ============================================================ -->
        <div v-if="store.taskStatus === 'completed'" class="follow-up-section mt-20">
          <div class="chat-header">
            <span class="chat-title">💬 追问分析</span>
            <span v-if="chatMessages.length > 0" class="chat-round-badge">
              第 {{ chatRoundCount }} 轮
            </span>
          </div>

          <!-- 对话消息列表 -->
          <div class="chat-messages" ref="chatMessagesRef" v-if="chatMessages.length > 0">
            <div
              v-for="(msg, idx) in chatMessages"
              :key="idx"
              class="chat-message-row"
              :class="msg.role"
            >
              <div class="chat-bubble" :class="msg.role">
                <div class="chat-bubble-role">{{ msg.role === 'user' ? '👤 我' : '🤖 AI' }}</div>
                <div class="chat-bubble-content">{{ msg.content }}</div>
                <div class="chat-bubble-time">{{ msg.time }}</div>
              </div>
            </div>
            <!-- 加载中气泡 -->
            <div v-if="chatLoading" class="chat-message-row assistant">
              <div class="chat-bubble assistant typing-bubble">
                <span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>
              </div>
            </div>
          </div>

          <!-- 追问输入框 -->
          <div class="follow-up-bar mt-10">
            <el-input
              v-model="followUpText"
              placeholder="对分析结果进行追问..."
              :disabled="chatLoading || chatRoundCount >= 5"
              class="follow-up-input"
              @keyup.enter="handleFollowUp"
            >
              <template #append>
                <el-button
                  @click="handleFollowUp"
                  :loading="chatLoading"
                  :disabled="!followUpText.trim() || chatRoundCount >= 5"
                >
                  {{ chatRoundCount >= 5 ? '建议新建分析' : '发送' }}
                </el-button>
              </template>
            </el-input>
          </div>

          <!-- 轮数上限提示 -->
          <div v-if="chatRoundCount >= 5" class="mt-10">
            <el-alert type="info" :closable="false" show-icon>
              已达到对话轮数上限，建议
              <el-button type="warning" link size="small" @click="handleReanalyze">新建分析</el-button>
              以获取更准确的结果
            </el-alert>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, Loading } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { exportAiReportPdf, getAiReportByVersion, chatWithAi } from '@/api/ai'
import { useAiStore } from '@/stores/ai'
import { renderMarkdown } from '@/utils/markdown'
import InputQualityPanel from '@/components/ai/InputQualityPanel.vue'
import EvidenceTracePanel from '@/components/ai/EvidenceTracePanel.vue'
import StructuredTimelinePanel from '@/components/ai/StructuredTimelinePanel.vue'
import CoverageGapPanel from '@/components/ai/CoverageGapPanel.vue'
import DeepDiveQuestionPanel from '@/components/ai/DeepDiveQuestionPanel.vue'
// v1.3.0 作战化：风险结论 / 缺口动作 / 稀有信号 / 攻击链 / 受众 / ATT&CK 矩阵
import RiskConclusionCard from '@/components/ai/RiskConclusionCard.vue'
import DataGapActionCard from '@/components/ai/DataGapActionCard.vue'
import RareSignalCard from '@/components/ai/RareSignalCard.vue'
import AttackChainNarrative from '@/components/ai/AttackChainNarrative.vue'
import AudienceToggle from '@/components/ai/AudienceToggle.vue'
import AttckMatrix from '@/components/ai/AttckMatrix.vue'
import { getDispatchStatus } from '@/api/dispatch'

const store = useAiStore()

// ============================================================
// Props & Emits
// ============================================================
const props = defineProps({
  hostId: { type: [Number, String], default: null },
  visible: { type: Boolean, default: false },
  hostName: { type: String, default: '' },
  mode: { type: String, default: 'standard' },
  focusArea: { type: String, default: null },
})

const emit = defineEmits(['close', 'update:visible'])

const dialogVisible = ref(false)
const currentHostId = ref(null)
const currentHostName = ref('')
const currentMode = ref('standard')
const currentFocusArea = ref(null)

// ── 模块中文名映射 ──
const MODULE_NAME_MAP = {
  profile: '主机画像',
  process_list: '进程树',
  abnormal_processes: '异常进程',
  connections: '可疑外连',
  persistence: '持久化痕迹',
  startup: '可疑启动项',
  ioc: 'IOC 命中',
  timeline: '时间线',
  users: '用户账户',
  services: '系统服务',
  usb: 'USB 记录',
  remote_control: '远程工具',
}

// ── 模块发送数据描述 ──
const MODULE_DATA_DESC = {
  profile: '主机基础信息、分析结果摘要、系统画像',
  process_list: '进程列表（含进程名、PID、路径、命令行、父子关系）',
  abnormal_processes: '异常进程详情（含进程名、路径、命令行、可疑原因、严重度）',
  connections: '可疑外连记录（含远程地址、端口、协议、关联进程）',
  persistence: '持久化痕迹（含类型、名称、命令、位置、可疑标记）',
  startup: '可疑启动项（含名称、命令、位置、类型、可疑原因）',
  ioc: 'IOC 命中记录（含类型、值、匹配位置、上下文、严重度）',
  timeline: '安全事件时间线（含时间戳、事件类型、描述、严重度）',
  users: '用户账户信息（含用户名、权限、组成员关系）',
  services: '系统服务列表（含服务名、状态、二进制路径）',
  usb: 'USB 设备接入记录（含设备名、序列号、接入时间）',
  remote_control: '远程控制工具痕迹（含工具名、执行时间、网络连接）',
}

// ============================================================
// Stage 状态
// ============================================================
const stage = ref('confirm')       // 'confirm' | 'analyzing' | 'done'
const confirmLoading = ref(false)
const maskedMode = ref(true)
const errorMessage = ref('')

// ============================================================
// 流式输出显示
// ============================================================
const terminalRef = ref(null)
const displayedContent = ref('')
let typingTimer = null
let displayedLength = 0

// ============================================================
// 报告展示
// ============================================================
const currentReport = ref(null)
const activeCollapse = ref(['risk', 'threat', 'timeline', 'recommendations'])
const exportLoading = ref(false)
const reportVersions = ref([])
const versionLoading = ref(false)
const selectedVersion = ref('')

// ============================================================
// P2-10: 阶段时间线
// ============================================================
const PREDEFINED_STAGES = [
  { stage: 'assembling', name: '数据组装', icon: 'data-board' },
  { stage: 'building', name: 'Prompt构建', icon: 'document' },
  { stage: 'calling', name: 'LLM调用中', icon: 'cpu' },
  { stage: 'parsing', name: '结果解析', icon: 'reading' },
  { stage: 'saving', name: '保存报告', icon: 'folder-checked' },
]

const allTimelineStages = computed(() => {
  const timeline = store.stageTimeline
  const currentStage = store.taskStage
  const isDone = store.taskStatus === 'completed'

  return PREDEFINED_STAGES.map((s, i) => {
    const entry = timeline.find((t) => t.stage === s.stage)
    let status = 'wait'

    if (entry) {
      if (entry.active && !isDone) {
        status = 'active'
      } else {
        status = 'completed'
      }
    } else if (isDone) {
      // 分析完成，所有阶段标记完成
      const currentIdx = PREDEFINED_STAGES.findIndex((st) => st.stage === currentStage)
      if (currentIdx >= i) {
        status = 'completed'
      }
    }

    return {
      ...s,
      status,
      index: i + 1,
      elapsed_ms: entry?.elapsed_ms ?? null,
    }
  })
})

// ============================================================
// P2-01: 多轮对话
// ============================================================
const followUpText = ref('')
const chatMessages = ref([])       // { role: 'user'|'assistant', content, time }
const chatLoading = ref(false)
const chatMessagesRef = ref(null)
const conversationId = ref(null)

const chatRoundCount = computed(() => {
  // 每对 user+assistant 为一轮
  return Math.ceil(chatMessages.value.filter((m) => m.role === 'user').length)
})

// ============================================================
// Computed
// ============================================================
const dialogTitle = computed(() => {
  if (currentMode.value === 'module' && currentFocusArea.value) {
    const moduleName = MODULE_NAME_MAP[currentFocusArea.value] || currentFocusArea.value
    switch (stage.value) {
      case 'confirm': return `AI 分析 — ${moduleName}`
      case 'analyzing': return `AI 正在分析 — ${moduleName}`
      case 'done':
        return store.taskStatus === 'completed'
          ? `AI 分析完成 — ${moduleName}`
          : `AI 分析失败 — ${moduleName}`
      default: return `AI 分析 — ${moduleName}`
    }
  }
  switch (stage.value) {
    case 'confirm': return 'AI 一键分析'
    case 'analyzing': return 'AI 正在分析中...'
    case 'done':
      return store.taskStatus === 'completed' ? 'AI 分析完成' : 'AI 分析失败'
    default: return 'AI 一键分析'
  }
})

const dialogWidth = computed(() => {
  switch (stage.value) {
    case 'confirm': return '650px'
    case 'analyzing': return '800px'
    case 'done': return '900px'
    default: return '700px'
  }
})

const progressStatus = computed(() => {
  if (store.taskStatus === 'completed') return 'success'
  if (store.taskStatus === 'error') return 'exception'
  return ''
})

const parsedRiskAssessment = computed(() => parseMaybeJson(currentReport.value?.risk_assessment))
const parsedThreatAnalysis = computed(() => parseMaybeJson(currentReport.value?.threat_analysis))
const parsedTimelineAnalysis = computed(() => parseMaybeJson(currentReport.value?.timeline_analysis))
const parsedRecommendations = computed(() => parseMaybeJson(currentReport.value?.recommendations))

// v1.3.0 作战化：解析后端返回的新列（已结构化，parseMaybeJson 兜底）
// BugFix: 优先使用 API 层提取的顶层 data_gaps，回退到 risk_assessment 内嵌
const parsedDataGaps = computed(() => {
  const topLevel = currentReport.value?.data_gaps
  if (Array.isArray(topLevel) && topLevel.length) return topLevel
  return parsedRiskAssessment.value?.data_gaps || []
})
const parsedEscalation = computed(() => parsedRiskAssessment.value?.escalation_conditions || [])
const parsedMitreAttack = computed(() => parseMaybeJson(currentReport.value?.mitre_attack) || [])
const parsedRareSignals = computed(() => parseMaybeJson(currentReport.value?.rare_high_signals) || [])
const parsedAttackChainHits = computed(() => parseMaybeJson(currentReport.value?.attack_chain_hits) || [])
const parsedAudience = computed(() => parseMaybeJson(currentReport.value?.audience) || 'both')
// v1.3.0 BugFix: 受众切换驱动条件渲染 — 从 parsedAudience 提取技术/管理层内容
const techCommands = computed(() => {
  if (typeof parsedAudience.value === 'object' && parsedAudience.value.technical) {
    return parsedAudience.value.technical.commands || []
  }
  return []
})
const techIocs = computed(() => {
  if (typeof parsedAudience.value === 'object' && parsedAudience.value.technical) {
    return parsedAudience.value.technical.iocs || []
  }
  return []
})
const techScripts = computed(() => {
  if (typeof parsedAudience.value === 'object' && parsedAudience.value.technical) {
    return parsedAudience.value.technical.scripts || []
  }
  return []
})
const execImpact = computed(() => {
  if (typeof parsedAudience.value === 'object' && parsedAudience.value.executive) {
    return parsedAudience.value.executive.impact || ''
  }
  return ''
})
const execRecommendations = computed(() => {
  if (typeof parsedAudience.value === 'object' && parsedAudience.value.executive) {
    return parsedAudience.value.executive.recommendations || ''
  }
  return ''
})
const execBusinessLanguage = computed(() => {
  if (typeof parsedAudience.value === 'object' && parsedAudience.value.executive) {
    return parsedAudience.value.executive.business_language || ''
  }
  return ''
})
const hasAudienceContent = computed(() => {
  return techCommands.value.length > 0 || techIocs.value.length > 0 || techScripts.value.length > 0 ||
    execImpact.value || execRecommendations.value || execBusinessLanguage.value
})
// v1.3.0：受众切换（默认双受众，前端默认 technical 由主理人决策④）
const selectedAudience = ref('both')

// ============================================================
// 监听 visible，重置状态
// ============================================================
watch(
  () => dialogVisible.value,
  (val) => {
    if (val) {
      resetState()
    } else {
      cleanup()
    }
  }
)

// ============================================================
// 打字机效果：监听 streamContent
// ============================================================
watch(
  () => store.streamContent,
  () => {
    if (stage.value !== 'analyzing') return
    startTypingEffect()
  }
)

// ============================================================
// 监听任务完成
// ============================================================
watch(
  () => store.taskStatus,
  (status) => {
    // 取消状态由 handleCancelAnalysis 主动处理，不通过 watch 跳转 done，
    // 否则与 resetState() 的 stage='confirm' 产生竞态
    if (status === 'cancelled') {
      stopTypingEffect()
      return
    }
    if (status === 'completed' || status === 'error') {
      stopTypingEffect()
      // 显示全部已接收内容
      displayedContent.value = store.streamContent
      if (status === 'completed') {
        loadReport()
      }
      if (status === 'error') {
        errorMessage.value = store.taskStage || 'AI 分析过程出错'
      }
      stage.value = 'done'
    }
  }
)

// ============================================================
// 监听关闭
// ============================================================
function handleClose() {
  if (stage.value === 'analyzing') return  // 分析中不允许关闭
  cleanup()
  dialogVisible.value = false
  emit('close')
  emit('update:visible', false)
}

// ============================================================
// 重置状态
// ============================================================
function resetState() {
  stage.value = 'confirm'
  confirmLoading.value = false
  maskedMode.value = true
  errorMessage.value = ''
  displayedContent.value = ''
  displayedLength = 0
  currentReport.value = null
  reportVersions.value = []
  selectedVersion.value = ''
  followUpText.value = ''
  chatMessages.value = []
  conversationId.value = null
  currentMode.value = 'standard'
  currentFocusArea.value = null
  store.resetStream()
}

// ============================================================
// 清理资源
// ============================================================
function cleanup() {
  stopTypingEffect()
  if (store.isAnalyzing) {
    store.cancelAnalysis()
  }
}

onBeforeUnmount(() => {
  cleanup()
})

function show(hostId, hostName = '', mode = 'standard', focusArea = null) {
  currentHostId.value = hostId
  currentHostName.value = hostName || ''
  currentMode.value = mode || 'standard'
  currentFocusArea.value = focusArea || null
  dialogVisible.value = true
  stage.value = 'confirm'
}

defineExpose({ show })

// ============================================================
// 阶段 1 → 2：开始分析
// ============================================================
async function handleStartAnalysis() {
  confirmLoading.value = true
  try {
    const taskId = await store.startAnalysis(currentHostId.value, maskedMode.value ? 1 : 0, {
      mode: currentMode.value,
      focusArea: currentFocusArea.value,
      audience: selectedAudience.value,
    })
    stage.value = 'analyzing'
    displayedContent.value = ''
    displayedLength = 0

    // 启动流式连接（非阻塞）
    store.connectStream(taskId).catch((err) => {
      console.error('[AiAnalysis] Stream error:', err)
    })
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '提交分析任务失败')
  } finally {
    confirmLoading.value = false
  }
}

// ============================================================
// 打字机效果
// ============================================================
function startTypingEffect() {
  if (typingTimer) return
  typingTimer = setInterval(() => {
    const fullText = store.streamContent
    if (displayedLength < fullText.length) {
      // 每次多显示 1~3 个字符
      const increment = Math.max(1, Math.floor(Math.random() * 3) + 1)
      displayedLength = Math.min(displayedLength + increment, fullText.length)
      displayedContent.value = fullText.slice(0, displayedLength)
      scrollTerminalToBottom()
    }
  }, 30)
}

function stopTypingEffect() {
  if (typingTimer) {
    clearInterval(typingTimer)
    typingTimer = null
  }
  // 显示全部
  if (store.streamContent) {
    displayedContent.value = store.streamContent
    displayedLength = store.streamContent.length
  }
  scrollTerminalToBottom()
}

function scrollTerminalToBottom() {
  nextTick(() => {
    const el = terminalRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

// ============================================================
// 取消分析
// ============================================================
async function handleCancelAnalysis() {
  stopTypingEffect()
  await store.cancelAnalysis()
  errorMessage.value = '分析已被取消'
  resetState()
  stage.value = 'confirm'
}

// ============================================================
// 阶段 3：加载报告
// ============================================================
async function loadReport() {
  try {
    const cachedReport = store.reportData
    if (cachedReport) {
      currentReport.value = cachedReport
    } else {
      const report = await store.fetchReport(currentHostId.value)
      currentReport.value = report
    }

    if (currentReport.value) {
      activeCollapse.value = ['risk', 'threat', 'timeline', 'recommendations']
      if (currentReport.value.conversation_id) {
        conversationId.value = currentReport.value.conversation_id
      }
    }
  } catch {
    currentReport.value = store.reportData || null
  }
}

// ============================================================
// 重新分析
// ============================================================
function handleReanalyze() {
  resetState()
  stage.value = 'confirm'
}

// v1.3.0 作战化：可证伪升级条件勾选（仅前端推演，提示可复核）
function onToggleEscalation(ec) {
  ElMessage.info(`升级条件已勾选：${ec.condition} → ${ec.if_true}`)
}

// v1.3.0 作战化：只读派发回填轮询（绝不自动处置，仅回填证据）
function onDispatched({ taskId }) {
  if (!taskId) return
  const timer = setInterval(async () => {
    try {
      const res = await getDispatchStatus(taskId)
      const data = res.data?.data || {}
      if (data.status && data.status !== 'running') {
        clearInterval(timer)
        if (data.status === 'completed' || data.status === 'timeout') {
          ElMessage.success(`只读采集完成（${data.status}），证据已回填，可刷新报告查看`)
        } else {
          ElMessage.warning(`只读采集结束（${data.status}）`)
        }
      }
    } catch (e) {
      clearInterval(timer)
      ElMessage.error(e?.response?.data?.message || '派发状态查询失败')
    }
  }, 2000)
  // 安全上限：130s 后停止轮询（后端超时 120s）
  setTimeout(() => clearInterval(timer), 130000)
}

// ============================================================
// 导出 PDF
// ============================================================
async function handleExportPdf() {
  exportLoading.value = true
  try {
    const res = await exportAiReportPdf(currentHostId.value)
    // 创建 Blob 下载
    const blob = new Blob([res], { type: 'application/pdf' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `AI_Report_${currentHostId.value}_${dayjs().format('YYYYMMDDHHmmss')}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('PDF 导出成功')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '导出失败')
  } finally {
    exportLoading.value = false
  }
}

// ============================================================
// 历史版本
// ============================================================
async function onVersionSelectVisible(visible) {
  if (visible && reportVersions.value.length === 0) {
    versionLoading.value = true
    try {
      const versions = await store.fetchReportVersions(currentHostId.value)
      reportVersions.value = versions.map((v) => ({
        ...v,
        label: `v${v.version} - ${dayjs(v.created_at).format('MM-DD HH:mm')}`,
      }))
    } catch {
      reportVersions.value = []
    } finally {
      versionLoading.value = false
    }
  }
}

async function handleSwitchVersion(version) {
  versionLoading.value = true
  try {
    const res = await getAiReportByVersion(currentHostId.value, version)
    currentReport.value = res.data
  } catch (e) {
    ElMessage.error('加载历史版本失败')
  } finally {
    versionLoading.value = false
  }
}

// ============================================================
// P2-01：多轮对话处理
// ============================================================
async function handleFollowUp(options = {}) {
  const text = (options.question || followUpText.value).trim()
  if (!text) return
  if (chatLoading.value) return

  // 添加用户消息
  chatMessages.value.push({
    role: 'user',
    content: text,
    time: dayjs().format('HH:mm:ss'),
  })
  followUpText.value = ''
  scrollChatToBottom()

  chatLoading.value = true
  try {
    const payload = {
      message: text,
      mode: options.mode || 'follow_up',
      focus_area: options.focusArea || null,
      base_report_id: currentReport.value?.id || null,
    }
    if (conversationId.value) {
      payload.conversation_id = conversationId.value
    }
    const res = await chatWithAi(currentHostId.value, payload)
    const data = res.data || res

    // 记录 conversation_id（首次）
    if (data.conversation_id && !conversationId.value) {
      conversationId.value = data.conversation_id
    }

    // 添加 AI 回复
    chatMessages.value.push({
      role: 'assistant',
      content: data.reply || data.message || data.content || '(无回复)',
      time: dayjs().format('HH:mm:ss'),
    })
  } catch (e) {
    const errMsg = e?.response?.data?.message || e?.message || '追问失败'
    chatMessages.value.push({
      role: 'assistant',
      content: `⚠️ ${errMsg}`,
      time: dayjs().format('HH:mm:ss'),
    })
    ElMessage.error(errMsg)
  } finally {
    chatLoading.value = false
    scrollChatToBottom()
  }
}

function scrollChatToBottom() {
  nextTick(() => {
    const el = chatMessagesRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

function handleSelectRecommendedQuestion(item) {
  handleFollowUp({
    question: item.question,
    mode: 'deep_dive',
    focusArea: item.focus_area,
  })
}

function parseMaybeJson(value) {
  if (!value) return {}
  if (typeof value === 'object') return value
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return { raw_analysis: value }
    }
  }
  return {}
}

function getReadableSectionContent(value) {
  if (!value) return ''
  if (typeof value === 'string') {
    const parsed = parseMaybeJson(value)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return getReadableSectionContent(parsed)
    }
    return value
  }
  if (typeof value !== 'object' || Array.isArray(value)) {
    return String(value || '')
  }

  const preferredKeys = [
    'raw_analysis',
    'risk_summary',
    'summary',
    'timeline_summary',
    'attack_chain',
    'attack_vector',
    'ioc_interpretation',
    'evidence_insufficiency',
    'remediation_priority',
  ]

  const lines = []
  for (const key of preferredKeys) {
    const field = value[key]
    if (typeof field === 'string' && field.trim()) {
      lines.push(field.trim())
    }
  }

  for (const [key, field] of Object.entries(value)) {
    if (preferredKeys.includes(key) || field === null || field === undefined) continue
    if (typeof field === 'string' && field.trim()) {
      lines.push(`**${formatSectionKey(key)}**\n${field.trim()}`)
    } else if (Array.isArray(field) && field.length) {
      const items = field
        .map((item) => {
          if (typeof item === 'string') return `- ${item}`
          if (item && typeof item === 'object') {
            return `- ${Object.values(item).filter(Boolean).join(' | ')}`
          }
          return ''
        })
        .filter(Boolean)
      if (items.length) {
        lines.push(`**${formatSectionKey(key)}**\n${items.join('\n')}`)
      }
    }
  }

  return lines.join('\n\n').trim()
}

function hasReadableSection(value) {
  return Boolean(getReadableSectionContent(value))
}

function formatSectionKey(key) {
  return String(key)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

// ============================================================
// 工具函数
// ============================================================
function formatNumber(n) {
  if (n == null) return '0'
  return Number(n).toLocaleString()
}

function formatTime(t) {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

/** 格式化阶段耗时（毫秒 → 可读文本） */
function formatElapsed(ms) {
  if (ms == null || ms < 0) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const mins = Math.floor(ms / 60000)
  const secs = ((ms % 60000) / 1000).toFixed(0)
  return `${mins}m${secs}s`
}
</script>

<style scoped>
/* ============================================================
   Stage: Confirm
   ============================================================ */
.confirm-info {
  background: #f5f7fa;
  padding: 16px;
  border-radius: 8px;
}
.confirm-host {
  display: flex;
  align-items: center;
  gap: 6px;
}
.confirm-label {
  font-size: 14px;
  color: #606266;
}
.confirm-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.confirm-info h4 {
  color: #303133;
  font-size: 14px;
}
.confirm-info ul {
  padding-left: 20px;
  color: #606266;
  line-height: 1.8;
  margin: 0;
}
.confirm-options {
  padding: 12px;
  background: #fafafa;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.option-row {
  display: flex;
  align-items: center;
}
.option-label {
  font-size: 14px;
  color: #606266;
  margin-right: 8px;
}
.option-hint {
  font-size: 12px;
  color: #909399;
}

/* ============================================================
   P2-10: Stage Timeline
   ============================================================ */
.stage-timeline {
  background: #f9fafb;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 20px;
}
.timeline-header {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e4e7ed;
}
.timeline-steps {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  position: relative;
}
.timeline-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  position: relative;
  transition: opacity 0.3s ease;
}
.timeline-step.is-waiting {
  opacity: 0.45;
}
.step-line {
  position: absolute;
  top: 16px;
  right: 50%;
  width: 100%;
  height: 2px;
  background: #e4e7ed;
  z-index: 0;
  transition: background 0.4s ease;
}
.step-line.filled {
  background: #409eff;
}
.step-icon-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  z-index: 1;
  gap: 4px;
}
.step-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
.step-icon.completed {
  background: #67c23a;
  color: #fff;
}
.step-icon.active {
  background: #409eff;
  color: #fff;
  box-shadow: 0 0 0 4px rgba(64, 158, 255, 0.2);
  animation: pulse-ring 1.5s ease-in-out infinite;
}
.step-icon.wait {
  background: #e4e7ed;
  color: #909399;
}
.step-icon-num {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
}
.step-icon-svg {
  font-size: 16px;
}
.is-spinning {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes pulse-ring {
  0%, 100% { box-shadow: 0 0 0 4px rgba(64, 158, 255, 0.2); }
  50% { box-shadow: 0 0 0 8px rgba(64, 158, 255, 0.08); }
}
.step-label {
  font-size: 11px;
  color: #606266;
  white-space: nowrap;
  margin-top: 4px;
  transition: color 0.3s;
}
.timeline-step.is-active .step-label {
  color: #409eff;
  font-weight: 600;
}
.timeline-step.is-completed .step-label {
  color: #67c23a;
}
.step-elapsed {
  font-size: 10px;
  color: #909399;
  white-space: nowrap;
  margin-top: 2px;
}
.step-elapsed.placeholder {
  color: #409eff;
  font-style: italic;
}

/* ============================================================
   Stage: Analyzing (Terminal)
   ============================================================ */
.stream-token-bar {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: #606266;
}
.token-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.token-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.token-dot.prompt {
  background: #409eff;
}
.token-dot.completion {
  background: #67c23a;
}

.terminal-output {
  background: #1e1e1e;
  border-radius: 8px;
  padding: 16px;
  min-height: 200px;
  max-height: 280px;
  overflow-y: auto;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 14px;
  line-height: 1.7;
}
.terminal-content {
  color: #d4d4d4;
}
.terminal-text {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  color: #d4d4d4;
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
}
.cursor-blink {
  color: #4ec94e;
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.stream-progress {
  padding: 0 4px;
}

/* ============================================================
   Stage: Done
   ============================================================ */
.ai-report {
  max-height: 60vh;
  overflow-y: auto;
  padding-right: 4px;
}
.structured-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.report-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.report-collapse {
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.report-content {
  padding: 8px 0;
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
}
.raw-content {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 13px;
  line-height: 1.6;
  max-height: 400px;
  overflow-y: auto;
  font-family: Consolas, 'Courier New', monospace;
}

.report-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.version-select {
  width: 180px;
}
.masked-hint {
  font-size: 13px;
  color: #909399;
}

.error-section {
  padding: 20px;
  text-align: center;
}

/* ============================================================
   P2-01: Multi-turn Chat
   ============================================================ */
.follow-up-section {
  border-top: 1px solid #ebeef5;
  padding-top: 16px;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.chat-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.chat-round-badge {
  font-size: 12px;
  color: #fff;
  background: #409eff;
  padding: 1px 8px;
  border-radius: 10px;
}

.chat-messages {
  max-height: 260px;
  overflow-y: auto;
  padding: 8px 4px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}
.chat-message-row {
  display: flex;
  margin-bottom: 12px;
}
.chat-message-row.user {
  justify-content: flex-end;
}
.chat-message-row.assistant {
  justify-content: flex-start;
}

.chat-bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  position: relative;
  word-break: break-word;
}
.chat-bubble.user {
  background: #409eff;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.chat-bubble.assistant {
  background: #fff;
  color: #303133;
  border: 1px solid #e4e7ed;
  border-bottom-left-radius: 4px;
}
.chat-bubble-role {
  font-size: 11px;
  opacity: 0.7;
  margin-bottom: 4px;
}
.chat-bubble-content {
  white-space: pre-wrap;
}
.chat-bubble-time {
  font-size: 10px;
  opacity: 0.5;
  text-align: right;
  margin-top: 4px;
}

/* 加载动画气泡 */
.typing-bubble {
  padding: 12px 18px;
}
.typing-dots {
  display: flex;
  gap: 4px;
}
.typing-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #909399;
  animation: typing-bounce 1.4s infinite ease-in-out both;
}
.typing-dots span:nth-child(1) { animation-delay: -0.32s; }
.typing-dots span:nth-child(2) { animation-delay: -0.16s; }
.typing-dots span:nth-child(3) { animation-delay: 0s; }
@keyframes typing-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.follow-up-bar {
  padding-top: 0;
  border-top: none;
}
.follow-up-input {
  width: 100%;
}

.chat-limit-hint {
  margin-top: 8px;
}

/* ============================================================
   v1.3.0 Audience Section
   ============================================================ */
.audience-section { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.audience-panel { border: 1px solid #ebeef5; border-radius: 8px; padding: 14px; background: #fff; }
.audience-panel-header { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #f0f0f0; }
.audience-block { margin-bottom: 10px; }
.audience-block-title { font-size: 12px; font-weight: 600; color: #909399; margin-bottom: 4px; text-transform: uppercase; }
.audience-code { background: #f5f7fa; padding: 8px 10px; border-radius: 4px; font-family: Consolas, 'Courier New', monospace; font-size: 12px; margin: 4px 0; white-space: pre-wrap; word-break: break-all; }
.audience-text { font-size: 13px; color: #606266; line-height: 1.7; margin: 4px 0; }
.audience-panel.technical { border-left: 3px solid #409eff; }
.audience-panel.executive { border-left: 3px solid #e6a23c; }

/* ============================================================
   Markdown 样式增强
   ============================================================ */
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #e4e7ed;
  padding: 8px 12px;
  text-align: left;
}
.markdown-body :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}
.markdown-body :deep(pre) {
  background: #1e1e1e;
  border-radius: 6px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
}
.markdown-body :deep(code) {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
}
.markdown-body :deep(p code) {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 3px;
  color: #e74c3c;
}
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 12px 0 6px;
  color: #303133;
}
.markdown-body :deep(blockquote) {
  border-left: 4px solid #409eff;
  padding: 4px 12px;
  color: #606266;
  background: #f0f7ff;
  margin: 8px 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 20px;
}

/* ============================================================
   Utility
   ============================================================ */
.mb-10 { margin-bottom: 10px; }
.mb-15 { margin-bottom: 15px; }
.mb-20 { margin-bottom: 20px; }
.mr-5 { margin-right: 5px; }
.mb-5 { margin-bottom: 5px; }
.ops-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px;
  align-items: start;
}
@media (max-width: 900px) {
  .ops-grid { grid-template-columns: 1fr; }
}
.mt-5 { margin-top: 5px; }
.mt-10 { margin-top: 10px; }
.mt-15 { margin-top: 15px; }
.mt-20 { margin-top: 20px; }
.mt-25 { margin-top: 25px; }
.ml-10 { margin-left: 10px; }
.flex-center {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
}
</style>
