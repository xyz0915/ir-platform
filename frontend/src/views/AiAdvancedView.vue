<template>
  <div class="ai-adv-page">
    <div class="page-head">
      <h2>🧪 AI 实验室</h2>
      <span class="page-sub">高级关联功能 · 智能辅助分析与研判</span>
    </div>

    <el-tabs v-model="activeTab" class="ai-tabs">
      <!-- ===== Tab 1: 自然语言指挥台 ===== -->
      <el-tab-pane label="💬 自然语言指挥台" name="chat">
        <div class="chat-box">
          <div class="chat-msgs" ref="chatRef">
            <div v-for="(m, i) in chatMsgs" :key="i" :class="['msg', m.role]">
              <div class="msg-avatar">{{ m.role === 'user' ? '👤' : '🤖' }}</div>
              <div class="msg-bubble">
                <div class="msg-text" v-if="m.text">{{ m.text }}</div>
                <div class="msg-data" v-if="m.data">
                  <pre>{{ JSON.stringify(m.data, null, 2) }}</pre>
                </div>
              </div>
            </div>
            <div v-if="chatLoading" class="msg assistant">
              <div class="msg-avatar">🤖</div>
              <div class="msg-bubble thinking">思考中...</div>
            </div>
          </div>
          <div class="chat-input-row">
            <el-input v-model="chatInput" placeholder="输入问题，例如：严重的告警、统计信息、在线主机..." size="large"
              @keyup.enter="sendQuery" :disabled="chatLoading" clearable />
            <el-button type="primary" size="large" @click="sendQuery" :loading="chatLoading" style="margin-left:8px">提问</el-button>
          </div>
          <div class="chat-hints">
            <span>试试：</span>
            <el-tag size="small" effect="plain" style="cursor:pointer" @click="quickQuery('严重的告警')">严重的告警</el-tag>
            <el-tag size="small" effect="plain" style="cursor:pointer" @click="quickQuery('统计信息')">统计信息</el-tag>
            <el-tag size="small" effect="plain" style="cursor:pointer" @click="quickQuery('在线主机')">在线主机</el-tag>
            <el-tag size="small" effect="plain" style="cursor:pointer" @click="quickQuery('登录失败的日志')">登录失败的日志</el-tag>
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== Tab 2: 语义告警降噪 ===== -->
      <el-tab-pane label="📊 告警降噪" name="correlate">
        <div class="mb-16">
          <el-select v-model="corrHostId" placeholder="全部主机" clearable size="small" style="width:160px">
            <el-option v-for="h in hosts" :key="h.id" :label="h.hostname" :value="h.id" />
          </el-select>
          <el-button type="primary" size="small" @click="doCorrelate" :loading="corrLoading" style="margin-left:8px">🔄 执行归并</el-button>
          <span v-if="corrResult" style="margin-left:12px;font-size:12px;color:#059669">归并完成：{{ corrResult.length }} 起事件</span>
        </div>
        <el-table :data="corrResult" stripe border size="small" v-loading="corrLoading" style="width:100%">
          <el-table-column label="事件标题" min-width="200">
            <template #default="{row}"><span style="font-weight:500">{{ row.title }}</span></template>
          </el-table-column>
          <el-table-column label="严重度" width="80">
            <template #default="{row}"><el-tag :type="sevType(row.severity)" size="small">{{ row.severity }}</el-tag></template>
          </el-table-column>
          <el-table-column label="告警数" width="70" align="center">
            <template #default="{row}">{{ row.alert_count }}</template>
          </el-table-column>
          <el-table-column label="攻击阶段" width="120">
            <template #default="{row}"><el-tag size="small" :type="stageType(row.kill_chain)">{{ stageLabel(row.kill_chain) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="涉及主机" min-width="120">
            <template #default="{row}">{{ (row.host_ids||[]).join(', ') || '-' }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ===== Tab 3: 攻击故事 ===== -->
      <el-tab-pane label="📖 攻击故事" name="story">
        <div class="mb-16">
          <el-select v-model="storyHostId" placeholder="选择主机" clearable size="small" style="width:200px">
            <el-option v-for="h in hosts" :key="h.id" :label="h.hostname" :value="h.id" />
          </el-select>
          <el-button type="primary" size="small" @click="doNarrate" :loading="storyLoading" style="margin-left:8px">📖 生成故事</el-button>
        </div>
        <div v-if="storyText" class="story-box">
          <pre class="story-pre">{{ storyText }}</pre>
        </div>
        <div v-else class="empty-hint">选择主机后点击"生成故事"查看攻击时间线叙事</div>
      </el-tab-pane>

      <!-- ===== Tab 4: 预测预警 ===== -->
      <el-tab-pane label="🎯 预测预警" name="risk">
        <div class="mb-16">
          <el-button type="primary" size="small" @click="doRiskRank" :loading="riskLoading">🔄 刷新排行</el-button>
          <span v-if="riskData.length" style="margin-left:12px;font-size:12px;color:#6b7280">共 {{ riskTotal }} 台主机</span>
        </div>
        <el-table :data="riskData" stripe border size="small" v-loading="riskLoading" style="width:100%">
          <el-table-column type="index" label="#" width="50" />
          <el-table-column label="主机名" min-width="140">
            <template #default="{row}"><span style="font-weight:500">{{ row.hostname }}</span></template>
          </el-table-column>
          <el-table-column label="IP" width="120">
            <template #default="{row}">{{ row.ip || '-' }}</template>
          </el-table-column>
          <el-table-column label="风险评分" width="100" align="center">
            <template #default="{row}">
              <el-tag :type="riskTagType(row.risk_level)" size="medium" effect="dark">
                <strong>{{ row.risk_score }}</strong>
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="风险等级" width="100" align="center">
            <template #default="{row}">{{ riskLevelLabel(row.risk_level) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{row}">{{ row.status }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ===== Tab 5: 误报管理 ===== -->
      <el-tab-pane label="✅ 误报管理" name="fp">
        <div class="mb-16">
          <el-button size="small" @click="loadFPs" :loading="fpLoading">🔄 刷新</el-button>
          <span v-if="fpTotal" style="margin-left:12px;font-size:12px;color:#6b7280">共 {{ fpTotal }} 条误报模式</span>
        </div>
        <el-table :data="fpData" stripe border size="small" v-loading="fpLoading" style="width:100%">
          <el-table-column label="规则" min-width="160">
            <template #default="{row}">{{ row.rule_name || '-' }}</template>
          </el-table-column>
          <el-table-column label="进程" width="140">
            <template #default="{row}">{{ row.source_process || '-' }}</template>
          </el-table-column>
          <el-table-column label="主机ID" width="70">
            <template #default="{row}">{{ row.host_id || '-' }}</template>
          </el-table-column>
          <el-table-column label="原因" min-width="180">
            <template #default="{row}">{{ row.reason || '-' }}</template>
          </el-table-column>
          <el-table-column label="命中次数" width="80" align="center">
            <template #default="{row}">{{ row.hit_count || 0 }}</template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="{row}">
              <el-button link type="danger" size="small" @click="deleteFP(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  correlateIncidents, aiQuery, narrateIncident,
  getFalsePositives, deleteFalsePositive, getRiskRanking
} from '@/api/ai_advanced'

