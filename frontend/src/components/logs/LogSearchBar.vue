<template>
  <div class="log-search-bar">
    <!-- Token 化搜索输入 -->
    <div class="search-input-row">
      <div class="token-input" :class="{ focused: inputFocused }">
        <div class="token-list">
          <el-tag
            v-for="(token, idx) in searchTokens"
            :key="idx"
            closable
            size="small"
            type="info"
            @close="removeToken(idx)"
          >
            {{ token.field }} {{ token.op }} "{{ token.value }}"
          </el-tag>
        </div>
        <el-input
          v-model="inputText"
          :placeholder="placeholder"
          size="small"
          :style="{ border: 'none', boxShadow: 'none' }"
          @focus="inputFocused = true"
          @blur="inputFocused = false"
          @keyup.enter="doSearch"
        />
      </div>
      <el-button type="primary" size="small" @click="doSearch">搜索</el-button>
    </div>

    <!-- 语法帮助 + 常用字段标签（P0-1 真实语法提示） -->
    <div class="field-tags">
      <span class="field-label">字段:</span>
      <el-tag
        v-for="field in commonFields"
        :key="field"
        size="small"
        effect="plain"
        @click="insertField(field)"
      >
        [{{ field }}]
      </el-tag>
      <el-tooltip placement="top" width="320">
        <template #content>
          <div class="syntax-help">
            <p><b>字段语法：</b><code>field op value</code></p>
            <p>操作符：<code>==</code> <code>!=</code> <code>~</code>(包含)
              <code>in</code> <code>&gt;=</code> <code>&lt;=</code> <code>between</code></p>
            <p>组合：<code>and</code> <code>or</code> <code>not</code> <code>( )</code></p>
            <p>字段：severity / status / source_ip / user_name / process_name /
              command_line / event_type / source_collector / timestamp / keyword 等</p>
            <p>示例：<code>severity=="high" or source_ip~"1.1.1.1"</code></p>
            <p>裸词（如 <code>powershell -enc</code>）按关键字检索</p>
          </div>
        </template>
        <span class="syntax-help-link">语法帮助</span>
      </el-tooltip>
    </div>

    <!-- 快捷筛选标签（P0-1 合法 DSL） -->
    <div class="quick-tags">
      <span class="field-label">快捷:</span>
      <el-tag
        v-for="tag in quickFilters"
        :key="tag.label"
        :type="tag.type"
        size="small"
        effect="plain"
        style="cursor: pointer;"
        @click="applyQuickFilter(tag)"
      >
        {{ tag.label }}
      </el-tag>
    </div>

    <!-- 日志量趋势柱状图 -->
    <div class="trend-section" v-if="trendData.length > 0">
      <div class="trend-chart">
        <div
          v-for="(item, idx) in trendData"
          :key="idx"
          class="trend-bar"
          :style="{ height: barHeight(item) + 'px' }"
          :class="{ peak: isPeak(item) }"
          :title="`${item.hour}: ${item.count} 条`"
        />
      </div>
      <div class="trend-labels">
        <span>近 24h</span>
        <span class="trend-peak-label">峰值: {{ maxCount }} 条</span>
      </div>
    </div>

    <!-- 结果计数 -->
    <div class="result-count" v-if="total !== null">
      <span>共 {{ total }} 条，耗时 {{ elapsedMs }}ms</span>
      <span class="context-hint" v-if="currentCaseName || currentHostName">
        | 案件 {{ currentCaseName }} / 主机 {{ currentHostName }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { todayStart } from '@/utils/time'

const props = defineProps({
  modelValue: { type: String, default: '' },
  total: { type: Number, default: null },
  elapsedMs: { type: Number, default: 0 },
  trendData: { type: Array, default: () => [] },
  currentCaseName: { type: String, default: '' },
  currentHostName: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'search', 'quick-filter'])

const inputText = ref(props.modelValue)
const inputFocused = ref(false)
const searchTokens = ref([])

// P0-1 真实语法提示占位符
const placeholder = '支持字段语法: severity=="high" or source_ip~"1.1.1.1"'

// 常用字段（白名单）
const commonFields = ['severity', 'status', 'source_ip', 'user_name', 'process_name', 'event_type', 'source_collector', 'timestamp']

// 快捷筛选（P0-1 合法 DSL；今日新增动态生成）
const quickFilters = [
  { label: '高危未处理', type: 'danger', query: 'severity in ("high","critical") and status=="pending"' },
  { label: 'IOC 命中', type: 'danger', query: 'event_type=="ioc_match"' },
  { label: '公网连接', type: 'warning', query: 'source_collector~"network" or event_type=="network_outbound"' },
  { label: '可疑进程', type: 'info', query: 'process_name~"svchost" or process_name~"powershell"' },
  { label: '今日新增', type: 'warning', query: `timestamp>="${todayStart()}"` },
]

// 趋势图最大值
const maxCount = computed(() => {
  if (props.trendData.length === 0) return 0
  return Math.max(...props.trendData.map(d => d.count))
})

function barHeight(item) {
  if (maxCount.value === 0) return 0
  return Math.max(4, (item.count / maxCount.value) * 48)
}

function isPeak(item) {
  return item.count === maxCount.value && maxCount.value > 0
}

function insertField(field) {
  inputText.value += `${field}==`
  inputFocused.value = true
}

function applyQuickFilter(tag) {
  emit('quick-filter', tag)
  inputText.value = tag.query
  doSearch()
}

function removeToken(idx) {
  searchTokens.value.splice(idx, 1)
}

// P0-1 doSearch 分流：含 DSL 操作符 → dsl 参数；否则纯 keyword
const DSL_RE = /[=~]|\b(in|or|and|not)\b/i
function isDsl(text) {
  return DSL_RE.test(text || '')
}

function doSearch() {
  const text = inputText.value
  emit('update:modelValue', text)
  if (isDsl(text)) {
    emit('search', { dsl: text })
  } else {
    emit('search', { keyword: text })
  }
}
</script>

<style scoped>
.log-search-bar {
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  padding: 12px 16px;
}

.search-input-row {
  display: flex;
  gap: 8px;
}

.token-input {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border: 1px solid var(--color-border-default);
  border-radius: 6px;
  background: var(--color-canvas-default);
  transition: border-color 0.15s;
  min-height: 32px;
}

.token-input.focused {
  border-color: var(--color-accent-fg);
}

.token-list {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.field-tags,
.quick-tags {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.field-label {
  font-size: 11px;
  color: var(--color-fg-muted);
  flex-shrink: 0;
}

.syntax-help-link {
  font-size: 11px;
  color: var(--color-accent-fg);
  cursor: pointer;
  margin-left: 4px;
  text-decoration: underline dotted;
}
.syntax-help {
  font-size: 12px;
  line-height: 1.8;
  color: var(--color-fg-default);
}
.syntax-help code {
  background: rgba(0, 0, 0, 0.06);
  border-radius: 3px;
  padding: 0 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}

/* 趋势图 */
.trend-section {
  margin-top: 10px;
}

.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 52px;
  padding: 4px 0;
}

.trend-bar {
  flex: 1;
  background: var(--color-accent-subtle, #dbeafe);
  border-radius: 2px 2px 0 0;
  min-height: 4px;
  transition: height 0.3s;
}

.trend-bar.peak {
  background: var(--color-danger-subtle, #fecaca);
}

.trend-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--color-fg-muted);
}

.trend-peak-label {
  color: var(--color-danger-fg);
  font-weight: 600;
}

/* 结果计数 */
.result-count {
  margin-top: 8px;
  font-size: 11px;
  color: var(--color-fg-muted);
}

.context-hint {
  color: var(--color-accent-fg);
}
</style>
