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
        type="success"
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
          <el-tag :type="severityType(row.severity)" size="small">
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
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="$emit('view-detail', row)">
            详情
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import Papa from 'papaparse'

const props = defineProps({
  data: { type: Array, default: () => [] }
})

defineEmits(['view-detail'])

const searchQuery = ref('')
const severityFilter = ref([])
const ruleNameFilter = ref([])

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
  if (score >= 80) return '#F56C6C'
  if (score >= 50) return '#E6A23C'
  if (score >= 20) return '#409EFF'
  return '#67C23A'
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
</style>
