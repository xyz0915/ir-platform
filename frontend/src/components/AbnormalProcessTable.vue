<template>
  <div class="abnormal-process-table-enhanced">
    <!-- 顶部工具栏 -->
    <div class="toolbar mb-12">
      <el-input
        v-model="searchQuery"
        placeholder="搜索进程名/路径/命令行"
        clearable
        style="width: 240px"
        size="small"
      />
      <el-select
        v-model="severityFilter"
        multiple
        placeholder="严重程度"
        clearable
        size="small"
        style="width: 200px; margin-left: 8px"
      >
        <el-option label="Critical" value="critical" />
        <el-option label="High" value="high" />
        <el-option label="Medium" value="medium" />
        <el-option label="Low" value="low" />
        <el-option label="Info" value="info" />
      </el-select>
      <el-select
        v-model="ruleNameFilter"
        multiple
        placeholder="规则名"
        clearable
        size="small"
        style="width: 240px; margin-left: 8px"
      >
        <el-option
          v-for="opt in allRuleNames"
          :key="opt.name"
          :label="opt.label"
          :value="opt.name"
        />
      </el-select>
      <el-button
        size="small"
        style="margin-left: 8px"
        @click="exportCSV"
      >
        导出 CSV
      </el-button>
    </div>

    <!-- 表格 -->
    <el-table
      :data="filteredData"
      border
      stripe
      size="small"
      row-key="pid"
      :default-expand-all="false"
    >
      <el-table-column prop="pid" label="PID" width="80" />
      <el-table-column prop="process_name" label="进程名" width="130" show-overflow-tooltip />
      <el-table-column prop="process_path" label="路径" min-width="180" show-overflow-tooltip />
      <el-table-column prop="command_line" label="命令行" min-width="200" show-overflow-tooltip />
      <el-table-column prop="parent_name" label="父进程" width="120" show-overflow-tooltip />
      <el-table-column prop="severity" label="严重程度" width="100">
        <template #default="{ row }">
          <el-tag :type="severityType(row.severity)" size="small" effect="plain" class="sev-tag">
            {{ row.severity }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="risk_score" label="风险评分" width="130">
        <template #default="{ row }">
          <el-progress
            :percentage="row.risk_score || 0"
            :color="riskColor(row.risk_score || 0)"
            :stroke-width="14"
            :text-inside="true"
            style="width: 100px"
          />
        </template>
      </el-table-column>
      <el-table-column type="expand" label="命中规则" width="80">
        <template #default="{ row }">
          <div v-if="row.matched_rules && row.matched_rules.length" class="expand-rules">
            <el-tag
              v-for="(rule, idx) in row.matched_rules"
              :key="idx"
              :type="severityType(rule.severity)"
              size="small"
              effect="plain"
              class="rule-tag"
              style="margin: 2px 4px"
            >
              {{ rule.label || rule.name }} [{{ rule.severity }}]: {{ rule.reason }}
            </el-tag>
          </div>
          <div v-else class="expand-rules">
            <span>{{ row.rule_name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="原因" min-width="180" show-overflow-tooltip />
      <el-table-column label="知识匹配" width="80" v-if="hasKnowledgeHits">
        <template #default="{ row }">
          <el-tooltip
            v-if="row.knowledge_hit"
            :content="row.knowledge_hit.title + ' (' + row.knowledge_hit.confidence + ')'"
            placement="top"
          >
            <span class="knowledge-badge" @click.stop="$emit('knowledge-click', row.knowledge_hit?.entry_ref)">
              <svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                <path d="M12 6v7" />
                <path d="M9 9h6" />
              </svg>
            </span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" @click="$emit('view-detail', row)">
            详情
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 底部统计条 -->
    <div class="table-footer">
      <span class="footer-info">共 {{ filteredData.length }} 条异常进程<span v-if="filteredData.length !== data.length">，已筛选</span></span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import Papa from 'papaparse'

const props = defineProps({
  data: { type: Array, default: () => [] }
})

defineEmits(['view-detail', 'knowledge-click'])

const searchQuery = ref('')
const severityFilter = ref([])
const ruleNameFilter = ref([])

/** 判断是否有知识匹配的条目 */
const hasKnowledgeHits = computed(() => {
  return props.data.some(row => row.knowledge_hit)
})

/** 从 data 中提取所有规则：{name(稳定 ID), label(中文展示)} */
const allRuleNames = computed(() => {
  const map = new Map()
  for (const row of props.data) {
    if (row.matched_rules && Array.isArray(row.matched_rules)) {
      for (const rule of row.matched_rules) {
        if (rule && rule.name) {
          // value 用 name（稳定 ID，筛选/历史兼容）；展示用 label || name
          map.set(rule.name, rule.label || rule.name)
        }
      }
    } else if (row.rule_name) {
      map.set(row.rule_name, row.rule_name)
    }
  }
  return Array.from(map.entries())
    .map(([name, label]) => ({ name, label }))
    .sort((a, b) => a.name.localeCompare(b.name))
})

/** 搜索+筛选逻辑 */
const filteredData = computed(() => {
  let result = props.data

  // 搜索
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(row => {
      const name = (row.process_name || '').toLowerCase()
      const path = (row.process_path || '').toLowerCase()
      const cmd = (row.command_line || '').toLowerCase()
      return name.includes(q) || path.includes(q) || cmd.includes(q)
    })
  }

  // 严重程度筛选
  if (severityFilter.value.length > 0) {
    result = result.filter(row => severityFilter.value.includes(row.severity))
  }

  // 规则名筛选
  if (ruleNameFilter.value.length > 0) {
    result = result.filter(row => {
      if (row.matched_rules && Array.isArray(row.matched_rules)) {
        return row.matched_rules.some(rule => ruleNameFilter.value.includes(rule.name))
      }
      return ruleNameFilter.value.includes(row.rule_name)
    })
  }

  return result
})

function severityType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary',
    info: 'info'
  }
  return map[severity] || 'info'
}

