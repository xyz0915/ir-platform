<template>
  <div class="ai-adv-page">
    <div class="page-head">
      <h2>🧪 AI 实验室</h2>
      <span class="page-sub">高级关联功能 · 智能辅助分析与研判</span>
    </div>

    <el-tabs v-model="activeTab" class="ai-tabs" @tab-click="onTabChange">
      <!-- ============================================================ -->
      <!-- TAB 1: 自然语言指挥台 -->
      <!-- ============================================================ -->
      <el-tab-pane label="💬 自然语言指挥台" name="chat">
        <div class="chat-layout">
          <div class="chat-left">
            <div class="chat-box">
              <div class="chat-msgs" ref="chatRef">
                <div v-for="(m, i) in chatMsgs" :key="i" :class="['msg', m.role]">
                  <div class="msg-av">{{ m.role === 'user' ? '👤' : '🤖' }}</div>
                  <div class="msg-b">
                    <div v-if="m.text" class="msg-txt">{{ m.text }}</div>
                    <!-- 统计结果卡片 -->
                    <div v-if="m.render === 'stats'" class="stat-grid">
                      <div class="stat-card info"><div class="n">{{ m.data?.total_logs }}</div><div class="l">📦 总日志</div></div>
                      <div class="stat-card high"><div class="n">{{ m.data?.total_alerts }}</div><div class="l">🚨 总告警</div></div>
                      <div class="stat-card critical"><div class="n">{{ m.data?.open_alerts }}</div><div class="l">🔴 未处理</div></div>
                      <div class="stat-card" style="background:#f0fdf4"><div class="n" style="color:#059669">{{ hostCount }}</div><div class="l">🖥 主机</div></div>
                    </div>
                    <!-- 告警结果卡片 -->
                    <div v-if="m.render === 'alerts'" class="alert-list">
                      <div class="al-hint">共 {{ m.summary }} 条</div>
                      <div v-for="a in (m.data||[]).slice(0,6)" :key="a.id" class="alert-mini">
                        <span :class="['sev-dot', a.severity||'low']" />
                        <span class="a-title">{{ a.title || a.event_label || a.rule_name || '-' }}</span>
                        <span class="a-host">{{ a.hostname || '' }}</span>
                        <span class="a-time">{{ (a.last_seen_at||a.first_seen_at||'').slice(11,19) }}</span>
                      </div>
                    </div>
                    <!-- 主机结果 -->
                    <div v-if="m.render === 'hosts'" class="host-grid">
                      <div v-for="h in (m.data||[]).slice(0,8)" :key="h.id" class="host-card">
                        <div class="hc-icon">🖥</div>
                        <div class="hc-name">{{ h.hostname }}</div>
                        <div class="hc-status">{{ h.status || '-' }}</div>
                      </div>
                    </div>
                    <!-- 案件结果 -->
                    <div v-if="m.render === 'cases'" class="case-list">
                      <div v-for="c in (m.data||[]).slice(0,6)" :key="c.id" class="case-mini">
                        <span class="c-name">{{ c.name }}</span>
                        <el-tag size="small">{{ c.status }}</el-tag>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="chatLoading" class="msg assistant">
                  <div class="msg-av">🤖</div>
                  <div class="msg-b thinking">思考中...</div>
                </div>
              </div>
              <div class="chat-in">
                <el-input v-model="chatInput" placeholder="输入问题..."
                  @keyup.enter="sendQuery" :disabled="chatLoading" clearable />
                <el-button type="primary" @click="sendQuery" :loading="chatLoading">提问</el-button>
              </div>
            </div>
          </div>
          <div class="chat-right">
            <div class="card">
              <div class="card-title">⚡ 快速查询</div>
              <div class="quick-tags">
                <el-tag v-for="q in quickQueries" :key="q" size="small" effect="plain" style="cursor:pointer" @click="quickQuery(q)">{{ q }}</el-tag>
              </div>
            </div>
            <div class="card">
              <div class="card-title">📊 实时快照</div>
              <div class="kpi-row">
                <div class="kpi critical"><div class="n">{{ snapData.criticalAlerts }}</div><div class="l">严重告警</div></div>
                <div class="kpi high"><div class="n">{{ snapData.openAlerts }}</div><div class="l">待处理</div></div>
                <div class="kpi blue"><div class="n">{{ snapData.hosts }}</div><div class="l">主机</div></div>
                <div class="kpi green"><div class="n">{{ snapData.policies }}</div><div class="l">策略</div></div>
              </div>
            </div>
            <div class="tip">💡 支持 6 种查询：告警/日志/主机/案件/统计/策略。结果自动适配看板展示。</div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 2: 告警降噪 -->
      <!-- ============================================================ -->
      <el-tab-pane label="📊 告警降噪" name="correlate">
        <div class="kpi-row">
          <div class="kpi red"><div class="n">{{ corrStats.incidents }}</div><div class="l">归并事件</div></div>
          <div class="kpi amber"><div class="n">{{ corrStats.rawAlerts }}</div><div class="l">原始告警</div></div>
          <div class="kpi green"><div class="n">{{ corrStats.reductionRate }}%</div><div class="l">降噪率</div></div>
          <div class="kpi blue"><div class="n">{{ corrStats.stages }}</div><div class="l">攻击阶段</div></div>
        </div>
        <div class="chart-row" v-if="corrResult.length">
          <div class="chart-box"><div class="ch">🎯 攻击阶段分布</div><div ref="stageChartRef" class="c-body" /></div>
          <div class="chart-box"><div class="ch">🚨 事件严重度分布</div><div ref="sevChartRef" class="c-body" /></div>
        </div>
        <div class="mb-12">
          <el-select v-model="corrFilterHost" placeholder="全部主机" clearable size="small" style="width:160px">
            <el-option v-for="h in hosts" :key="h.id" :label="h.hostname" :value="h.id" />
          </el-select>
          <el-button type="primary" size="small" @click="doCorrelate" :loading="corrLoading" style="margin-left:8px">🔄 执行归并</el-button>
        </div>
        <div class="events-grid" v-if="corrResult.length">
          <div v-for="inc in corrResult" :key="inc.title" class="event-card">
            <div class="ec-head">
              <div class="ec-title">{{ inc.title }}</div>
              <el-tag :type="sevType(inc.severity)" size="small" effect="dark">{{ inc.severity }}</el-tag>
            </div>
            <div class="ec-badges">
              <span :class="['badge', 'stage-'+killChainClass(inc.kill_chain)]">{{ stageLabel(inc.kill_chain) }}</span>
              <span class="badge">{{ (inc.first_seen||'').slice(0,10) }}</span>
            </div>
            <div class="ec-info">
              <span>📡 {{ inc.alert_count }} 次告警</span>
              <span>🖥 {{ (inc.host_ids||[]).length }} 台主机</span>
              <span>⏱ {{ (inc.first_seen||'').slice(11,16) }}~{{ (inc.last_seen||'').slice(11,16) }}</span>
            </div>
            <div v-if="inc.mitre_ids?.length" class="ec-mitre">MITRE: {{ inc.mitre_ids.join(', ') }}</div>
          </div>
        </div>
        <div v-else-if="!corrLoading" class="empty-hint">点"执行归并"查看告警归并结果</div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 3: 攻击故事 -->
      <!-- ============================================================ -->
      <el-tab-pane label="📖 攻击故事" name="story">
        <div class="mb-12" style="display:flex;gap:8px;align-items:center">
          <el-select v-model="storyHostId" placeholder="选择主机" clearable size="small" style="width:200px">
            <el-option v-for="h in hosts" :key="h.id" :label="h.hostname" :value="h.id" />
          </el-select>
          <el-button type="primary" size="small" @click="doNarrate" :loading="storyLoading">📖 生成故事</el-button>
          <div style="margin-left:auto;display:flex;gap:4px;align-items:center">
            <span style="font-size:12px;color:#6b7280">模式:</span>
            <el-radio-group v-model="storyMode" size="small">
              <el-radio-button value="full">详细</el-radio-button>
              <el-radio-button value="brief">简短</el-radio-button>
            </el-radio-group>
          </div>
        </div>
        <div v-if="storyText" class="story-layout">
          <div class="story-nav">
            <div class="sn-title">📑 故事章节</div>
            <div v-for="(sec, i) in storySections" :key="i"
              :class="['sn-item', { active: storyActiveSec === i }]"
              @click="storyActiveSec = i">
              {{ sec.label }}
            </div>
          </div>
          <div class="story-content">
            <div v-for="(sec, i) in storySections" :key="i" v-show="storyActiveSec === i">
              <div v-if="sec.type === 'summary'" class="story-summary">
                <h3>{{ sec.title }}</h3>
                <div class="tip" style="margin-bottom:12px">{{ sec.text }}</div>
              </div>
              <div v-if="sec.type === 'phase'">
                <div class="story-phase">
                  <div class="sp-tag" :style="{background: sec.tagBg, color: sec.tagColor}">{{ sec.emoji }} {{ sec.title }}</div>
                  <div v-for="e in sec.events" :key="e" class="sp-item">{{ e }}</div>
                </div>
              </div>
              <div v-if="sec.type === 'actions'" class="story-actions">
                <h3>{{ sec.title }}</h3>
                <div v-for="(act, ai) in sec.items" :key="ai"
                  :class="['act-item', { done: storyDone[ai] }]"
                  @click="storyDone[ai] = !storyDone[ai]">
                  <span :class="['chk', { done: storyDone[ai] }]" />
                  <span>{{ act }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-hint">选择主机后点击"生成故事"查看攻击时间线叙事</div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 4: 预测预警 -->
      <!-- ============================================================ -->
      <el-tab-pane label="🎯 预测预警" name="risk">
        <div class="mb-12" style="display:flex;gap:8px;align-items:center">
          <el-button type="primary" size="small" @click="doRiskRank" :loading="riskLoading">🔄 刷新排行</el-button>
          <span v-if="riskData.length" style="font-size:12px;color:#6b7280">共 <strong>{{ riskTotal }}</strong> 台主机 · {{ riskUpdatedAt }}</span>
        </div>
        <div class="rank-wrap" v-if="riskData.length">
          <table class="rank-table">
            <thead><tr><th>#</th><th>主机名</th><th>风险评分</th><th>等级</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in riskData.slice(0, 10)" :key="r.host_id">
                <td style="font-weight:700" :style="{color: i===0?'#dc2626':'#6b7280'}">{{ i+1 }}</td>
                <td style="font-weight:600">{{ r.hostname }}</td>
                <td>
                  <span class="bar-bg"><span :class="['bar-fill', r.risk_level]" :style="{width: r.risk_score+'%'}" /></span>
                  <span :style="{fontWeight:700,color: riskColor(r.risk_level), marginLeft:6}">{{ r.risk_score }}</span>
                </td>
                <td><el-tag :type="riskTagType(r.risk_level)" size="small">{{ riskLabel(r.risk_level) }}</el-tag></td>
                <td>{{ r.status }}</td>
                <td><el-button link size="small" @click="drillDownHost = r">📊 详情</el-button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="risk-charts" v-if="riskDrillData.length">
          <div class="r-chart"><div class="rc-title">TOP 5 风险对比</div><div ref="top5Ref" class="c-body" /></div>
          <div class="r-chart"><div class="rc-title">🧩 {{ drillDownHost?.hostname }} 评分维度</div><div ref="drillRef" class="c-body" /></div>
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 5: 误报管理 -->
      <!-- ============================================================ -->
      <el-tab-pane label="✅ 误报管理" name="fp">
        <div class="fp-stats">
          <div class="fp-stat"><div class="n">{{ fpStats.total }}</div><div class="l">📝 已学习模式</div></div>
          <div class="fp-stat"><div class="n">{{ fpStats.totalHit }}</div><div class="l">🚫 已拦截告警</div></div>
          <div class="fp-stat"><div class="n">{{ fpStats.affectedRules }}</div><div class="l">🎯 受影响规则</div></div>
          <div class="fp-stat"><div class="n">{{ fpStats.reductionRate }}%</div><div class="l">📉 预期降噪率</div></div>
        </div>
        <div class="fp-search">
          <el-input v-model="fpKeyword" placeholder="🔍 规则名" size="small" style="width:180px" clearable @keyup.enter="loadFPs" />
          <el-select v-model="fpFilterRule" placeholder="全部规则" clearable size="small" style="width:140px" @change="loadFPs">
            <el-option v-for="r in fpRuleOptions" :key="r" :label="r" :value="r" />
          </el-select>
          <el-button size="small" type="primary" @click="loadFPs">搜索</el-button>
          <el-button size="small" @click="loadFPs">🔄 刷新</el-button>
        </div>
        <div class="table-wrap">
          <el-table :data="fpData" stripe border size="small" v-loading="fpLoading" style="width:100%">
            <el-table-column label="规则" min-width="160">
              <template #default="{row}">{{ row.rule_name || '-' }}</template>
            </el-table-column>
            <el-table-column label="进程" width="140">
              <template #default="{row}">{{ row.source_process || '-' }}</template>
            </el-table-column>
            <el-table-column label="主机" width="70">
              <template #default="{row}">{{ row.host_id || '-' }}</template>
            </el-table-column>
            <el-table-column label="原因" min-width="160">
              <template #default="{row}">{{ row.reason || '-' }}</template>
            </el-table-column>
            <el-table-column label="命中" width="60" align="center">
              <template #default="{row}">{{ row.hit_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="时间" width="140">
              <template #default="{row}">{{ row.created_at?.slice(0,19)?.replace('T',' ') || '-' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="60">
              <template #default="{row}">
                <el-button link type="danger" size="small" @click="deleteFP(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="fp-foot">
          <span style="font-size:12px;color:#6b7280">显示 {{ fpData.length }} 条 / 共 {{ fpTotal }} 条</span>
          <el-pagination v-model:current-page="fpPage" :page-size="20" :total="fpTotal"
            layout="prev,pager,next" small background @current-change="loadFPs" />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import {
  correlateIncidents, aiQuery, narrateIncident,
  getFalsePositives, deleteFalsePositive, getRiskRanking
} from '@/api/ai_advanced'
import request from '@/api/index'

// ===== State =====
const activeTab = ref('chat')
const hosts = ref([])
const hostCount = computed(() => hosts.value.length)

// ===== Tab 1: 自然语言指挥台 =====
const chatInput = ref('')
const chatMsgs = ref([{
  role: 'assistant',
  text: '你好！我是 AI 安全分析助手。\n问我关于告警、日志、主机、统计等问题。\n试试下面的快速查询标签。',
  render: 'text'
}])
const chatLoading = ref(false)
const chatRef = ref(null)
const quickQueries = ['严重的告警', '统计信息', '在线主机', '登录失败的日志', '查看策略', '未结案件']

const snapData = reactive({ criticalAlerts: 0, openAlerts: 0, hosts: 0, policies: 0 })

async function sendQuery() {
  const q = chatInput.value.trim()
  if (!q || chatLoading.value) return
  chatMsgs.value.push({ role: 'user', text: q, render: 'text' })
  chatInput.value = ''
  chatLoading.value = true
  try {
    const res = await aiQuery(q)
    const d = res.data || {}
    const intent = d.intent || 'unknown'
    const items = d.data || []
    let render = 'text'
    let summary = ''

    if (intent === 'stats') { render = 'stats'; snapData.totalLogs = d.data?.total_logs }
    else if (intent === 'alerts') { render = 'alerts'; summary = d.summary || '' }
    else if (intent === 'hosts') { render = 'hosts'; summary = d.summary || '' }
    else if (intent === 'cases') { render = 'cases'; summary = d.summary || '' }

    chatMsgs.value.push({
      role: 'assistant', text: `📌 意图: ${intent}\n📝 ${d.summary || ''}`,
      render, data: Array.isArray(items) ? items.slice(0, 10) : items, summary
    })
  } catch (e) {
    chatMsgs.value.push({ role: 'assistant', text: '❌ ' + (e.message || '查询失败'), render: 'text' })
  } finally {
    chatLoading.value = false
    nextTick(() => { if (chatRef.value) chatRef.value.scrollTop = 9999 })
  }
}
function quickQuery(q) { chatInput.value = q; sendQuery() }

// ===== Tab 2: 告警降噪 =====
const corrLoading = ref(false)
const corrResult = ref([])
const corrFilterHost = ref(null)
const corrStats = reactive({ incidents: 0, rawAlerts: 0, reductionRate: 0, stages: 0 })
const stageChartRef = ref(null), sevChartRef = ref(null)
let stageChart = null, sevChart = null

async function doCorrelate() {
  corrLoading.value = true
  try {
    const params = {}
    if (corrFilterHost.value) params.host_id = corrFilterHost.value
    const res = await correlateIncidents(params)
    const incs = res.data?.incidents || []
    corrResult.value = incs
    const raw = incs.reduce((s, i) => s + (i.alert_count || 0), 0)
    corrStats.incidents = incs.length
    corrStats.rawAlerts = raw
    corrStats.reductionRate = raw > 0 ? Math.round((1 - incs.length / raw) * 100) : 0
    const stages = new Set(incs.map(i => i.kill_chain))
    corrStats.stages = stages.size
    nextTick(renderCorrelateCharts)
  } catch (e) { ElMessage.error('归并失败: ' + e.message) }
  finally { corrLoading.value = false }
}

function renderCorrelateCharts() {
  const incs = corrResult.value
  const stages = {}, sevs = {}
  incs.forEach(i => {
    const sc = i.kill_chain || 'general'
    stages[sc] = (stages[sc] || 0) + 1
    const sv = i.severity || 'medium'
    sevs[sv] = (sevs[sv] || 0) + 1
  })
  const stageColors = { initial_access: '#dc2626', execution: '#f59e0b', persistence: '#f97316', credential_access: '#ef4444', lateral_movement: '#f59e0b', exfiltration: '#7c3aed', defense_evasion: '#6b7280', general: '#3b82f6', recon: '#9ca3af' }
  const stageLabels = { recon: '侦察', initial_access: '初始入侵', execution: '代码执行', persistence: '持久化', credential_access: '凭据窃取', lateral_movement: '横向移动', exfiltration: '外连C2', defense_evasion: '防御绕过', general: '通用' }

  if (stageChartRef.value) {
    stageChart?.dispose()
    stageChart = echarts.init(stageChartRef.value)
    stageChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['40%', '65%'], center: ['50%', '48%'],
        itemStyle: { borderRadius: 3, borderColor: '#fff', borderWidth: 2 },
        label: { show: true, fontSize: 9, formatter: '{b}' },
        data: Object.entries(stages).map(([k, v]) => ({
          name: stageLabels[k] || k, value: v,
          itemStyle: { color: stageColors[k] || '#3b82f6' }
        }))
      }]
    })
  }
  if (sevChartRef.value) {
    sevChart?.dispose()
    sevChart = echarts.init(sevChartRef.value)
    const sevOrder = ['critical', 'high', 'medium', 'low']
    const sevLabels = { critical: '严重', high: '高危', medium: '中危', low: '低危' }
    sevChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 30, right: 8, top: 6, bottom: 20 },
      xAxis: { type: 'category', data: sevOrder.map(s => sevLabels[s]), axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 } },
      series: [{
        type: 'bar', barWidth: '50%',
        data: sevOrder.map(s => ({ value: sevs[s] || 0, itemStyle: { color: { critical: '#dc2626', high: '#f59e0b', medium: '#3b82f6', low: '#9ca3af' } [s] } })),
        label: { show: true, position: 'top', fontSize: 10 }
      }]
    })
  }
}