const activeTab = ref('chat')

// ===== Tab 1: 自然语言指挥台 =====
const chatInput = ref('')
const chatMsgs = ref([{ role: 'assistant', text: '你好！我是 AI 安全分析助手。你可以问我关于告警、日志、主机、统计等问题。\n例如：\n- "严重的告警"\n- "统计信息"\n- "在线主机"' }])
const chatLoading = ref(false)

async function sendQuery() {
  if (!chatInput.value.trim() || chatLoading.value) return
  const q = chatInput.value
  chatMsgs.value.push({ role: 'user', text: q })
  chatInput.value = ''
  chatLoading.value = true
  try {
    const res = await aiQuery(q)
    const d = res.data || {}
    const lines = [`📌 意图识别: ${d.intent}`, `📝 ${d.summary}`]
    chatMsgs.value.push({ role: 'assistant', text: lines.join('\n'), data: d.data })
  } catch (e) {
    chatMsgs.value.push({ role: 'assistant', text: '❌ 查询失败: ' + (e.message || '未知错误') })
  } finally {
    chatLoading.value = false
  }
}

function quickQuery(q) { chatInput.value = q; sendQuery() }

// ===== Tab 2: 告警降噪 =====
const corrHostId = ref(null)
const corrLoading = ref(false)
const corrResult = ref([])
async function doCorrelate() {
  corrLoading.value = true
  try {
    const params = {}
    if (corrHostId.value) params.host_id = corrHostId.value
    const res = await correlateIncidents(params)
    corrResult.value = res.data?.incidents || []
  } catch (e) { ElMessage.error('归并失败: ' + e.message) }
  finally { corrLoading.value = false }
}

