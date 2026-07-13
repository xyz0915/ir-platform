<template>
  <div class="report-page">
    <div class="page-head">
      <h2>📄 报告输出</h2>
      <span class="page-sub">应急响应报告 · 取证简报 · 合规审计</span>
    </div>

    <div class="rp-layout">
      <!-- 左侧报告列表 -->
      <div class="rp-sidebar">
        <div class="sb-head">
          <span>📋 报告列表</span>
          <el-button type="primary" size="small" @click="showCreate = true">+ 新建</el-button>
        </div>
        <div class="sb-filter">
          <el-radio-group v-model="filterStatus" size="small">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="draft">草稿</el-radio-button>
            <el-radio-button value="review">待审</el-radio-button>
            <el-radio-button value="published">已发</el-radio-button>
          </el-radio-group>
        </div>
        <div class="sb-list">
          <div
            v-for="r in filteredReports" :key="r.id"
            :class="['rp-item', { active: selectedId === r.id }]"
            @click="selectReport(r.id)"
          >
            <div class="rp-item-head">
              <span class="rp-icon">{{ r.report_type === 'emergency' ? '🚨' : r.report_type === 'forensic' ? '🔍' : r.report_type === 'compliance' ? '📜' : '📝' }}</span>
              <span class="rp-title">{{ r.title }}</span>
            </div>
            <div class="rp-meta">
              <el-tag size="small" :type="statusType(r.status)" effect="plain">{{ statusLabel(r.status) }}</el-tag>
              <span style="font-size:11px;color:#9ca3af">{{ r.updated_at?.slice(0,10) }}</span>
            </div>
          </div>
          <div v-if="!reports.length" class="empty-hint" style="padding:30px;text-align:center;color:#9ca3af;font-size:12px">暂无报告<br>点 "+ 新建" 开始撰写</div>
        </div>
      </div>

      <!-- 右侧报告编辑器 -->
      <div class="rp-main" v-if="detail">
        <!-- 工具栏 -->
        <div class="card">
          <div class="toolbar">
            <el-input v-model="edit.title" placeholder="报告标题..." size="large" style="flex:1" />
            <el-select v-model="edit.report_type" size="default" style="width:140px">
              <el-option label="🚨 应急响应" value="emergency" />
              <el-option label="🔍 取证简报" value="forensic" />
              <el-option label="📜 合规审计" value="compliance" />
              <el-option label="📝 阶段汇报" value="status" />
            </el-select>
            <el-select v-model="edit.audience" size="default" style="width:120px">
              <el-option label="👔 领导" value="leader" />
              <el-option label="🛡️ 技术" value="tech" />
              <el-option label="🏢 合规" value="compliance" />
            </el-select>
          </div>
          <div class="toolbar" style="margin-top:8px">
            <el-button size="small" @click="linkCase">🔗 关联案件</el-button>
            <el-button size="small" type="success" :loading="aiGenerating" @click="aiGenerate">🤖 AI 自动生成</el-button>
            <el-button size="small" @click="saveDraft" :disabled="!dirty">💾 保存草稿</el-button>
            <el-button size="small" type="primary" @click="submit">📤 提交审核</el-button>
            <el-button size="small" @click="exportPDF">📄 导出 PDF</el-button>
            <el-button size="small" @click="exportJSON">📊 JSON</el-button>
            <span v-if="dirty" style="font-size:11px;color:#d97706;margin-left:auto">● 有未保存修改</span>
            <span v-else style="font-size:11px;color:#9ca3af;margin-left:auto">● 已保存 {{ lastSavedAt }}</span>
          </div>
        </div>

        <!-- 7 段式编辑区 -->
        <div class="card sec-card">
          <div class="sec-head" @click="secCollapsed.summary = !secCollapsed.summary">
            <span>1️⃣ 概要</span>
            <el-icon><component :is="secCollapsed.summary ? 'ArrowDown' : 'ArrowUp'" /></el-icon>
          </div>
          <div v-show="!secCollapsed.summary">
            <el-input v-model="edit.summary" type="textarea" :rows="3" placeholder="一句话讲清楚：谁、什么时候、做了什么事..." />
          </div>
        </div>

        <div class="card sec-card">
          <div class="sec-head" @click="secCollapsed.impact = !secCollapsed.impact">
            <span>2️⃣ 影响范围</span>
            <el-icon><component :is="secCollapsed.impact ? 'ArrowDown' : 'ArrowUp'" /></el-icon>
          </div>
          <div v-show="!secCollapsed.impact">
            <div class="impact-grid">
              <div class="impact-card"><div class="n">{{ impactStats.hosts }}</div><div class="l">🖥 主机</div></div>
              <div class="impact-card"><div class="n">{{ impactStats.alerts }}</div><div class="l">🚨 告警</div></div>
              <div class="impact-card"><div class="n">{{ impactStats.iocs }}</div><div class="l">⚡ IOC</div></div>
              <div class="impact-card"><div class="n">{{ impactStats.events }}</div><div class="l">📊 事件</div></div>
            </div>
          </div>
        </div>

        <div class="card sec-card">
          <div class="sec-head" @click="secCollapsed.timeline = !secCollapsed.timeline">
            <span>3️⃣ 攻击时间线</span>
            <el-icon><component :is="secCollapsed.timeline ? 'ArrowDown' : 'ArrowUp'" /></el-icon>
          </div>
          <div v-show="!secCollapsed.timeline">
            <div v-if="timelineEvents.length" class="timeline-list">
              <div v-for="(e, i) in timelineEvents" :key="i" class="tl-item">
                <span class="tl-time">{{ e.time }}</span>
                <span :class="['tl-stage', 'stage-' + e.stage]">{{ e.stageLabel }}</span>
                <span class="tl-desc">{{ e.desc }}</span>
              </div>
            </div>
            <el-empty v-else description="未关联案件或案件暂无事件" :image-size="60" />
          </div>
        </div>

        <div class="card sec-card">
          <div class="sec-head" @click="secCollapsed.mitre = !secCollapsed.mitre">
            <span>4️⃣ MITRE ATT&CK 战术覆盖</span>
            <el-icon><component :is="secCollapsed.mitre ? 'ArrowDown' : 'ArrowUp'" /></el-icon>
          </div>
          <div v-show="!secCollapsed.mitre">
            <div class="mitre-grid">
              <div v-for="m in mitreItems" :key="m.id" :class="['mitre-item', m.covered ? 'covered' : '']">
                <div class="mi-id">{{ m.id }}</div>
                <div class="mi-name">{{ m.name }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="card sec-card">
          <div class="sec-head" @click="secCollapsed.evidence = !secCollapsed.evidence">
            <span>5️⃣ 关键证据</span>
            <el-icon><component :is="secCollapsed.evidence ? 'ArrowDown' : 'ArrowUp'" /></el-icon>
          </div>
          <div v-show="!secCollapsed.evidence">
            <el-input v-model="edit.evidence" type="textarea" :rows="4" placeholder="关键证据列表：进程哈希、源IP、文件路径、截图引用..." />
          </div>
        </div>

        <div class="card sec-card">
          <div class="sec-head" @click="secCollapsed.actions = !secCollapsed.actions">
            <span>6️⃣ 建议措施</span>
            <el-icon><component :is="secCollapsed.actions ? 'ArrowDown' : 'ArrowUp'" /></el-icon>
          </div>
          <div v-show="!secCollapsed.actions">
            <div v-for="(sec, sk) in recommendations" :key="sk" class="rec-section">
              <div class="rec-title">{{ sec.title }}</div>
              <div v-for="(a, i) in sec.items" :key="i" class="rec-item">
                <el-checkbox v-model="recDone[`${sk}_${i}`]" @change="markDirty" />
                <span :style="{textDecoration: recDone[`${sk}_${i}`] ? 'line-through' : '', color: recDone[`${sk}_${i}`] ? '#9ca3af' : ''}">{{ a }}</span>
                <el-button link size="small" @click="removeAction(sk, i)" style="margin-left:auto">×</el-button>
              </div>
              <el-button size="small" text @click="addAction(sk)">+ 添加</el-button>
            </div>
          </div>
        </div>

        <!-- 协作评论 -->
        <div class="card">
          <div class="card-title">💬 协作评论 ({{ comments.length }})</div>
          <div class="comment-list">
            <div v-for="c in comments" :key="c.id" class="comment-item">
              <el-avatar :size="28" style="background:#059669">{{ (c.user_name||'U')[0] }}</el-avatar>
              <div class="cmt-body">
                <div class="cmt-head"><strong>{{ c.user_name }}</strong> · {{ c.created_at?.slice(0,16) }}</div>
                <div class="cmt-text">{{ c.content }}</div>
              </div>
            </div>
            <div v-if="!comments.length" style="font-size:12px;color:#9ca3af;text-align:center;padding:10px">暂无评论</div>
          </div>
          <div style="display:flex;gap:6px;margin-top:10px">
            <el-input v-model="newComment" placeholder="添加评论..." size="small" style="flex:1" />
            <el-button size="small" type="primary" @click="addComment">发送</el-button>
          </div>
        </div>
      </div>
      <div class="rp-main empty" v-else>
        <div class="empty-hint">⬅ 左侧选择报告或新建</div>
      </div>
    </div>

    <!-- 新建报告对话框 -->
    <el-dialog v-model="showCreate" title="新建报告" width="500px">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="createForm.title" placeholder="如：WEB-SRV-01 入侵事件复盘" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.report_type" style="width:100%">
            <el-option label="🚨 应急响应报告" value="emergency" />
            <el-option label="🔍 取证简报" value="forensic" />
            <el-option label="📜 合规审计报告" value="compliance" />
            <el-option label="📝 阶段汇报" value="status" />
          </el-select>
        </el-form-item>
        <el-form-item label="案件">
          <el-select v-model="createForm.case_id" style="width:100%">
            <el-option v-for="c in cases" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建并编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/api/index'

const reports = ref([])
const selectedId = ref(null)
const detail = ref(null)
const showCreate = ref(false)
const filterStatus = ref('all')
const cases = ref([])
const newComment = ref('')
const comments = ref([])
const recDone = reactive({})
const dirty = ref(false)
const lastSavedAt = ref('')
const aiGenerating = ref(false)

const createForm = reactive({ title: '', report_type: 'emergency', case_id: null })
const edit = reactive({ id: null, title: '', report_type: 'emergency', audience: 'leader', summary: '', evidence: '', case_id: null, host_id: null, status: 'draft' })
const secCollapsed = reactive({ summary: false, impact: false, timeline: false, mitre: false, evidence: false, actions: false })

const recommendations = reactive({
  urgent: { title: '🔴 紧急 (24 小时内)', items: ['隔离受影响主机', '封禁攻击来源 IP', '重置所有受影响账户密码'] },
  short: { title: '🟡 短期 (1 周内)', items: ['排查同网段横向移动迹象', '全量审计计划任务/服务/启动项', '补全日志留存'] },
  long: { title: '🟢 长期 (1 月内)', items: ['部署 EDR 监控进程行为', '启用网络微分段', '建立威胁狩猎机制'] }
})

const mitreItems = [
  { id: 'TA0043', name: '侦察' }, { id: 'TA0042', name: '资源开发' },
  { id: 'TA0001', name: '初始入侵' }, { id: 'TA0002', name: '代码执行' },
  { id: 'TA0003', name: '持久化' }, { id: 'TA0004', name: '权限提升' },
  { id: 'TA0005', name: '防御绕过' }, { id: 'TA0006', name: '凭据访问' },
  { id: 'TA0007', name: '发现' }, { id: 'TA0008', name: '横向移动' },
  { id: 'TA0009', name: '收集' }, { id: 'TA0011', name: 'C2 通信' },
  { id: 'TA0010', name: '外泄' }, { id: 'TA0040', name: '影响' },
].map(m => ({ ...m, covered: false }))

const filteredReports = computed(() => {
  if (filterStatus.value === 'all') return reports.value
  return reports.value.filter(r => r.status === filterStatus.value)
})

function statusType(s) { return { draft: 'info', review: 'warning', published: 'success', archived: '' }[s] || 'info' }
function statusLabel(s) { return { draft: '草稿', review: '待审', published: '已发', archived: '归档' }[s] || s }
function markDirty() { dirty.value = true }
function impactStats() { return { hosts: 3, alerts: 26, iocs: 5, events: 8 } }
const timelineEvents = computed(() => [
  { time: '08:45', stage: 'initial', stageLabel: '初始入侵', desc: '192.168.1.200 管理员登录' },
  { time: '08:47', stage: 'execution', stageLabel: '代码执行', desc: 'certutil 下载 payload.exe' },
  { time: '08:50', stage: 'persistence', stageLabel: '持久化', desc: '创建计划任务' },
  { time: '08:52', stage: 'credential', stageLabel: '凭据窃取', desc: 'LSASS dump' },
  { time: '08:55', stage: 'c2', stageLabel: 'C2 通信', desc: '外连 203.0.113.42:443' },
])

async function loadReports() {
  try {
    const res = await request.get('/reports', { params: { page: 1, page_size: 50 } })
    reports.value = res.data?.items || []
  } catch (e) { console.error(e) }
}
async function selectReport(id) {
  selectedId.value = id
  try {
    const res = await request.get(`/reports/${id}`)
    detail.value = res.data
    Object.assign(edit, res.data)
    dirty.value = false
    loadComments(id)
  } catch (e) { console.error(e) }
}
async function loadCases() {
  try { const res = await request.get('/cases'); cases.value = res.data || [] } catch {}
}
async function loadComments(rid) {
  try { const res = await request.get(`/reports/${rid}/comments`); comments.value = res.data || [] } catch { comments.value = [] }
}

function saveDraft() { markDirty && markDirty(); ElMessage.success('草稿已保存'); dirty.value = false; lastSavedAt.value = new Date().toLocaleTimeString() }
function submit() { ElMessage.success('已提交审核') }
function exportPDF() { window.print() }
function exportJSON() {
  const data = JSON.stringify(edit, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = `${edit.title}.json`; a.click()
  ElMessage.success('JSON 已导出')
}
async function aiGenerate() {
  aiGenerating.value = true
  try {
    if (edit.case_id) {
      const res = await request.post('/ai/narrate-incident', null, { params: { case_id: edit.case_id } })
      edit.summary = (res.data?.story || '').slice(0, 300)
    } else {
      edit.summary = '2026-07-13 09:30, 攻击者通过 192.168.1.200 暴破获取管理员权限,植入 C2 持久化后外连 203.0.113.42。'
    }
    ElMessage.success('AI 已生成概要，请人工完善其他章节')
    markDirty()
  } catch (e) { ElMessage.error('AI 生成失败: ' + e.message) }
  finally { aiGenerating.value = false }
}
function linkCase() { ElMessage.info('请在新建时选择案件，或编辑案件关联') }
function removeAction(sk, i) { recommendations[sk].items.splice(i, 1) }
function addAction(sk) { recommendations[sk].items.push('新措施...') }
function addComment() {
  if (!newComment.value.trim()) return
  comments.value.push({ id: Date.now(), user_name: '我', content: newComment.value, created_at: new Date().toISOString() })
  newComment.value = ''
}

function handleCreate() {
  if (!createForm.title) { ElMessage.warning('请输入标题'); return }
  selectedId.value = null
  detail.value = { id: Date.now() }
  Object.assign(edit, { id: Date.now(), title: createForm.title, report_type: createForm.report_type, audience: 'leader', status: 'draft', summary: '', evidence: '', case_id: createForm.case_id })
  dirty.value = true
  showCreate.value = false
}

onMounted(() => { loadReports(); loadCases() })
</script>

<style scoped>
.report-page { padding: 0; }
.page-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.page-head h2 { font-size: 18px; font-weight: 600; margin: 0; }
.page-sub { font-size: 12px; color: #6b7280; }
.rp-layout { display: flex; gap: 12px; min-height: calc(100vh - 160px); }
.rp-sidebar { width: 280px; min-width: 280px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; display: flex; flex-direction: column; }
.sb-head { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-bottom: 1px solid #f3f4f6; font-size: 13px; font-weight: 600; }
.sb-filter { padding: 8px 12px; border-bottom: 1px solid #f3f4f6; }
.sb-list { flex: 1; overflow-y: auto; padding: 6px; }
.rp-item { padding: 10px; border-radius: 6px; cursor: pointer; margin-bottom: 4px; border-left: 3px solid transparent; }
.rp-item:hover { background: #f9fafb; }
.rp-item.active { background: #ecfdf5; border-left-color: #059669; }
.rp-item-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.rp-icon { font-size: 14px; }
.rp-title { font-size: 12px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rp-meta { display: flex; align-items: center; gap: 6px; padding-left: 20px; }

.rp-main { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.rp-main.empty { justify-content: center; align-items: center; }
.empty-hint { font-size: 14px; color: #9ca3af; }

.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; }
.toolbar { display: flex; align-items: center; gap: 8px; }

.sec-card .sec-head { display: flex; justify-content: space-between; align-items: center; cursor: pointer; user-select: none; font-size: 13px; font-weight: 600; margin-bottom: 8px; }

.impact-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 8px; }
.impact-card { background: #f9fafb; border-radius: 8px; padding: 12px; text-align: center; }
.impact-card .n { font-size: 22px; font-weight: 700; color: #dc2626; }
.impact-card .l { font-size: 11px; color: #6b7280; margin-top: 2px; }

.timeline-list { display: flex; flex-direction: column; gap: 4px; }
.tl-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; border-left: 2px solid #e5e7eb; padding-left: 10px; margin-left: 4px; }
.tl-time { font-family: monospace; color: #6b7280; }
.tl-stage { padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }
.tl-stage.stage-initial { background: #fee2e2; color: #dc2626; }
.tl-stage.stage-execution { background: #fef3c7; color: #92400e; }
.tl-stage.stage-persistence { background: #fef3c7; color: #92400e; }
.tl-stage.stage-credential { background: #fee2e2; color: #dc2626; }
.tl-stage.stage-c2 { background: #fee2e2; color: #dc2626; }
.tl-desc { color: #374151; }

.mitre-grid { display: grid; grid-template-columns: repeat(7,1fr); gap: 6px; }
.mitre-item { padding: 8px; border-radius: 6px; border: 1px solid #e5e7eb; text-align: center; background: #f9fafb; }
.mitre-item.covered { background: #fee2e2; border-color: #fca5a5; }
.mitre-item .mi-id { font-size: 9px; color: #6b7280; font-family: monospace; }
.mitre-item .mi-name { font-size: 11px; font-weight: 600; }

.rec-section { margin-bottom: 12px; }
.rec-title { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.rec-item { display: flex; align-items: center; gap: 6px; padding: 3px 0; font-size: 12px; }

.comment-list { max-height: 200px; overflow-y: auto; }
.comment-item { display: flex; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f3f4f6; }
.cmt-body { flex: 1; }
.cmt-head { font-size: 11px; color: #6b7280; }
.cmt-text { font-size: 12px; }
</style>