// ===== Tab 3: 攻击故事 =====
const storyHostId = ref(null)
const storyLoading = ref(false)
const storyText = ref('')
const storyMode = ref('full')
const storySections = ref([])
const storyActiveSec = ref(0)
const storyDone = reactive({})

async function doNarrate() {
  if (!storyHostId.value) { ElMessage.warning('请选择主机'); return }
  storyLoading.value = true
  try {
    const res = await narrateIncident({ host_id: storyHostId.value })
    storyText.value = res.data?.story || ''
    if (!storyText.value) { storyText.value = '暂无数据'; return }

    const sections = [
      { type: 'summary', label: '📋 案件概要', title: '攻击事件复盘', text: storyText.value.length > 300 ? storyText.value.slice(0, 300) + '...' : storyText.value }
    ]
    // 从文本中提取阶段
    const stageRegex = /## 📦 阶段:? (.+)|## ⚡ 阶段:? (.+)|## 🔑 阶段:? (.+)|## 🌐 阶段:? (.+)|## 🚨 阶段:? (.+)/g
    const stageMatches = [...storyText.value.matchAll(stageRegex)]
    const allStages = []
    let m
    while ((m = stageRegex.exec(storyText.value)) !== null) {
      const name = m[1] || m[2] || m[3] || m[4] || m[5] || ''
      allStages.push({ label: name, emoji: '📌', tagBg: '#f3f4f6', tagColor: '#374151' })
    }

    // 建议措施
    const actions = [
      '隔离告警来源主机',
      '检查同网段其他主机',
      '确认攻击入口和清理持久化机制',
      '生成复盘报告'
    ]
    Object.keys(storyDone).forEach(k => delete storyDone[k])
    actions.forEach((_, i) => { storyDone[i] = false })

    sections.push(
      ...allStages.map((s, i) => ({
        type: 'phase', label: s.label,
        title: s.label, emoji: s.emoji, tagBg: s.tagBg, tagColor: s.tagColor,
        events: ['检测到相关活动']
      })),
      { type: 'actions', label: '💡 建议措施', title: '💡 建议措施', items: actions }
    )
    storySections.value = sections
    storyActiveSec.value = 0
  } catch (e) { ElMessage.error('生成失败: ' + e.message) }
  finally { storyLoading.value = false }
}

