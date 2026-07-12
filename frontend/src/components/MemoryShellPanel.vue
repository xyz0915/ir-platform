<template>
  <div class="memory-shell-panel">
    <div class="toolbar mb-12">
      <span class="tab-hint">共 {{ data.length }} 条内存码命中</span>
      <el-input
        v-model="searchQuery"
        placeholder="搜索 PID/进程名/类型"
        clearable
        size="small"
        style="width: 240px; margin-left: 12px"
      />
    </div>

    <el-table :data="filteredData" border stripe size="small" row-key="pid">
      <el-table-column type="expand" label="明细" width="70">
        <template #default="{ row }">
          <div class="expand-detail">
            <div v-if="ruleList(row).length" class="expand-section">
              <div class="expand-title">命中规则</div>
              <el-tag
                v-for="(r, i) in ruleList(row)"
                :key="i"
                :type="severityType(r.severity)"
                size="small"
                class="rule-tag"
              >
                {{ ruleLabel(r) }}<span v-if="r.severity"> [{{ r.severity }}]</span
                ><span v-if="r.reason">: {{ r.reason }}</span>
              </el-tag>
            </div>
            <div class="expand-section">
              <div class="expand-title">信号明细</div>
              <div v-for="s in signalSections(row)" :key="s.key" class="signal-line">
                <span class="signal-key">{{ s.label }}：</span>
                <template v-if="s.items.length">
                  <el-tag
                    v-for="(it, i) in s.items"
                    :key="i"
                    size="small"
                    effect="plain"
                    class="rule-tag"
                  >{{ it }}</el-tag>
                </template>
                <span v-else class="text-muted">无</span>
              </div>
            </div>
            <div v-if="row.evidence" class="expand-section">
              <div class="expand-title">证据</div>
              <div class="evidence-text">{{ row.evidence }}</div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="PID" width="90">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="$emit('view-tree', row.pid)">
            {{ row.pid }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="process_name" label="进程名" min-width="140" show-overflow-tooltip />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag size="small" type="warning">{{ row.type || 'unknown' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="信号(class/agent/conn/thread)" min-width="200" align="center">
        <template #default="{ row }">
          <span class="signal-badge" v-for="s in signalBadges(row)" :key="s.key" :style="{ color: s.count ? '' : '#bbb' }">
            {{ s.label }}<strong>{{ s.count }}</strong>
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="evidence" label="证据" min-width="200" show-overflow-tooltip />
      <el-table-column label="置信度" width="130">
        <template #default="{ row }">
          <el-progress
            :percentage="Number(row.risk_score || 0)"
            :color="riskColor(Number(row.risk_score || 0))"
            :stroke-width="14"
            :text-inside="true"
            style="width: 100px"
          />
        </template>
      </el-table-column>
      <el-table-column prop="severity" label="严重程度" width="100">
        <template #default="{ row }">
          <el-tag :type="severityType(row.severity)" size="small">{{ row.severity || 'info' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="知识匹配" width="70" v-if="hasKnowledgeHits">
        <template #default="{ row }">
          <el-tooltip
            v-if="row.knowledge_hit"
            :content="row.knowledge_hit.title + ' (' + row.knowledge_hit.confidence + ')'"
            placement="top"
          >
            <span class="knowledge-badge" @click.stop="$emit('knowledge-click', row.knowledge_hit.entry_ref)">📚</span>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

defineEmits(['view-tree', 'knowledge-click'])

const props = defineProps({
  data: { type: Array, default: () => [] }
})

const searchQuery = ref('')

const filteredData = computed(() => {
  if (!searchQuery.value) return props.data
  const q = String(searchQuery.value).toLowerCase()
  return props.data.filter(row => {
    const pid = String(row.pid || '').toLowerCase()
    const name = (row.process_name || '').toLowerCase()
    const type = (row.type || '').toLowerCase()
    return pid.includes(q) || name.includes(q) || type.includes(q)
  })
})

const hasKnowledgeHits = computed(() => {
  return props.data.some(row => row.knowledge_hit)
})

/** details 里存放了 class_signals/agent_signals/conn_signals/thread_signals */
function det(row) {
  return row.details && typeof row.details === 'object' ? row.details : {}
}

function signalArray(row, key) {
  const v = det(row)[key]
  if (Array.isArray(v)) return v
  if (v == null || v === '') return []
  if (typeof v === 'object') return Object.entries(v).map(([k, val]) => `${k}=${val}`)
  return [v]
}

function signalBadges(row) {
  return [
    { key: 'class_signals', label: '类', count: signalArray(row, 'class_signals').length },
    { key: 'agent_signals', label: 'Agent', count: signalArray(row, 'agent_signals').length },
    { key: 'conn_signals', label: '连', count: signalArray(row, 'conn_signals').length },
    { key: 'thread_signals', label: '线', count: signalArray(row, 'thread_signals').length },
  ]
}

function signalSections(row) {
  return [
    { key: 'class_signals', label: '类加载信号', items: signalArray(row, 'class_signals') },
    { key: 'agent_signals', label: 'Agent 注入信号', items: signalArray(row, 'agent_signals') },
    { key: 'conn_signals', label: '连接异常信号', items: signalArray(row, 'conn_signals') },
    { key: 'thread_signals', label: '线程异常信号', items: signalArray(row, 'thread_signals') },
  ]
}

function ruleList(row) {
  const rules = row.matched_rules || det(row).matched_rules || []
  return Array.isArray(rules) ? rules : []
}

function ruleLabel(r) {
  if (typeof r === 'string') return r
  return r.label || r.name || r.rule || 'rule'
}

function severityType(severity) {
  const map = { critical: 'danger', high: 'danger', medium: 'warning', low: 'primary', info: 'info' }
  return map[severity] || 'info'
}

function riskColor(score) {
  if (score >= 80) return '#F56C6C'
  if (score >= 50) return '#E6A23C'
  if (score >= 20) return '#409EFF'
  return '#67C23A'
}
</script>

<style scoped>
.toolbar { display: flex; align-items: center; }
.mb-12 { margin-bottom: 12px; }
.tab-hint { font-size: 13px; color: var(--color-fg-muted, #909399); }
.rule-tag { margin: 2px 4px; }
.expand-detail { padding: 8px 16px; }
.expand-section { margin-bottom: 10px; }
.expand-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--color-fg-default, #303133); }
.signal-line { margin-bottom: 6px; font-size: 13px; }
.signal-key { font-weight: 600; margin-right: 4px; }
.evidence-text {
  background: var(--color-canvas-inset, #f5f7fa);
  border: 1px solid var(--color-border-default, #ebeef5);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.signal-badge {
  display: inline-block;
  margin: 0 6px;
  font-size: 12px;
}
.signal-badge strong { margin-left: 2px; }
.text-muted { color: var(--color-fg-muted, #909399); }
.knowledge-badge { cursor: pointer; font-size: 16px; }
</style>
