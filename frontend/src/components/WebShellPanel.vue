<template>
  <div class="webshell-panel">
    <div class="toolbar mb-12">
      <span class="tab-hint">共 {{ data.length }} 条 WebShell 命中</span>
      <el-input
        v-model="searchQuery"
        placeholder="搜索路径/文件名/SHA256"
        clearable
        size="small"
        style="width: 260px; margin-left: 12px"
      />
    </div>

    <el-table :data="filteredData" border stripe size="small" row-key="path">
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
            <div v-if="funcList(row).length" class="expand-section">
              <div class="expand-title">危险函数</div>
              <el-tag
                v-for="(f, i) in funcList(row)"
                :key="i"
                type="danger"
                size="small"
                effect="plain"
                class="rule-tag"
              >{{ f }}</el-tag>
            </div>
            <div v-if="row.details && Object.keys(row.details).length" class="expand-section">
              <div class="expand-title">原始证据 (details)</div>
              <pre class="evidence-pre">{{ formatJson(row.details) }}</pre>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="path" label="路径" min-width="220" show-overflow-tooltip />
      <el-table-column prop="name" label="文件名" width="150" show-overflow-tooltip />
      <el-table-column label="中间件" width="110">
        <template #default="{ row }">
          <el-tag v-if="middlewareOf(row.path)" size="small" type="info">
            {{ middlewareOf(row.path) }}
          </el-tag>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="sha256" label="SHA256" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="mono">{{ shortHash(row.sha256) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="危险函数" min-width="160">
        <template #default="{ row }">
          <template v-if="funcList(row).length">
            <el-tag
              v-for="(f, i) in funcList(row).slice(0, 4)"
              :key="i"
              type="danger"
              size="small"
              effect="plain"
              class="rule-tag"
            >{{ f }}</el-tag>
            <span v-if="funcList(row).length > 4" class="text-muted">+{{ funcList(row).length - 4 }}</span>
          </template>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="obfuscation_score" label="混淆分" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="obfuscationType(row.obfuscation_score)" size="small">
            {{ row.obfuscation_score ?? 0 }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="哥斯拉/冰蝎" width="110" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.behinder_godzilla_signal" type="danger" size="small">命中</el-tag>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="风险评分" width="130">
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

const props = defineProps({
  data: { type: Array, default: () => [] }
})

defineEmits(['knowledge-click'])

const searchQuery = ref('')

const filteredData = computed(() => {
  if (!searchQuery.value) return props.data
  const q = String(searchQuery.value).toLowerCase()
  return props.data.filter(row => {
    const path = (row.path || '').toLowerCase()
    const name = (row.name || '').toLowerCase()
    const sha = (row.sha256 || '').toLowerCase()
    return path.includes(q) || name.includes(q) || sha.includes(q)
  })
})

const hasKnowledgeHits = computed(() => {
  return props.data.some(row => row.knowledge_hit)
})

/** matched_rules 兼容字符串/对象 */
function ruleList(row) {
  const rules = row.matched_rules || row.details?.matched_rules || []
  return Array.isArray(rules) ? rules : []
}

/** suspicious_funcs 兼容字符串/对象 */
function funcList(row) {
  const funcs = row.suspicious_funcs || row.details?.suspicious_funcs || []
  return Array.isArray(funcs) ? funcs : []
}

function ruleLabel(r) {
  if (typeof r === 'string') return r
  return r.label || r.name || r.rule || 'rule'
}

function middlewareOf(path) {
  if (!path) return ''
  const p = String(path).toLowerCase()
  const map = [
    ['tomcat', 'Tomcat'],
    ['weblogic', 'WebLogic'],
    ['jboss', 'JBoss'],
    ['wildfly', 'WildFly'],
    ['jetty', 'Jetty'],
    ['websphere', 'WebSphere'],
    ['nginx', 'Nginx'],
    ['apache', 'Apache'],
    ['httpd', 'Apache'],
    ['iis', 'IIS'],
    ['wwwroot', 'IIS'],
    ['webapps', 'Tomcat'],
  ]
  for (const [kw, label] of map) {
    if (p.includes(kw)) return label
  }
  return ''
}

function shortHash(sha) {
  if (!sha) return '-'
  const s = String(sha)
  return s.length > 16 ? `${s.slice(0, 8)}…${s.slice(-8)}` : s
}

function obfuscationType(score) {
  const s = Number(score || 0)
  if (s >= 70) return 'danger'
  if (s >= 40) return 'warning'
  if (s > 0) return 'primary'
  return 'info'
}

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

function formatJson(obj) {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
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
.evidence-pre {
  background: var(--color-canvas-inset, #f5f7fa);
  border: 1px solid var(--color-border-default, #ebeef5);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  max-height: 240px;
  overflow: auto;
  margin: 0;
}
.mono { font-family: Consolas, 'Courier New', monospace; font-size: 12px; }
.text-muted { color: var(--color-fg-muted, #909399); }
.knowledge-badge { cursor: pointer; font-size: 16px; }
</style>