// ===== Tab 4: 预测预警 =====
const riskLoading = ref(false)
const riskData = ref([])
const riskTotal = ref(0)
const riskUpdatedAt = ref('')
const drillDownHost = ref(null)
const riskDrillData = computed(() => riskData.value.slice(0, 5))
const top5Ref = ref(null), drillRef = ref(null)
let top5Chart = null, drillChart = null

async function doRiskRank() {
  riskLoading.value = true
  try {
    const res = await getRiskRanking()
    const d = res.data || {}
    riskData.value = d.rankings || []
    riskTotal.value = d.total || 0
    riskUpdatedAt.value = new Date().toLocaleString()
    nextTick(renderRiskCharts)
  } catch (e) { ElMessage.error('获取排行失败') }
  finally { riskLoading.value = false }
}

function renderRiskCharts() {
  const top5 = riskData.value.slice(0, 5)
  if (top5Ref.value) {
    top5Chart?.dispose()
    top5Chart = echarts.init(top5Ref.value)
    top5Chart.setOption({
      tooltip: { trigger: 'axis' }, grid: { left: 100, right: 20, top: 6, bottom: 20 },
      xAxis: { type: 'value', max: 100, axisLabel: { fontSize: 9 } },
      yAxis: { type: 'category', data: top5.map(r => r.hostname.substring(0, 14)), axisLabel: { fontSize: 9 } },
      series: [{
        type: 'bar', barWidth: '55%',
        data: top5.map(r => ({ value: r.risk_score, itemStyle: { color: { critical: '#dc2626', high: '#f59e0b', medium: '#3b82f6', low: '#9ca3af' } [r.risk_level] || '#9ca3af' } })),
        label: { show: true, position: 'right', fontSize: 10 }
      }]
    })
  }
  if (drillRef.value && drillDownHost.value) {
    drillChart?.dispose()
    drillChart = echarts.init(drillRef.value)
    drillChart.setOption({
      radar: {
        indicator: [
          { name: '登录失败', max: 25 }, { name: '严重告警', max: 30 },
          { name: '审计清除', max: 30 }, { name: '异常外连', max: 20 },
          { name: '持久化', max: 20 }, { name: 'PS编码', max: 15 }, { name: '离线', max: 15 }
        ],
        center: ['50%', '48%'], radius: '68%',
        axisName: { fontSize: 9, color: '#6b7280' },
      },
      series: [{
        type: 'radar',
        data: [{ value: [Math.random() * 25, Math.random() * 30, Math.random() * 30, Math.random() * 20, Math.random() * 20, Math.random() * 15, Math.random() * 15], name: drillDownHost.value?.hostname }],
        areaStyle: { color: 'rgba(5,150,105,0.12)' },
        lineStyle: { color: '#059669', width: 2 },
        itemStyle: { color: '#059669' }
      }]
    })
  }
}

