<template>
  <div class="page-container">
    <h2 class="page-title mb-20">
      <span>AI 分析</span>
      <span class="page-subtitle">配置 AI 供应商、模型与提示词</span>
    </h2>

    <el-tabs v-model="activeTab" class="ai-tabs">
      <!-- ============================================================ -->
      <!-- 配置 Tab -->
      <!-- ============================================================ -->
      <el-tab-pane label="配置" name="config">
        <!-- Profile 切换区 -->
        <div class="profile-bar card-box mb-20">
          <div class="profile-bar-left">
            <span class="profile-label">当前配置：</span>
            <el-select
              v-model="selectedProfileId"
              placeholder="选择 AI 配置"
              class="profile-select"
              @change="onProfileSelect"
              :loading="profileLoading"
            >
              <el-option
                v-for="p in store.profiles"
                :key="p.id"
                :label="profileLabel(p)"
                :value="p.id"
              />
            </el-select>
            <span class="profile-detail" v-if="currentProfileData">
              {{ currentProfileData.model_name || '--' }} · {{ currentProfileData.provider || '--' }}
            </span>
            <span class="status-dot" :class="{ active: store.activeProfileId === selectedProfileId }">
              <span class="dot"></span>
              {{ store.activeProfileId === selectedProfileId ? '活跃中' : '未激活' }}
            </span>
          </div>
          <div class="profile-bar-right">
            <el-button
              size="small"
              @click="openEditDialog"
              :disabled="!selectedProfileId"
            >编辑</el-button>
            <el-dropdown trigger="click" size="small">
              <el-button size="small">更多 ▼</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="openAddDialog">新增配置</el-dropdown-item>
                  <el-dropdown-item
                    @click="handleSetActive"
                    :disabled="!selectedProfileId || store.activeProfileId === selectedProfileId"
                  >设为活跃</el-dropdown-item>
                  <el-dropdown-item
                    @click="handleDeleteProfile"
                    :disabled="!selectedProfileId || store.profiles.length <= 1"
                    divided
                  >删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <!-- AI 功能开关 -->
        <div class="switch-row card-box mb-20">
          <div class="switch-left">
            <span class="switch-label">AI 分析功能</span>
            <el-switch
              v-model="aiSwitchOn"
              @change="handleToggleAi"
              active-color="#13ce66"
              inactive-color="#909399"
              :loading="toggleLoading"
              :disabled="!canToggleAi"
            />
          </div>
          <div class="switch-right">
            <span class="switch-hint" v-if="!canToggleAi && !aiSwitchOn">
              需要先创建配置并设置 API Base URL 和 API Key
            </span>
          </div>
        </div>

        <!-- 配置表单区 -->
        <div v-if="currentProfileData" class="card-box mb-20" v-loading="formLoading">
          <div class="section-title">配置详情 <span class="subsection-hint">编辑后自动保存</span></div>

          <div class="config-grid">
            <!-- 左侧列 -->
            <div class="config-col">
              <el-form-item label="配置名称">
                <el-input v-model="configForm.profile_name" size="small" maxlength="60" show-word-limit />
              </el-form-item>
              <el-form-item label="API Key">
                <div class="api-key-row">
                  <el-input v-model="configForm.api_key" size="small" type="password" show-password />
                </div>
              </el-form-item>
              <el-form-item label="系统提示词">
                <el-input v-model="configForm.system_prompt" type="textarea" :rows="4" size="small" placeholder="自定义 AI 分析的系统提示词（可选，留空使用默认提示词）" />
                <el-button v-if="configForm.system_prompt" size="small" @click="openPromptOptimize" class="prompt-optimize-btn">提示词优化</el-button>
              </el-form-item>
            </div>

            <!-- 右侧列 -->
            <div class="config-col">
              <el-form-item label="AI 提供商">
                <el-select v-model="configForm.provider" size="small" style="width:100%" filterable allow-create placeholder="选择或输入提供商">
                  <el-option label="OpenAI" value="openai" />
                  <el-option label="DeepSeek" value="deepseek" />
                  <el-option label="通义千问" value="qwen" />
                  <el-option label="智谱 GLM" value="zhipu" />
                  <el-option label="Anthropic" value="anthropic" />
                  <el-option label="Ollama (本地)" value="ollama" />
                  <el-option label="自定义" value="custom" />
                </el-select>
                <!-- P2-05: Ollama 本地模型提示 -->
                <div v-if="configForm.provider === 'ollama'" class="ollama-hint mt-10">
                  <el-alert type="info" :closable="false" show-icon>
                    <template #title>
                      使用本地模型
                    </template>
                    请确保已启动本地 Ollama 服务：<br/>
                    <code>ollama pull llama3 &amp;&amp; ollama serve</code><br/>
                    默认 API 地址: <code>http://localhost:11434/v1</code>
                  </el-alert>
                </div>
              </el-form-item>
              <el-form-item label="API Base URL">
                <el-input v-model="configForm.api_base_url" size="small" placeholder="https://api.deepseek.com" />
                <div class="form-tip">兼容 OpenAI 格式的 API 地址</div>
              </el-form-item>
              <el-form-item label="模型名称">
                <el-select v-model="configForm.model_name" size="small" style="width:100%" filterable allow-create placeholder="选择或输入模型名称">
                  <el-option label="gpt-4o" value="gpt-4o" />
                  <el-option label="gpt-4o-mini" value="gpt-4o-mini" />
                  <el-option label="gpt-4-turbo" value="gpt-4-turbo" />
                  <el-option label="gpt-4" value="gpt-4" />
                  <el-option label="gpt-3.5-turbo" value="gpt-3.5-turbo" />
                  <el-option label="deepseek-chat" value="deepseek-chat" />
                  <el-option label="deepseek-reasoner" value="deepseek-reasoner" />
                  <el-option label="deepseek-v4-flash" value="deepseek-v4-flash" />
                  <el-option label="qwen-max" value="qwen-max" />
                  <el-option label="qwen-plus" value="qwen-plus" />
                  <el-option label="glm-4" value="glm-4" />
                  <el-option label="claude-3-5-sonnet" value="claude-3-5-sonnet" />
                  <el-option label="claude-3-opus" value="claude-3-opus" />
                </el-select>
              </el-form-item>
              <el-form-item label="Max Tokens">
                <div class="slider-row">
                  <el-slider v-model="configForm.max_tokens" :min="256" :max="65536" size="small" style="flex:1" />
                  <el-input-number v-model="configForm.max_tokens" :min="256" :max="65536" size="small" style="width:100px" controls-position="right" />
                </div>
              </el-form-item>
              <el-form-item label="Temperature">
                <div class="slider-row">
                  <el-slider v-model="configForm.temperature" :min="0" :max="2" :step="0.1" size="small" style="flex:1" />
                  <el-input-number v-model="configForm.temperature" :min="0" :max="2" :step="0.1" size="small" style="width:80px" controls-position="right" />
                </div>
              </el-form-item>
            </div>
          </div>
          <div class="config-actions">
            <el-button size="small" :loading="testing" @click="handleTestConnection">测试连接</el-button>
            <el-button size="small" type="primary" :loading="saving" @click="handleSaveConfig">保存配置</el-button>
          </div>
        </div>

        <!-- 无 Profile 时的空状态 -->
        <div v-if="store.profiles.length === 0 && !profileLoading" class="card-box mb-20 empty-state">
          <el-empty description="尚未创建 AI 配置">
            <el-button type="primary" @click="openAddDialog">创建第一个配置</el-button>
          </el-empty>
        </div>

        <!-- 使用统计区 -->
        <div class="card-box stats-section">
          <h3 class="section-title">使用统计</h3>

          <!-- 汇总卡片 -->
          <el-row :gutter="20" class="stats-cards mb-20">
            <el-col :span="6">
              <div class="stat-card">
                <div class="stat-card-icon stat-icon-tokens">
                  <el-icon :size="24"><Coin /></el-icon>
                </div>
                <div class="stat-card-info">
                  <div class="stat-card-value">{{ formatNumber(stats.totalTokens) }}</div>
                  <div class="stat-card-label">本月总 Token</div>
                </div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="stat-card">
                <div class="stat-card-icon stat-icon-calls">
                  <el-icon :size="24"><TrendCharts /></el-icon>
                </div>
                <div class="stat-card-info">
                  <div class="stat-card-value">{{ formatNumber(stats.totalCalls) }}</div>
                  <div class="stat-card-label">总调用次数</div>
                </div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="stat-card">
                <div class="stat-card-icon stat-icon-latency">
                  <el-icon :size="24"><Timer /></el-icon>
                </div>
                <div class="stat-card-info">
                  <div class="stat-card-value">{{ stats.avgLatency }}<small>ms</small></div>
                  <div class="stat-card-label">平均延迟</div>
                </div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="stat-card">
                <div class="stat-card-icon stat-icon-rate">
                  <el-icon :size="24"><DataAnalysis /></el-icon>
                </div>
                <div class="stat-card-info">
                  <div class="stat-card-value">{{ stats.successRate }}<small>%</small></div>
                  <div class="stat-card-label">成功率</div>
                </div>
              </div>
            </el-col>
          </el-row>

          <!-- 折线图控制 -->
          <div class="chart-controls mb-10">
            <span class="chart-label">Token 消耗趋势：</span>
            <el-radio-group v-model="chartPeriod" @change="loadChartData" size="small">
              <el-radio-button value="daily">日</el-radio-button>
              <el-radio-button value="weekly">周</el-radio-button>
              <el-radio-button value="monthly">月</el-radio-button>
            </el-radio-group>
          </div>

          <!-- 折线图 -->
          <div class="chart-container" v-loading="chartLoading">
            <v-chart v-if="chartOption" :option="chartOption" autoresize class="token-chart" />
            <el-empty v-else description="暂无统计数据" :image-size="80" />
          </div>
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- 审计日志 Tab -->
      <!-- ============================================================ -->
      <el-tab-pane label="审计日志" name="audit">
        <div class="card-box">
          <h3 class="section-title mb-20">AI 调用审计日志</h3>
          <el-table
            :data="auditLogs"
            v-loading="auditLoading"
            stripe
            border
            class="audit-table"
            @sort-change="handleAuditSort"
          >
            <el-table-column prop="created_at" label="时间" width="170" sortable="custom">
              <template #default="{ row }">
                {{ formatTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column prop="host_name" label="主机名" min-width="140" show-overflow-tooltip />
            <el-table-column prop="model_name" label="模型" width="150" show-overflow-tooltip />
            <el-table-column prop="total_tokens" label="Token 数" width="100" align="right" sortable="custom">
              <template #default="{ row }">
                {{ formatNumber(row.total_tokens) }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" link size="small" @click="openAuditDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 分页 -->
          <div class="flex-between mt-15">
            <div class="text-gray">共 {{ auditPagination.total }} 条记录</div>
            <el-pagination
              v-model:current-page="auditPagination.page"
              v-model:page-size="auditPagination.pageSize"
              :total="auditPagination.total"
              :page-sizes="[10, 20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              @change="loadAuditLogs"
              small
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ============================================================ -->
    <!-- Profile 新增/编辑 Dialog -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="profileDialogVisible"
      :title="profileDialogMode === 'add' ? '新增 AI 配置' : '编辑 AI 配置'"
      width="600px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="resetProfileForm"
    >
      <el-form
        ref="profileFormRef"
        :model="profileForm"
        :rules="profileFormRules"
        label-width="120px"
        @submit.prevent
      >
        <el-form-item label="配置名称" prop="profile_name">
          <el-input v-model="profileForm.profile_name" placeholder="例如：生产环境 GPT-4o" clearable />
        </el-form-item>
        <el-form-item label="AI 提供商" prop="provider">
          <el-select v-model="profileForm.provider" filterable allow-create placeholder="选择提供商">
            <el-option label="OpenAI" value="openai" />
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="通义千问" value="qwen" />
            <el-option label="智谱 GLM" value="zhipu" />
            <el-option label="Anthropic" value="anthropic" />
            <el-option label="Ollama (本地)" value="ollama" />
            <el-option label="自定义" value="custom" />
          </el-select>
          <!-- P2-05: Ollama 本地模型提示 -->
          <div v-if="profileForm.provider === 'ollama'" class="ollama-hint mt-10">
            <el-alert type="info" :closable="false" show-icon>
              <template #title>
                使用本地模型
              </template>
              请确保已启动本地 Ollama 服务：<br/>
              <code>ollama pull llama3 &amp;&amp; ollama serve</code><br/>
              默认 API 地址: <code>http://localhost:11434/v1</code>
            </el-alert>
          </div>
        </el-form-item>
        <el-form-item label="API Base URL" prop="api_base_url">
          <el-input v-model="profileForm.api_base_url" placeholder="https://api.openai.com/v1" clearable />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="profileForm.api_key"
            type="password"
            placeholder="输入 API Key"
            show-password
            clearable
          />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-select v-model="profileForm.model_name" filterable allow-create placeholder="选择或输入模型">
            <el-option label="gpt-4o" value="gpt-4o" />
            <el-option label="gpt-4o-mini" value="gpt-4o-mini" />
            <el-option label="gpt-4-turbo" value="gpt-4-turbo" />
            <el-option label="deepseek-chat" value="deepseek-chat" />
            <el-option label="deepseek-reasoner" value="deepseek-reasoner" />
            <el-option label="qwen-max" value="qwen-max" />
            <el-option label="qwen-plus" value="qwen-plus" />
            <el-option label="glm-4" value="glm-4" />
            <el-option label="claude-3-5-sonnet" value="claude-3-5-sonnet" />
          </el-select>
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-slider v-model="profileForm.max_tokens" :min="512" :max="16384" :step="256" show-input />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-slider v-model="profileForm.temperature" :min="0" :max="1" :step="0.1" show-input />
        </el-form-item>
        <el-form-item label="系统提示词">
          <div class="prompt-row">
            <el-input
              v-model="profileForm.system_prompt"
              type="textarea"
              :rows="5"
              placeholder="自定义系统提示词（可选）"
              class="prompt-textarea"
            />
            <!-- P2-06: 提示词优化按钮 -->
            <el-button
              class="prompt-optimize-btn"
              type="warning"
              size="small"
              :disabled="!selectedProfileId && profileDialogMode === 'edit'"
              @click="openPromptOptimize"
            >
              提示词优化
            </el-button>
          </div>
        </el-form-item>
        <!-- P2-08: 公开配置开关 -->
        <el-form-item label="公开配置">
          <el-switch
            v-model="profileForm.is_public"
            active-text="允许其他用户使用此配置"
            inactive-text="仅自己可见"
          />
          <div class="form-tip">开启后，其他用户可以查看和使用此配置进行 AI 分析</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="profileDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          @click="submitProfile"
          :loading="profileSubmitLoading"
        >
          {{ profileDialogMode === 'add' ? '创建' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ============================================================ -->
    <!-- P2-06: 提示词优化 Dialog -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="promptOptimizeVisible"
      title="提示词优化"
      width="750px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="resetPromptOptimize"
    >
      <!-- 步骤 1：输入反馈 -->
      <div v-if="promptOptStep === 'input'" class="prompt-opt-input">
        <el-alert type="info" :closable="false" class="mb-15" show-icon>
          描述你希望 AI 如何改进提示词，系统将根据你的反馈自动优化
        </el-alert>

        <div class="mb-10">
          <span class="opt-label">当前提示词：</span>
        </div>
        <div class="opt-current-prompt mb-15">
          <pre>{{ currentPromptText || '(空)' }}</pre>
        </div>

        <div class="mb-10">
          <span class="opt-label">优化反馈：</span>
        </div>
        <el-input
          v-model="promptOptimizeFeedback"
          type="textarea"
          :rows="4"
          placeholder="例如：让回答更简洁、增加中文输出、聚焦安全事件分析..."
        />
        <div class="flex-center mt-20">
          <el-button @click="promptOptimizeVisible = false">取消</el-button>
          <el-button
            type="primary"
            @click="handlePromptOptimize"
            :loading="promptOptLoading"
            :disabled="!promptOptimizeFeedback.trim()"
          >
            开始优化
          </el-button>
        </div>
      </div>

      <!-- 步骤 2：预览对比 -->
      <div v-else-if="promptOptStep === 'preview'" class="prompt-opt-preview">
        <el-alert type="success" :closable="false" class="mb-15" show-icon>
          优化完成，请对比下方结果
        </el-alert>

        <div class="opt-compare-grid">
          <div class="opt-compare-col">
            <div class="opt-compare-header old">原始提示词</div>
            <div class="opt-compare-content">
              <pre>{{ currentPromptText || '(空)' }}</pre>
            </div>
          </div>
          <div class="opt-compare-col">
            <div class="opt-compare-header new">优化后提示词</div>
            <div class="opt-compare-content">
              <pre>{{ optimizedPromptText }}</pre>
            </div>
          </div>
        </div>

        <!-- 历史版本下拉 -->
        <div class="opt-history-bar mt-15" v-if="promptVersions.length > 0">
          <span class="opt-label mr-10">历史版本：</span>
          <el-select
            v-model="selectedPromptVersion"
            placeholder="查看历史版本"
            size="small"
            class="opt-history-select"
            @change="onPromptVersionSelect"
            :loading="promptVersionLoading"
          >
            <el-option
              v-for="v in promptVersions"
              :key="v.id"
              :label="v.label || `版本 ${v.id}`"
              :value="v.id"
            />
          </el-select>
        </div>

        <div class="flex-center mt-20">
          <el-button @click="handleRevertOptimize">回退</el-button>
          <el-button type="primary" @click="handleAcceptOptimize">采纳优化结果</el-button>
        </div>
      </div>

      <template #footer v-if="false" />
    </el-dialog>

    <!-- ============================================================ -->
    <!-- 审计日志详情 Dialog -->
    <!-- ============================================================ -->
    <el-dialog
      v-model="auditDetailVisible"
      title="审计日志详情"
      width="800px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-if="auditDetail" class="audit-detail">
        <el-descriptions :column="2" border size="small" class="mb-20">
          <el-descriptions-item label="时间">{{ formatTime(auditDetail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="主机名">{{ auditDetail.host_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="模型">{{ auditDetail.model_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Token 数">{{ formatNumber(auditDetail.total_tokens) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(auditDetail.status)" size="small">
              {{ statusLabel(auditDetail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="耗时">{{ auditDetail.latency_ms ? auditDetail.latency_ms + 'ms' : '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="audit-section mb-15">
          <h4>发送的 Prompt</h4>
          <div class="audit-content" :class="{ collapsed: !promptExpanded }">
            <pre>{{ auditDetail.prompt || '(无)' }}</pre>
          </div>
          <el-button
            v-if="isTextLong(auditDetail.prompt)"
            type="primary"
            link
            size="small"
            @click="promptExpanded = !promptExpanded"
            class="mt-5"
          >
            {{ promptExpanded ? '收起' : '展开全部' }}
          </el-button>
        </div>

        <div class="audit-section">
          <h4>AI 回复</h4>
          <div class="audit-content" :class="{ collapsed: !responseExpanded }">
            <pre>{{ auditDetail.response || '(无)' }}</pre>
          </div>
          <el-button
            v-if="isTextLong(auditDetail.response)"
            type="primary"
            link
            size="small"
            @click="responseExpanded = !responseExpanded"
            class="mt-5"
          >
            {{ responseExpanded ? '收起' : '展开全部' }}
          </el-button>
        </div>
      </div>
      <div v-else v-loading="auditDetailLoading" style="min-height:200px;" />
      <template #footer>
        <el-button @click="auditDetailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, CircleClose, Coin, TrendCharts, Timer, DataAnalysis } from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import 'echarts'
import dayjs from 'dayjs'
import {
  getAiTokenStats,
  getAiTokenSummary,
  getAiAuditLogs,
  getAiAuditLogDetail,
  testAiConnection,
  optimizePrompt,
  getPromptVersions,
} from '@/api/ai'
import { useAiStore } from '@/stores/ai'

const store = useAiStore()

// ============================================================
// Tab & Profile 状态
// ============================================================
const activeTab = ref('config')
const selectedProfileId = ref(null)
const profileLoading = ref(false)

// ============================================================
// AI 开关
// ============================================================
const aiSwitchOn = ref(false)
const toggleLoading = ref(false)

const canToggleAi = computed(() => {
  const p = currentProfileData.value
  return !!(p && (p.api_base_url || configForm.api_base_url) && (p.api_key_masked || configForm.api_key))
})

// ============================================================
// 配置表单
// ============================================================
const formLoading = ref(false)
const saveLoading = ref(false)
const testLoading = ref(false)
const testResult = ref('')     // '' | 'success' | 'fail'
const testErrorMsg = ref('')

const configForm = reactive({
  profile_name: '',
  provider: '',
  api_base_url: '',
  api_key: '',
  model_name: 'gpt-4o',
  max_tokens: 4096,
  temperature: 0.3,
  system_prompt: '',
})

const currentProfileData = computed(() => {
  return store.profiles.find((p) => p.id === selectedProfileId.value) || null
})

// ============================================================
// 使用统计
// ============================================================
const chartPeriod = ref('daily')
const chartLoading = ref(false)
const chartOption = ref(null)

const stats = reactive({
  totalTokens: 0,
  totalCalls: 0,
  avgLatency: 0,
  successRate: 0,
})

// ============================================================
// 审计日志
// ============================================================
const auditLogs = ref([])
const auditLoading = ref(false)
const auditPagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
})
const auditSort = reactive({ field: '', order: '' })

const auditDetailVisible = ref(false)
const auditDetail = ref(null)
const auditDetailLoading = ref(false)
const promptExpanded = ref(false)
const responseExpanded = ref(false)

// ============================================================
// Profile 编辑 Dialog
// ============================================================
const profileDialogVisible = ref(false)
const profileDialogMode = ref('add')  // 'add' | 'edit'
const profileSubmitLoading = ref(false)
const profileFormRef = ref(null)

const profileForm = reactive({
  profile_name: '',
  provider: 'openai',
  api_base_url: '',
  api_key: '',
  model_name: 'gpt-4o',
  max_tokens: 4096,
  temperature: 0.3,
  system_prompt: '',
  is_public: true,
})

const profileFormRules = {
  profile_name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  api_base_url: [{ required: true, message: '请输入 API Base URL', trigger: 'blur' }],
}

// ============================================================
// P2-06: 提示词优化状态
// ============================================================
const promptOptimizeVisible = ref(false)
const promptOptStep = ref('input')        // 'input' | 'preview'
const promptOptimizeFeedback = ref('')
const optimizedPromptText = ref('')
const promptOptLoading = ref(false)
const promptVersions = ref([])
const promptVersionLoading = ref(false)
const selectedPromptVersion = ref('')

const currentPromptText = computed(() => {
  // 优先取当前编辑中的 system_prompt
  return configForm.system_prompt || currentProfileData.value?.system_prompt || ''
})

// ============================================================
// 初始化
// ============================================================
onMounted(async () => {
  profileLoading.value = true
  try {
    await store.fetchProfiles()
    if (store.profiles.length > 0) {
      selectedProfileId.value = store.activeProfileId || store.profiles[0].id
      aiSwitchOn.value = store.isAiEnabled
      fillConfigForm()
    }
    await loadStats()
  } finally {
    profileLoading.value = false
  }
})

// ============================================================
// Profile 选择 & 表单填充
// ============================================================
function onProfileSelect(id) {
  fillConfigForm()
  testResult.value = ''
  testErrorMsg.value = ''
}

function fillConfigForm() {
  const p = currentProfileData.value
  if (!p) return
  configForm.profile_name = p.profile_name || ''
  configForm.provider = p.provider || ''
  configForm.api_base_url = p.api_base_url || ''
  configForm.api_key = ''
  configForm.model_name = p.model_name || 'gpt-4o'
  configForm.max_tokens = p.max_tokens || 4096
  configForm.temperature = p.temperature ?? 0.3
  configForm.system_prompt = p.system_prompt || ''
}

function handleResetConfig() {
  fillConfigForm()
  testResult.value = ''
  testErrorMsg.value = ''
}

function profileLabel(p) {
  let label = p.profile_name || `配置 #${p.id}`
  if (p.provider) label += ` (${p.provider})`
  return label
}

// ============================================================
// AI 开关
// ============================================================
async function handleToggleAi(val) {
  if (val) {
    // 开启：检查配置完整性
    if (!canToggleAi.value) {
      ElMessage.warning('请先完善 API Base URL 和 API Key')
      aiSwitchOn.value = false
      return
    }
    if (!store.activeProfileId || store.activeProfileId !== selectedProfileId.value) {
      toggleLoading.value = true
      try {
        await store.setActiveProfile(selectedProfileId.value)
        ElMessage.success('AI 分析功能已开启')
      } catch (e) {
        ElMessage.error(e?.response?.data?.message || '开启失败')
        aiSwitchOn.value = false
      } finally {
        toggleLoading.value = false
      }
    }
  } else {
    // 关闭：清除活跃状态（UI 层面）
    ElMessage.info('AI 分析功能已关闭，可通过"设为活跃"重新开启')
  }
}

// ============================================================
// 设为活跃
// ============================================================
async function handleSetActive() {
  if (!selectedProfileId.value) return
  try {
    await store.setActiveProfile(selectedProfileId.value)
    aiSwitchOn.value = true
    ElMessage.success('已设为活跃配置')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '操作失败')
  }
}

// ============================================================
// 删除 Profile
// ============================================================
async function handleDeleteProfile() {
  if (store.profiles.length <= 1) {
    ElMessage.warning('不能删除最后一个配置')
    return
  }
  if (!selectedProfileId.value) return
  try {
    await store.deleteProfileById(selectedProfileId.value)
    selectedProfileId.value = store.profiles.length > 0 ? store.profiles[0].id : null
    fillConfigForm()
    aiSwitchOn.value = store.isAiEnabled
    ElMessage.success('配置已删除')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '删除失败')
  }
}

// ============================================================
// 测试连接
// ============================================================
async function handleTestConnection() {
  if (!selectedProfileId.value) {
    ElMessage.warning('请先选择或创建配置')
    return
  }
  testLoading.value = true
  testResult.value = ''
  testErrorMsg.value = ''
  try {
    await testAiConnection(selectedProfileId.value)
    testResult.value = 'success'
    ElMessage.success('连接测试成功')
  } catch (e) {
    testResult.value = 'fail'
    testErrorMsg.value = e?.response?.data?.message || e?.message || '连接失败'
    ElMessage.error(testErrorMsg.value)
  } finally {
    testLoading.value = false
  }
}

// ============================================================
// 保存配置
// ============================================================
async function handleSaveConfig() {
  if (!selectedProfileId.value) return
  saveLoading.value = true
  try {
    const data = {
      profile_name: configForm.profile_name,
      provider: configForm.provider,
      api_base_url: configForm.api_base_url,
      model_name: configForm.model_name,
      max_tokens: configForm.max_tokens,
      temperature: configForm.temperature,
      system_prompt: configForm.system_prompt,
    }
    if (configForm.api_key) {
      data.api_key = configForm.api_key
    }
    await store.updateProfile(selectedProfileId.value, data)
    configForm.api_key = ''
    aiSwitchOn.value = store.isAiEnabled
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '保存失败')
  } finally {
    saveLoading.value = false
  }
}

// ============================================================
// Profile Dialog 操作
// ============================================================
function openAddDialog() {
  profileDialogMode.value = 'add'
  resetProfileForm()
  profileDialogVisible.value = true
}

function openEditDialog() {
  if (!selectedProfileId.value) return
  profileDialogMode.value = 'edit'
  const p = currentProfileData.value
  if (p) {
    profileForm.profile_name = p.profile_name || ''
    profileForm.provider = p.provider || 'openai'
    profileForm.api_base_url = p.api_base_url || ''
    profileForm.api_key = ''
    profileForm.model_name = p.model_name || 'gpt-4o'
    profileForm.max_tokens = p.max_tokens || 4096
    profileForm.temperature = p.temperature ?? 0.3
    profileForm.system_prompt = p.system_prompt || ''
    profileForm.is_public = p.is_public !== undefined ? !!p.is_public : true
  }
  profileDialogVisible.value = true
}

function resetProfileForm() {
  profileForm.profile_name = ''
  profileForm.provider = 'openai'
  profileForm.api_base_url = ''
  profileForm.api_key = ''
  profileForm.model_name = 'gpt-4o'
  profileForm.max_tokens = 4096
  profileForm.temperature = 0.3
  profileForm.system_prompt = ''
  profileForm.is_public = true
  profileFormRef.value?.resetFields()
}

async function submitProfile() {
  const valid = await profileFormRef.value?.validate().catch(() => false)
  if (!valid) return

  profileSubmitLoading.value = true
  try {
    const data = {
      profile_name: profileForm.profile_name,
      provider: profileForm.provider,
      api_base_url: profileForm.api_base_url,
      model_name: profileForm.model_name,
      max_tokens: profileForm.max_tokens,
      temperature: profileForm.temperature,
      system_prompt: profileForm.system_prompt,
      is_public: profileForm.is_public ? 1 : 0,
    }
    if (profileForm.api_key) {
      data.api_key = profileForm.api_key
    }

    if (profileDialogMode.value === 'add') {
      const created = await store.createProfile(data)
      selectedProfileId.value = created.id
    } else {
      await store.updateProfile(selectedProfileId.value, data)
    }

    profileDialogVisible.value = false
    fillConfigForm()
    aiSwitchOn.value = store.isAiEnabled
    ElMessage.success(profileDialogMode.value === 'add' ? '配置已创建' : '配置已更新')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '操作失败')
  } finally {
    profileSubmitLoading.value = false
  }
}

// ============================================================
// 使用统计
// ============================================================
async function loadStats() {
  try {
    // 调用 summary 端点获取汇总统计数据（total_tokens/calls/success_rate 等）
    const res = await getAiTokenSummary()
    const d = res.data || {}
    stats.totalTokens = d.this_month_tokens || d.total_tokens || 0
    stats.totalCalls = d.this_month_calls || d.total_calls || 0
    stats.avgLatency = Math.round(d.avg_latency_ms || d.avg_latency || 0)
    const rate = d.success_rate != null ? Number(d.success_rate) : 0
    stats.successRate = (rate * 100).toFixed(1)
  } catch {
    // 静默失败
  }

  await loadChartData()
}

async function loadChartData() {
  chartLoading.value = true
  try {
    // 使用 stats/tokens 端点获取按日聚合的时间序列数据
    const daysMap = { daily: 30, weekly: 90, monthly: 365 }
    const days = daysMap[chartPeriod.value] || 30
    const res = await getAiTokenStats({ days })
    const raw = res.data || {}
    const data = raw?.items || raw?.list || []
    buildChartOption(data)
  } catch {
    chartOption.value = null
  } finally {
    chartLoading.value = false
  }
}

function buildChartOption(data) {
  // 数据格式: [{ period: '2024-01-01', tokens: 1000, calls: 5 }, ...]
  if (!Array.isArray(data) || data.length === 0) {
    chartOption.value = null
    return
  }

  const xData = data.map((d) => d.period || d.date || '')
  const tokenData = data.map((d) => d.tokens || d.total_tokens || 0)
  const callData = data.map((d) => d.calls || d.total_calls || d.call_count || d.count || 0)

  chartOption.value = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: {
      data: ['Token 消耗', '调用次数'],
      bottom: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '40px',
      top: '10px',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: xData,
      boundaryGap: false,
      axisLabel: {
        rotate: xData.length > 10 ? 45 : 0,
      },
    },
    yAxis: [
      {
        type: 'value',
        name: 'Token',
        axisLabel: {
          formatter: (v) => formatLargeNumber(v),
        },
      },
      {
        type: 'value',
        name: '次数',
        axisLabel: {
          formatter: '{value}',
        },
      },
    ],
    series: [
      {
        name: 'Token 消耗',
        type: 'line',
        data: tokenData,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: '#409eff', width: 2 },
        itemStyle: { color: '#409eff' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(64,158,255,0.3)' },
              { offset: 1, color: 'rgba(64,158,255,0.05)' },
            ],
          },
        },
      },
      {
        name: '调用次数',
        type: 'line',
        yAxisIndex: 1,
        data: callData,
        smooth: true,
        symbol: 'diamond',
        symbolSize: 6,
        lineStyle: { color: '#67c23a', width: 2 },
        itemStyle: { color: '#67c23a' },
      },
    ],
  }
}

// ============================================================
// 审计日志
// ============================================================
watch(activeTab, (tab) => {
  if (tab === 'audit') {
    loadAuditLogs()
  }
})

async function loadAuditLogs() {
  auditLoading.value = true
  try {
    const params = {
      page: auditPagination.page,
      page_size: auditPagination.pageSize,
    }
    if (auditSort.field) {
      params.sort_by = auditSort.field
      params.sort_order = auditSort.order === 'ascending' ? 'asc' : 'desc'
    }
    const res = await getAiAuditLogs(params)
    auditLogs.value = res.data?.items || res.data?.list || res.data || []
    auditPagination.total = res.data?.total || auditLogs.value.length
  } catch {
    auditLogs.value = []
  } finally {
    auditLoading.value = false
  }
}

function handleAuditSort({ prop, order }) {
  auditSort.field = prop
  auditSort.order = order || ''
  loadAuditLogs()
}

async function openAuditDetail(row) {
  auditDetailVisible.value = true
  auditDetail.value = null
  promptExpanded.value = false
  responseExpanded.value = false
  auditDetailLoading.value = true
  try {
    const res = await getAiAuditLogDetail(row.id)
    auditDetail.value = res.data
  } catch {
    auditDetail.value = null
  } finally {
    auditDetailLoading.value = false
  }
}

// ============================================================
// P2-06: 提示词优化
// ============================================================
function openPromptOptimize() {
  promptOptimizeVisible.value = true
  promptOptStep.value = 'input'
  promptOptimizeFeedback.value = ''
  optimizedPromptText.value = ''
  // 预加载历史版本
  loadPromptVersions()
}

function resetPromptOptimize() {
  promptOptStep.value = 'input'
  promptOptimizeFeedback.value = ''
  optimizedPromptText.value = ''
}

async function loadPromptVersions() {
  if (!selectedProfileId.value) return
  promptVersionLoading.value = true
  try {
    const res = await getPromptVersions(selectedProfileId.value)
    const data = res.data || []
    promptVersions.value = (Array.isArray(data) ? data : data.items || []).map((v) => ({
      ...v,
      label: `${v.version || v.id} - ${v.created_at ? dayjs(v.created_at).format('MM-DD HH:mm') : ''}`,
    }))
  } catch {
    promptVersions.value = []
  } finally {
    promptVersionLoading.value = false
  }
}

async function handlePromptOptimize() {
  if (!selectedProfileId.value) {
    ElMessage.warning('请先选择一个配置')
    return
  }
  if (!promptOptimizeFeedback.value.trim()) return

  promptOptLoading.value = true
  try {
    const res = await optimizePrompt(selectedProfileId.value, {
      feedback: promptOptimizeFeedback.value.trim(),
      current_prompt: currentPromptText.value,
    })
    const data = res.data || res
    optimizedPromptText.value = data.optimized_prompt || data.prompt || data.result || ''
    promptOptStep.value = 'preview'
    ElMessage.success('提示词优化完成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.message || '优化失败')
  } finally {
    promptOptLoading.value = false
  }
}

function handleAcceptOptimize() {
  if (!optimizedPromptText.value) return
  configForm.system_prompt = optimizedPromptText.value
  promptOptimizeVisible.value = false
  ElMessage.success('已采纳优化后的提示词，请记得保存配置')
}

function handleRevertOptimize() {
  promptOptStep.value = 'input'
  promptOptimizeFeedback.value = ''
  optimizedPromptText.value = ''
}

function onPromptVersionSelect(versionId) {
  const v = promptVersions.value.find((p) => p.id === versionId)
  if (v && v.prompt) {
    optimizedPromptText.value = v.prompt
    promptOptStep.value = 'preview'
  }
}

// ============================================================
// 工具函数
// ============================================================
function formatNumber(n) {
  if (n == null) return '0'
  return Number(n).toLocaleString()
}

function formatLargeNumber(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

function formatTime(t) {
  if (!t) return '-'
  return dayjs(t).format('YYYY-MM-DD HH:mm:ss')
}

function statusTagType(status) {
  const map = { success: 'success', completed: 'success', error: 'danger', failed: 'danger', cancelled: 'info', running: 'warning' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { success: '成功', completed: '成功', error: '失败', failed: '失败', cancelled: '已取消', running: '运行中' }
  return map[status] || status || '-'
}

function isTextLong(text) {
  return text && text.length > 300
}

</script>

<style scoped>
.profile-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.profile-bar-left, .profile-bar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.profile-label {
  font-size: 13px;
  color: var(--color-text-secondary, #555);
  white-space: nowrap;
}
.profile-select {
  width: 260px;
}
.profile-detail {
  font-size: 12px;
  color: var(--color-fg-subtle, #888);
  white-space: nowrap;
}
.status-dot {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--color-text-tertiary, #888);
}
.status-dot .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-text-tertiary, #888);
  flex-shrink: 0;
}
.status-dot.active .dot {
  background: var(--color-text-success, #16a34a);
}
.status-dot.active {
  color: var(--color-text-success, #16a34a);
}
.switch-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.switch-left, .switch-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.switch-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-primary, #111);
}
.switch-hint {
  font-size: 12px;
  color: var(--color-text-tertiary, #888);
}
.section-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-primary, #111);
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}
.config-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 32px;
}
.config-col { min-width: 0; }
.config-col :deep(.el-form-item) { margin-bottom: 14px; }
.config-col :deep(.el-form-item__label) {
  font-size: 12px; color: var(--color-fg-subtle, #888);
  font-weight: 400; padding-bottom: 2px;
  line-height: 1.4;
}
.config-col :deep(.el-form-item__content) { line-height: 1; }
.config-col :deep(.el-input__wrapper) { border-radius: 4px; }
.config-col :deep(.el-slider__runway) { margin: 8px 0; }
.config-col :deep(.el-slider__bar) { background: var(--color-accent-emphasis, #185FA5); }
.config-col :deep(.el-slider__button) { border-color: var(--color-accent-emphasis, #185FA5); }

.subsection-hint {
  font-size: 12px; color: var(--color-fg-subtle, #888);
  font-weight: 400; margin-left: 8px;
}
.config-actions {
  display: flex; align-items: center; gap: 8px;
  margin-top: 12px; padding-top: 12px;
  border-top: 0.5px solid var(--color-border-default, #e5e5e5);
}
.api-key-row { display: flex; gap: 4px; width: 100%; }
.api-key-row .el-input { flex: 1; }
.slider-row { display: flex; align-items: center; gap: 10px; width: 100%; }

.form-tip {
  font-size: 12px;
  color: var(--color-text-tertiary, #888);
  margin-top: 4px;
}
.form-tip code {
  color: var(--color-text-warning, #d97706);
  background: var(--color-warning-subtle, #fffbeb);
  padding: 2px 6px;
  border-radius: 3px;
}
.stats-section {
  margin-top: 20px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  background: var(--color-canvas-default, #fff);
  border-radius: var(--r-card, 10px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
}
.stat-card-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--r-btn, 6px);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--color-fg-on-emphasis, #fff);
}
.stat-icon-tokens {
  background: var(--color-accent-fg, #2563eb);
}
.stat-icon-calls {
  background: var(--color-text-success, #16a34a);
}
.stat-icon-latency {
  background: var(--color-text-warning, #d97706);
}
.stat-icon-rate {
  background: var(--color-text-info, #378ADD);
}
.stat-card-info {
  flex: 1;
  min-width: 0;
}
.stat-card-value {
  font-size: 22px;
  font-weight: 500;
  color: var(--color-text-primary, #111);
  line-height: 1.2;
}
.stat-card-value small {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-text-tertiary, #888);
}
.stat-card-label {
  font-size: 12px;
  color: var(--color-text-secondary, #555);
  margin-top: 2px;
}
.chart-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}
.chart-label {
  font-size: 13px;
  color: var(--color-text-secondary, #555);
}
.chart-container {
  min-height: 300px;
}
.token-chart {
  width: 100%;
  height: 340px;
}
.audit-table {
  width: 100%;
}
.audit-detail {
  max-height: 65vh;
  overflow-y: auto;
}
.audit-section h4 {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary, #111);
  margin-bottom: 8px;
}
.audit-content {
  background: var(--color-canvas-subtle, #fafafa);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  padding: 12px;
  max-height: 400px;
  overflow-y: auto;
}
.audit-content.collapsed {
  max-height: 200px;
  overflow: hidden;
}
.audit-content pre {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-primary, #111);
  font-family: var(--font-mono, Consolas, monospace);
}
.empty-state {
  text-align: center;
  padding: 40px 0;
}
.page-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--color-text-primary, #111);
  display: flex;
  align-items: center;
  gap: 8px;
}
.page-subtitle {
  font-size: 12px;
  color: var(--color-fg-subtle, #888);
  margin-left: 8px;
  font-weight: 400;
}
.ollama-hint {
  margin-top: 8px;
}
.ollama-hint code {
  background: var(--color-canvas-inset, #f5f5f5);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
  color: var(--color-text-primary, #111);
  font-family: var(--font-mono, Consolas, monospace);
}
.prompt-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.prompt-textarea {
  width: 100%;
}
.prompt-optimize-btn {
  align-self: flex-end;
}
.opt-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary, #111);
}
.opt-current-prompt {
  background: var(--color-canvas-subtle, #fafafa);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  padding: 10px 12px;
  max-height: 150px;
  overflow-y: auto;
}
.opt-current-prompt pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-secondary, #555);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono, Consolas, monospace);
}
.opt-compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.opt-compare-col {
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  overflow: hidden;
}
.opt-compare-header {
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 500;
}
.opt-compare-header.old {
  background: var(--color-canvas-subtle, #fafafa);
  color: var(--color-text-secondary, #555);
}
.opt-compare-header.new {
  background: var(--color-success-subtle, #f0fdf4);
  color: var(--color-text-success, #16a34a);
}
.opt-compare-content {
  padding: 10px 12px;
  max-height: 250px;
  overflow-y: auto;
  background: var(--color-canvas-default, #fff);
}
.opt-compare-content pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-primary, #111);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono, Consolas, monospace);
}
.opt-history-bar {
  display: flex;
  align-items: center;
}
.opt-history-select {
  width: 240px;
}
.flex-center {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
}
.mb-5 { margin-bottom: 5px; }
.mb-10 { margin-bottom: 10px; }
.mb-15 { margin-bottom: 15px; }
.mb-20 { margin-bottom: 20px; }
.mt-5 { margin-top: 5px; }
.mt-10 { margin-top: 10px; }
.mt-15 { margin-top: 15px; }
.mt-20 { margin-top: 20px; }
.mr-5 { margin-right: 5px; }
.mr-10 { margin-right: 10px; }
.ml-10 { margin-left: 10px; }
.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.text-gray {
  font-size: 12px;
  color: var(--color-text-tertiary, #888);
}
</style>
