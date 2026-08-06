<template>
  <div class="nl-panel">
    <!-- ═══ Header ═══ -->
    <div class="nl-hdr">
      <div class="nl-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="13" x2="13" y2="13"/></svg>
        自然语言检索
      </div>
      <div class="nl-sub">用中文描述你想查的日志，例如「查一下昨天来自 1.2.3.4 的高危登录失败」</div>
    </div>

    <!-- ═══ Input ═══ -->
    <div class="nl-input-row">
      <textarea
        v-model="nlText"
        class="nl-input"
        rows="2"
        maxlength="200"
        placeholder="输入自然语言检索需求…（Ctrl+Enter 检索，≤200 字）"
        @keydown.ctrl.enter="runSearch"
      ></textarea>
      <div class="nl-btn-group">
        <button class="btn btn-ghost nl-btn" :disabled="loading" @click="runPreview">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
          仅预览
        </button>
        <button class="btn btn-primary nl-btn" :disabled="loading" @click="runSearch">
          <svg v-if="!loading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
          {{ loading ? '检索中…' : '智能检索' }}
        </button>
      </div>
    </div>
    <div class="nl-char-count" v-if="nlText.length > 180">{{ nlText.length }}/200</div>

    <!-- ═══ 查询计划（P0-3 可审计可纠错）═══ -->
    <div v-if="queryPlan" class="nl-plan">
      <div class="nl-plan-hdr">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
        查询计划
        <span v-if="preview" class="nl-plan-preview-badge">预览（未查库）</span>
        <span v-if="auditId" class="nl-audit">审计 ID: {{ auditId }}</span>
      </div>
      <div class="nl-plan-body">
        <div v-if="queryPlan.sql_conditions && queryPlan.sql_conditions.length" class="nl-plan-list">
          <div class="nl-plan-item" v-for="(c, i) in queryPlan.sql_conditions" :key="i">
            <code>{{ c.field }}</code>
            <span class="nl-plan-op">{{ c.op || 'contains' }}</span>
            <code>{{ fmtCondValue(c.value) }}</code>
          </div>
        </div>
        <div v-else class="nl-plan-empty">无结构化条件（泛泛检索，按时间倒序返回）</div>
        <div class="nl-plan-meta">
          时间范围: {{ fmtTimeRange(queryPlan.time_range) }} · 排序: {{ queryPlan.sort }} · 每页: {{ queryPlan.page_size }}
        </div>
        <div v-if="queryPlan.degraded && queryPlan.degraded.length" class="nl-plan-degraded">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          降级提示：{{ queryPlan.degraded.join('；') }}
        </div>
      </div>
    </div>

    <!-- ═══ AI 摘要 ═══ -->
    <div v-if="summary" class="nl-summary">
      <div class="nl-summary-label">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/><path d="M9 21h6"/></svg>
        AI 摘要
      </div>
      <div class="nl-summary-body">{{ summary }}</div>
    </div>

    <!-- ═══ 错误 ═══ -->
    <div v-if="error" class="nl-error">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ error }}
    </div>

    <!-- ═══ 结果表格 ═══ -->
    <div v-if="rows.length" class="nl-result">
      <div class="nl-result-meta">
        <span>共 <b>{{ total }}</b> 条（脱敏展示）</span>
        <span v-if="auditId" class="nl-audit">审计 ID: {{ auditId }}</span>
      </div>
      <div class="nl-table-wrap">
        <table class="nl-table">
          <thead>
            <tr>
              <th v-for="col in columns" :key="col" :title="col">{{ col }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in rows" :key="i">
              <td v-for="col in columns" :key="col" :title="formatCell(row[col])">{{ formatCell(row[col]) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { nlLogSearch } from '@/api/logs'

const nlText = ref('')
const loading = ref(false)
const summary = ref('')
const error = ref('')
const columns = ref([])
const rows = ref([])
const total = ref(0)
const auditId = ref(null)
const queryPlan = ref(null)
const preview = ref(false)

function formatCell(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function fmtCondValue(v) {
  if (Array.isArray(v)) return v.join(', ')
  return formatCell(v)
}

function fmtTimeRange(tr) {
  if (!tr || (!tr.from && !tr.to)) return '不限'
  const from = tr.from || '起点'
  const to = tr.to || '现在'
  return `${from} ~ ${to}`
}

function applyResult(d) {
  columns.value = d.columns || []
  rows.value = d.rows || []
  summary.value = d.summary || ''
  total.value = d.total || rows.value.length
  auditId.value = d.audit_id || null
  queryPlan.value = d.query_plan || null
  preview.value = !!d.preview
}

async function runSearch() {
  const text = nlText.value.trim()
  if (!text) {
    ElMessage.warning('请输入检索需求')
    return
  }
  loading.value = true
  error.value = ''
  summary.value = ''
  rows.value = []
  columns.value = []
  auditId.value = null
  queryPlan.value = null
  preview.value = false
  try {
    const resp = await nlLogSearch({ nl_text: text })
    // resp: {code, data, message}
    if (resp && resp.code === 0 && resp.data) {
      applyResult(resp.data)
      if (!rows.value.length && !queryPlan.value) {
        ElMessage.info('未检索到匹配日志')
      }
    } else {
      error.value = (resp && resp.message) || '检索失败'
    }
  } catch (err) {
    error.value = '检索失败：' + (err.message || '未知错误')
  } finally {
    loading.value = false
  }
}

/** 仅预览：不查库，返回查询计划（可审计可纠错）。 */
async function runPreview() {
  const text = nlText.value.trim()
  if (!text) {
    ElMessage.warning('请输入检索需求')
    return
  }
  loading.value = true
  error.value = ''
  summary.value = ''
  rows.value = []
  columns.value = []
  try {
    const resp = await nlLogSearch({ nl_text: text, preview_only: true })
    if (resp && resp.code === 0 && resp.data) {
      applyResult(resp.data)
      ElMessage.success('已生成查询计划（未查库）')
    } else {
      error.value = (resp && resp.message) || '预览失败'
    }
  } catch (err) {
    error.value = '预览失败：' + (err.message || '未知错误')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* ═══════ IR Design System — NL Search Panel ═══════ */
.nl-panel {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-container, 12px);
  padding: 16px 18px;
  margin-bottom: 16px;
}
.nl-hdr {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}
.nl-title {
  font-size: 15px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-fg-default);
}
.nl-title svg {
  width: 16px;
  height: 16px;
  color: var(--color-accent-fg);
}
.nl-sub {
  font-size: 12px;
  color: var(--color-fg-subtle);
}
.nl-input-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}
.nl-btn-group {
  display: flex;
  gap: 6px;
  align-items: stretch;
}
.nl-char-count {
  margin-top: 4px;
  font-size: 11px;
  color: var(--color-fg-light);
  text-align: right;
}
.nl-input {
  flex: 1;
  height: auto;
  min-height: 52px;
  padding: 8px 12px;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default);
  font-size: 13px;
  font-family: inherit;
  line-height: 1.6;
  outline: none;
  resize: vertical;
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  transition: border-color 0.12s;
}
.nl-input:focus {
  border-color: var(--color-accent-fg);
}
.nl-input::placeholder {
  color: var(--color-fg-light);
}
.nl-btn {
  height: auto;
  min-height: 52px;
  padding: 0 16px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.nl-btn svg {
  width: 14px;
  height: 14px;
}
.spin {
  animation: nl-spin 0.9s linear infinite;
}
@keyframes nl-spin {
  to { transform: rotate(360deg); }
}
.nl-summary {
  margin-top: 12px;
  border: 0.5px solid var(--color-border-default);
  border-left: 3px solid var(--color-accent-fg);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--color-canvas-inset);
}
.nl-summary-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-accent-fg);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.nl-summary-label svg {
  width: 13px;
  height: 13px;
}
.nl-summary-body {
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-fg-default);
  white-space: pre-wrap;
}
.nl-error {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #b42318;
  background: rgba(180, 35, 24, 0.08);
  border: 0.5px solid rgba(180, 35, 24, 0.25);
  border-radius: 8px;
  padding: 8px 12px;
}
.nl-error svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
.nl-result {
  margin-top: 12px;
}
.nl-result-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--color-fg-muted);
  margin-bottom: 8px;
}
.nl-audit {
  color: var(--color-fg-light);
}
/* ── 查询计划（P0-3）── */
.nl-plan {
  margin-top: 12px;
  border: 0.5px solid var(--color-border-default);
  border-left: 3px solid var(--color-accent-fg);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--color-canvas-inset);
}
.nl-plan-hdr {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-accent-fg);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.nl-plan-hdr svg {
  width: 13px;
  height: 13px;
}
.nl-plan-preview-badge {
  font-size: 10px;
  font-weight: 600;
  color: #b45309;
  background: rgba(180, 83, 9, 0.12);
  border-radius: 4px;
  padding: 1px 6px;
}
.nl-plan-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nl-plan-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--color-fg-default);
}
.nl-plan-item code {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-muted, #e5e7eb);
  border-radius: 4px;
  padding: 1px 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}