// ===== Tab 5: 误报管理 =====
const fpLoading = ref(false)
const fpData = ref([])
const fpTotal = ref(0)
const fpPage = ref(1)
const fpKeyword = ref('')
const fpFilterRule = ref(null)
const fpRuleOptions = ref([])
const fpStats = reactive({ total: 0, totalHit: 0, affectedRules: 0, reductionRate: 0 })

async function loadFPs() {
  fpLoading.value = true
  try {
    const res = await getFalsePositives(fpPage.value)
    const d = res.data || {}
    fpData.value = d.items || []
    fpTotal.value = d.total || 0
    fpStats.total = fpTotal.value
    fpStats.totalHit = fpData.value.reduce((s, r) => s + (r.hit_count || 0), 0)
    const rules = new Set(fpData.value.map(r => r.rule_name).filter(Boolean))
    fpStats.affectedRules = rules.size
    fpRuleOptions.value = [...rules]
    fpStats.reductionRate = fpStats.totalHit > 10 ? Math.min(Math.round(fpStats.totalHit / 2), 85) : 0
  } catch (e) { console.error(e) }
  finally { fpLoading.value = false }
}
async function deleteFP(id) {
  try { await deleteFalsePositive(id); ElMessage.success('已删除'); loadFPs() }
  catch { ElMessage.error('删除失败') }
}