// ===== Tab 3: 攻击故事 =====
const storyHostId = ref(null)
const storyLoading = ref(false)
const storyText = ref('')
async function doNarrate() {
  if (!storyHostId.value) { ElMessage.warning('请选择主机'); return }
  storyLoading.value = true
  try {
    const res = await narrateIncident({ host_id: storyHostId.value })
    storyText.value = res.data?.story || '暂无数据'
  } catch (e) { ElMessage.error('生成失败: ' + e.message) }
  finally { storyLoading.value = false }
}

// ===== Tab 4: 预测预警 =====
const riskLoading = ref(false)
const riskData = ref([])
const riskTotal = ref(0)
async function doRiskRank() {
  riskLoading.value = true
  try {
    const res = await getRiskRanking()
    const d = res.data || {}
    riskData.value = d.rankings || []
    riskTotal.value = d.total || 0
  } catch (e) { ElMessage.error('获取排行失败: ' + e.message) }
  finally { riskLoading.value = false }
}

// ===== Tab 5: 误报管理 =====
const fpLoading = ref(false)
const fpData = ref([])
const fpTotal = ref(0)
async function loadFPs() {
  fpLoading.value = true
  try {
    const res = await getFalsePositives()
    const d = res.data || {}
    fpData.value = d.items || []
    fpTotal.value = d.total || 0
  } catch (e) { ElMessage.error('加载失败: ' + e.message) }
  finally { fpLoading.value = false }
}
async function deleteFP(id) {
  try {
    await deleteFalsePositive(id)
    ElMessage.success('已删除')
    loadFPs()
  } catch (e) { ElMessage.error('删除失败') }
}

// ===== 辅助 =====
const hosts = ref([])
function sevType(s) { return { critical: 'danger', high: 'warning', medium: 'primary' }[s] || 'info' }
function stageType(s) { return { initial_access: 'danger', execution: 'warning', persistence: 'warning', credential_access: 'danger', lateral_movement: 'danger', exfiltration: 'danger', defense_evasion: 'danger' }[s] || 'info' }
function stageLabel(s) {
  const m = { recon: '侦察', initial_access: '初始入侵', execution: '代码执行', persistence: '持久化', credential_access: '凭据窃取', lateral_movement: '横向移动', exfiltration: '外连C2', defense_evasion: '防御绕过' }
  return m[s] || s || '通用'
}
function riskTagType(l) { return { critical: 'danger', high: 'warning', medium: 'primary' }[l] || 'info' }
function riskLevelLabel(l) { return { critical: '🚨 严重', high: '🟡 高危', medium: '🔵 中危', low: '⚪ 低危' }[l] || l || '-' }

onMounted(async () => {
  // 加载主机列表
  try {
    const { default: req } = await import('@/api/index')
    const res = await req.get('/agents/online-status')
    hosts.value = (res.data || []).map(h => ({ id: h.id, hostname: h.hostname }))
  } catch (_) {}
})
</script>

<style scoped>
.ai-adv-page { padding: 0; }
.page-head { margin-bottom: 8px; display: flex; align-items: baseline; gap: 8px; }
.page-head h2 { font-size: 18px; font-weight: 600; margin: 0; }
.page-sub { font-size: 12px; color: #6b7280; }

/* Chat */
.chat-box { border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }
.chat-msgs { padding: 16px; max-height: 400px; overflow-y: auto; background: #f9fafb; }
.msg { display: flex; gap: 10px; margin-bottom: 14px; }
.msg-avatar { font-size: 22px; flex-shrink: 0; margin-top: 2px; }
.msg-bubble { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 14px; max-width: 80%; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.msg.user .msg-bubble { background: #ecfdf5; border-color: #a7f3d0; }
.msg.assistant .msg-bubble { background: #fff; }
.msg-data pre { font-size: 11px; max-height: 200px; overflow-y: auto; background: #f3f4f6; padding: 8px; border-radius: 4px; margin-top: 6px; }
.thinking { color: #9ca3af; font-style: italic; }
.chat-input-row { display: flex; padding: 10px 12px; border-top: 1px solid #e5e7eb; }
.chat-hints { padding: 8px 12px; border-top: 1px solid #f3f4f6; font-size: 12px; color: #6b7280; display: flex; gap: 4px; align-items: center; flex-wrap: wrap; }

/* Story */
.story-box { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; max-height: 500px; overflow-y: auto; }
.story-pre { font-size: 13px; line-height: 1.7; white-space: pre-wrap; font-family: inherit; color: #1f2937; margin: 0; }

.empty-hint { text-align: center; padding: 40px; color: #9ca3af; font-size: 14px; }

.mb-16 { margin-bottom: 12px; }

.ai-tabs :deep(.el-tabs__header) { margin: 0 0 12px; }
</style>