.nl-plan-op {
  color: var(--color-fg-muted);
  font-size: 11px;
}
.nl-plan-empty {
  font-size: 12px;
  color: var(--color-fg-subtle);
}
.nl-plan-meta {
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.nl-plan-degraded {
  margin-top: 8px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: #b42318;
  background: rgba(180, 35, 24, 0.06);
  border: 0.5px solid rgba(180, 35, 24, 0.2);
  border-radius: 6px;
  padding: 6px 8px;
}
.nl-plan-degraded svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
  margin-top: 1px;
}
.nl-table-wrap {
  max-height: 360px;
  overflow: auto;
  border: 0.5px solid var(--color-border-default);
  border-radius: 8px;
}
.nl-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.nl-table thead th {
  position: sticky;
  top: 0;
  background: var(--color-canvas-inset);
  color: var(--color-fg-muted);
  font-weight: 500;
  text-align: left;
  padding: 7px 10px;
  border-bottom: 0.5px solid var(--color-border-default);
  white-space: nowrap;
}
.nl-table tbody td {
  padding: 6px 10px;
  border-bottom: 0.5px solid var(--color-border-muted, #eee);
  color: var(--color-fg-default);
  white-space: nowrap;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nl-table tbody tr:hover {
  background: var(--color-canvas-inset);
}
</style>