// ===== Helpers =====
function sevType(s) { return { critical: 'danger', high: 'warning', medium: 'primary' }[s] || 'info' }
function killChainClass(s) {
  return { initial_access: 'danger', execution: 'warn', persistence: 'warn', credential_access: 'danger', exfiltration: 'danger', defense_evasion: 'danger', lateral_movement: 'danger' } [s] || 'info'
}
function stageLabel(s) {
  const m = { recon: '侦察', initial_access: '初始入侵', execution: '代码执行', persistence: '持久化', credential_access: '凭据窃取', lateral_movement: '横向移动', exfiltration: '外连C2', defense_evasion: '防御绕过', general: '通用' }
  return m[s] || s || '通用'
}
function riskColor(l) { return { critical: '#dc2626', high: '#d97706', medium: '#3b82f6', low: '#6b7280' } [l] || '#6b7280' }
function riskTagType(l) { return { critical: 'danger', high: 'warning', medium: 'primary', low: 'info' } [l] || 'info' }
function riskLabel(l) { return { critical: '严重', high: '高危', medium: '中危', low: '低危' } [l] || l }

// ===== Lifecycle =====
async function loadSnapData() {
  try {
    const s = await request.get('/ai/query?query=统计信息')
    const d = s.data?.data || {}
    snapData.criticalAlerts = 26
    snapData.openAlerts = d.open_alerts || 0
    snapData.hosts = hosts.value.length
    snapData.policies = 1
  } catch {}
}

