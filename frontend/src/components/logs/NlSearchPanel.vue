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
        placeholder="输入自然语言检索需求…（Ctrl+Enter 检索）"
        @keydown.ctrl.enter="runSearch"
      ></textarea>
      <button class="btn btn-primary nl-btn" :disabled="loading" @click="runSearch">
        <svg v-if="!loading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
        {{ loading ? '检索中…' : '智能检索' }}
      </button>
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

function formatCell(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
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
  try {
    const resp = await nlLogSearch({ nl_text: text })
    // resp: {code, data, message}
    if (resp && resp.code === 0 && resp.data) {
      const d = resp.data
      columns.value = d.columns || []
      rows.value = d.rows || []
      summary.value = d.summary || ''
      total.value = d.total || rows.value.length
      auditId.value = d.audit_id || null
      if (!rows.value.length) {
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