function riskColor(score) {
  if (score >= 80) return '#A32D2D'   // c-red 600
  if (score >= 50) return '#BA7517'   // c-amber 500
  if (score >= 20) return '#378ADD'   // c-blue 400
  return '#1D9E75'                    // c-teal 400
}

function exportCSV() {
  const exportData = filteredData.value.map(row => ({
    PID: row.pid,
    进程名: row.process_name,
    路径: row.process_path,
    命令行: row.command_line,
    父进程: row.parent_name,
    严重程度: row.severity,
    风险评分: row.risk_score,
    命中规则: row.matched_rules
      ? row.matched_rules.map(r => `${(r.label || r.name)}[${r.severity}]`).join('; ')
      : row.rule_name,
    原因: row.reason,
    攻击路径: row.attack_path || '',
  }))
  const csv = Papa.unparse(exportData)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'abnormal_processes.csv'
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
.mb-12 {
  margin-bottom: 12px;
}
.expand-rules {
  padding: 8px 12px;
}
.knowledge-badge {
  cursor: pointer;
  font-size: 16px;
}
.sev-tag {
  border: none !important;
  background: transparent !important;
  padding: 0 6px !important;
  font-size: 11px !important;
  font-weight: 500 !important;
}
.rule-tag {
  background: var(--color-canvas-inset, #f5f5f5) !important;
  border: 0.5px solid var(--color-border-default, #e5e5e5) !important;
  color: var(--color-fg-muted, #555) !important;
  padding: 2px 7px !important;
  font-size: 11px !important;
  font-weight: 400 !important;
  border-radius: 4px !important;
}
.knowledge-badge {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
}
.knowledge-badge svg {
  width: 16px;
  height: 16px;
  stroke: var(--color-fg-muted, #555);
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  padding: 10px 0 0;
  font-size: 12px;
  color: var(--color-fg-subtle, #888);
}
.footer-info {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 表格弱化边框和 stripe */
:deep(.el-table) {
  --el-table-border-color: var(--color-border-default, #e5e5e5);
  --el-table-row-hover-bg-color: var(--color-canvas-inset, #f5f5f5);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 8px;
  overflow: hidden;
}
:deep(.el-table th.el-table__cell) {
  background: var(--color-canvas-subtle, #fafafa) !important;
  color: var(--color-fg-subtle, #888) !important;
  font-weight: 500 !important;
  font-size: 12px !important;
  padding: 8px 10px !important;
}
:deep(.el-table td.el-table__cell) {
  padding: 8px 10px !important;
  font-size: 12px !important;
}
:deep(.el-table--striped .el-table__body tr.el-table__row--striped td) {
  background: var(--color-canvas-inset, #f5f5f5) !important;
}

/* 表格行紧凑 */
:deep(.el-table .el-table__body td) {
  padding: 6px 8px !important;
  font-size: 12px !important;
  line-height: 1.4 !important;
}
:deep(.el-table .el-table__body td .cell) {
  padding: 0 !important;
}

/* 进度条弱化 */
:deep(.el-progress) {
  margin: 0;
}
:deep(.el-progress-bar__inner) {
  border-radius: 3px !important;
}
:deep(.el-progress-bar__outer) {
  background: var(--color-canvas-inset, #f5f5f5) !important;
  border-radius: 3px !important;
}
</style>