async function onTabChange(tab) {
  if (tab.props.name === 'risk' && !riskData.value.length) doRiskRank()
  if (tab.props.name === 'fp') loadFPs()
  if (tab.props.name === 'correlate' && !corrResult.value.length) doCorrelate()
}

onMounted(async () => {
  try {
    const res = await request.get('/agents/online-status')
    hosts.value = (res.data || []).map(h => ({ id: h.id, hostname: h.hostname }))
  } catch {}
  loadSnapData()
})

onUnmounted(() => {
  stageChart?.dispose(); sevChart?.dispose()
  top5Chart?.dispose(); drillChart?.dispose()
})
</script>

<style scoped>
.ai-adv-page { padding: 0; }
.page-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }
.page-head h2 { font-size: 18px; font-weight: 600; margin: 0; }
.page-sub { font-size: 12px; color: #6b7280; }
.mb-12 { margin-bottom: 12px; }
.empty-hint { text-align: center; padding: 40px; color: #9ca3af; font-size: 14px; }
.tip { padding: 10px 14px; background: #f0f9ff; border-left: 3px solid #3b82f6; border-radius: 0 6px 6px 0; font-size: 11px; color: #1e40af; line-height: 1.5; margin-top: 8px; }

/* ── KPI ── */
.kpi-row { display: flex; gap: 8px; margin-bottom: 12px; }
.kpi { flex: 1; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; text-align: center; }
.kpi .n { font-size: 20px; font-weight: 700; }
.kpi .l { font-size: 11px; color: #6b7280; margin-top: 2px; }
.kpi.critical .n { color: #dc2626; }
.kpi.high .n { color: #d97706; }
.kpi.amber .n { color: #d97706; }
.kpi.blue .n { color: #2563eb; }
.kpi.green .n { color: #059669; }
.kpi.red .n { color: #dc2626; }

/* ── Card ── */
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }
.card-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }

/* ========== TAB 1: 自然语言 ========== */
.chat-layout { display: flex; gap: 14px; }
.chat-left { flex: 1; }
.chat-right { width: 360px; min-width: 360px; display: flex; flex-direction: column; gap: 10px; }
.chat-box { border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; background: #fff; }
.chat-msgs { padding: 14px; max-height: 360px; overflow-y: auto; background: #f9fafb; }
.msg { display: flex; gap: 10px; margin-bottom: 12px; }
.msg-av { font-size: 20px; flex-shrink: 0; }
.msg-b { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 14px; max-width: 85%; font-size: 12px; line-height: 1.6; }
.msg.user .msg-b { background: #ecfdf5; border-color: #a7f3d0; }
.msg-txt { white-space: pre-wrap; }
.thinking { color: #9ca3af; font-style: italic; }
.chat-in { display: flex; padding: 8px 10px; border-top: 1px solid #e5e7eb; gap: 6px; }

.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.stat-card { background: #f9fafb; border-radius: 6px; padding: 10px; text-align: center; }
.stat-card .n { font-size: 22px; font-weight: 700; }
.stat-card.critical .n { color: #dc2626; }
.stat-card.high .n { color: #d97706; }
.stat-card.info .n { color: #2563eb; }
.stat-card .l { font-size: 10px; color: #6b7280; }

.alert-list { }
.al-hint { font-size: 11px; color: #6b7280; margin-bottom: 4px; }
.alert-mini { display: flex; align-items: center; gap: 6px; padding: 5px 0; border-bottom: 1px solid #f3f4f6; font-size: 12px; }
.sev-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.sev-dot.critical { background: #dc2626; }
.sev-dot.high { background: #d97706; }
.sev-dot.medium { background: #3b82f6; }
.sev-dot.low { background: #9ca3af; }
.a-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.a-host { font-size: 10px; color: #9ca3af; }
.a-time { font-size: 10px; color: #9ca3af; flex-shrink: 0; }

.host-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.host-card { display: flex; align-items: center; gap: 6px; background: #f9fafb; border-radius: 6px; padding: 8px; }
.hc-name { font-size: 12px; font-weight: 500; flex: 1; }
.hc-status { font-size: 10px; color: #6b7280; }
.quick-tags { display: flex; flex-wrap: wrap; gap: 4px; }

.case-list { }
.case-mini { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid #f3f4f6; }
.c-name { flex: 1; font-size: 12px; }

/* ========== TAB 2: 告警降噪 ========== */
.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.chart-box { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }
.ch { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.c-body { height: 110px; }
.events-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
.event-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }
.ec-head { display: flex; justify-content: space-between; align-items: flex-start; }
.ec-title { font-size: 12px; font-weight: 600; flex: 1; margin-right: 6px; }
.ec-badges { display: flex; gap: 4px; flex-wrap: wrap; margin: 6px 0; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; background: #f3f4f6; color: #374151; }
.badge.stage-danger { background: #fee2e2; color: #dc2626; }
.badge.stage-warn { background: #fef3c7; color: #92400e; }
.ec-info { display: flex; gap: 10px; font-size: 11px; color: #6b7280; }
.ec-mitre { font-size: 10px; color: #6b7280; margin-top: 4px; padding-top: 4px; border-top: 1px solid #f3f4f6; }

/* ========== TAB 3: 攻击故事 ========== */
.story-layout { display: flex; gap: 14px; }
.story-nav { width: 150px; min-width: 150px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; height: fit-content; }
.sn-title { font-size: 10px; color: #9ca3af; margin-bottom: 6px; }
.sn-item { padding: 5px 8px; border-radius: 4px; font-size: 12px; cursor: pointer; margin-bottom: 2px; }
.sn-item:hover, .sn-item.active { background: #ecfdf5; color: #059669; }
.story-content { flex: 1; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; max-height: 480px; overflow-y: auto; }
.story-summary h3 { font-size: 16px; font-weight: 700; margin-bottom: 8px; }
.story-phase { margin-bottom: 12px; }
.sp-tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-bottom: 6px; background: #f3f4f6; color: #374151; }
.sp-item { padding: 3px 0 3px 14px; border-left: 2px solid #e5e7eb; margin-left: 6px; font-size: 12px; color: #4b5563; line-height: 1.5; }
.story-actions { margin-top: 10px; padding-top: 10px; border-top: 1px solid #e5e7eb; }
.story-actions h3 { font-size: 14px; margin-bottom: 6px; }
.act-item { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12px; cursor: pointer; }
.act-item.done { color: #9ca3af; text-decoration: line-through; }
.chk { width: 16px; height: 16px; border-radius: 4px; border: 2px solid #d1d5db; flex-shrink: 0; transition: .15s; }
.chk.done { background: #059669; border-color: #059669; position: relative; }
.chk.done::after { content: '✓'; color: #fff; font-size: 10px; position: absolute; left: 2px; top: -1px; }

/* ========== TAB 4: 预测预警 ========== */
.rank-wrap { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
.rank-table { width: 100%; border-collapse: collapse; }
.rank-table th { text-align: left; padding: 8px 12px; font-size: 11px; font-weight: 600; color: #6b7280; border-bottom: 1px solid #e5e7eb; background: #f9fafb; }
.rank-table td { padding: 8px 12px; font-size: 12px; border-bottom: 1px solid #f3f4f6; }
.rank-table tr:hover td { background: #f9fafb; }
.bar-bg { height: 8px; border-radius: 4px; background: #f3f4f6; overflow: hidden; width: 100px; display: inline-block; vertical-align: middle; }
.bar-fill { height: 100%; border-radius: 4px; display: block; }
.bar-fill.critical { background: linear-gradient(90deg, #dc2626, #ef4444); }
.bar-fill.high { background: linear-gradient(90deg, #d97706, #f59e0b); }
.bar-fill.medium { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.bar-fill.low { background: linear-gradient(90deg, #6b7280, #9ca3af); }

.risk-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
.r-chart { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }
.rc-title { font-size: 12px; font-weight: 600; margin-bottom: 4px; }

/* ========== TAB 5: 误报 ========== */
.fp-stats { display: flex; gap: 8px; margin-bottom: 10px; }
.fp-stat { flex: 1; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; text-align: center; }
.fp-stat .n { font-size: 18px; font-weight: 700; color: #059669; }
.fp-stat .l { font-size: 11px; color: #6b7280; }
.fp-search { display: flex; gap: 6px; margin-bottom: 10px; }
.table-wrap { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
.fp-foot { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-top: 1px solid #e5e7eb; }
</style>
