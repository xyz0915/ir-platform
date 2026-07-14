<template>
  <el-dialog
    v-model="visible"
    title="JSON 详情"
    width="640px"
    :close-on-click-modal="true"
    :close-on-press-escape="true"
    @close="onClose"
  >
    <div class="log-detail-panel">
      <!-- 基本信息 -->
      <div class="detail-info" v-if="record">
        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">ID</span>
            <span class="info-value">{{ record.id }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">案件</span>
            <span class="info-value">{{ record.case_name || `#${record.case_id}` }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">主机</span>
            <span class="info-value">{{ record.hostname || `#${record.host_id}` }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">采集器</span>
            <span class="info-value">{{ record.collector_type }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">时间</span>
            <span class="info-value">{{ record.imported_at }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">状态</span>
            <span class="info-value">
              <el-tag v-if="record.event_created" type="success" size="small">已生成事件</el-tag>
              <el-tag v-else type="info" size="small">未处理</el-tag>
            </span>
          </div>
        </div>
      </div>

      <!-- JSON 语法高亮 -->
      <div class="json-section">
        <div class="json-toolbar">
          <span class="json-title">原始 JSON</span>
          <el-button size="small" text @click="copyJson">
            <el-icon><CopyDocument /></el-icon>
            复制
          </el-button>
        </div>
        <div class="json-body">
          <JsonNode
            v-if="parsedJson"
            :data="parsedJson"
            :depth="0"
            :default-collapsed-depth="3"
          />
          <pre v-else class="raw-json">{{ rawJsonText }}</pre>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed, defineComponent, h } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'

// ---- Recursive JSON display component ----
// Replaces vue-json-pretty with a native Vue 3 implementation.
// Uses a render-function-based setup to support recursion within <script setup>.
const JsonNode = defineComponent({
  name: 'JsonNode',
  props: {
    data: { required: true },
    depth: { type: Number, default: 0 },
    defaultCollapsedDepth: { type: Number, default: 3 }
  },
  setup(props) {
    const collapsed = ref(props.depth >= props.defaultCollapsedDepth)
    const toggle = () => { collapsed.value = !collapsed.value }

    return () => {
      const isCollapsed = collapsed.value
      const d = props.data
      const nextDepth = props.depth + 1

      // ---- Primitives ----
      if (d === null) {
        return h('span', { class: 'json-null' }, 'null')
      }
      if (typeof d === 'boolean') {
        return h('span', { class: 'json-bool' }, String(d))
      }
      if (typeof d === 'number') {
        return h('span', { class: 'json-number' }, String(d))
      }
      if (typeof d === 'string') {
        return h('span', { class: 'json-string' }, JSON.stringify(d))
      }

      // ---- Array ----
      if (Array.isArray(d)) {
        const items = []
        items.push(h('span', {
          class: 'json-toggle',
          onClick: toggle
        }, isCollapsed ? '▸' : '▾'))

        if (isCollapsed) {
          items.push(h('span', { class: 'json-summary' }, `Array[${d.length}]`))
        } else {
          items.push(h('span', { class: 'json-bracket' }, '['))
          items.push(h('div', { class: 'json-children' },
            d.map((item, i) => {
              const line = [
                h(JsonNode, {
                  data: item,
                  depth: nextDepth,
                  defaultCollapsedDepth: props.defaultCollapsedDepth
                })
              ]
              if (i < d.length - 1) {
                line.push(h('span', { class: 'json-comma' }, ','))
              }
              return h('div', { class: 'json-line', key: i }, line)
            })
          ))
          items.push(h('span', { class: 'json-bracket' }, ']'))
        }

        return h('div', { class: 'json-entry' }, items)
      }

      // ---- Object ----
      if (typeof d === 'object' && d !== null) {
        const keys = Object.keys(d)
        const items = []
        items.push(h('span', {
          class: 'json-toggle',
          onClick: toggle
        }, isCollapsed ? '▸' : '▾'))

        if (isCollapsed) {
          items.push(h('span', { class: 'json-summary' }, `Object{${keys.length}}`))
        } else {
          items.push(h('span', { class: 'json-bracket' }, '{'))
          items.push(h('div', { class: 'json-children' },
            keys.map((key, i) => {
              const line = [
                h('span', { class: 'json-key' }, JSON.stringify(key)),
                h('span', { class: 'json-colon' }, ': '),
                h(JsonNode, {
                  data: d[key],
                  depth: nextDepth,
                  defaultCollapsedDepth: props.defaultCollapsedDepth
                })
              ]
              if (i < keys.length - 1) {
                line.push(h('span', { class: 'json-comma' }, ','))
              }
              return h('div', { class: 'json-line', key: i }, line)
            })
          ))
          items.push(h('span', { class: 'json-bracket' }, '}'))
        }

        return h('div', { class: 'json-entry' }, items)
      }

      // Fallback
      return h('span', String(d))
    }
  }
})

// ---- Main Component Logic ----
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  record: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// 解析 JSON
const parsedJson = computed(() => {
  if (!props.record?.raw_json) return null
  try {
    return JSON.parse(props.record.raw_json)
  } catch {
    return null
  }
})

const rawJsonText = computed(() => {
  if (!props.record?.raw_json) return '{}'
  try {
    return JSON.stringify(JSON.parse(props.record.raw_json), null, 2)
  } catch {
    return props.record.raw_json
  }
})

function copyJson() {
  const text = props.record?.raw_json || '{}'
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

function onClose() {
  emit('update:modelValue', false)
}
</script>

<style scoped>
.log-detail-panel {
  max-height: 70vh;
  overflow-y: auto;
}

.detail-info {
  margin-bottom: 16px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-label {
  font-size: 10px;
  color: var(--color-fg-muted);
  text-transform: uppercase;
}

.info-value {
  font-size: 12px;
  color: var(--color-fg-default);
  font-weight: 500;
}

/* JSON 区域 */
.json-section {
  border: 1px solid var(--color-border-default);
  border-radius: 6px;
  overflow: hidden;
}

.json-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: var(--color-canvas-subtle);
  border-bottom: 1px solid var(--color-border-default);
}

.json-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-fg-default);
}

.json-body {
  padding: 10px;
  max-height: 400px;
  overflow: auto;
  font-size: 12px;
  background: var(--color-canvas-default);
  font-family: 'Courier New', monospace;
  line-height: 1.6;
}

.raw-json {
  margin: 0;
  font-size: 11px;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-fg-default);
}

/* ---- JSON Node syntax highlighting ---- */
.json-entry {
  user-select: text;
}

.json-toggle {
  cursor: pointer;
  user-select: none;
  margin-right: 4px;
  font-size: 10px;
  color: var(--color-fg-muted);
  display: inline-block;
  width: 12px;
  text-align: center;
  flex-shrink: 0;
}

.json-toggle:hover {
  color: var(--color-fg-default);
}

.json-summary {
  color: var(--color-fg-muted);
  font-style: italic;
  font-size: 11px;
}

.json-bracket {
  color: var(--color-fg-muted);
}

.json-children {
  padding-left: 20px;
  border-left: 1px solid transparent;
}

.json-line {
  padding-left: 0;
}

/* Syntax colors */
.json-key {
  color: #185FA5;
}

.json-colon {
  color: var(--color-fg-muted);
}

.json-comma {
  color: var(--color-fg-muted);
}

.json-string {
  color: #3B6D11;
}

.json-number {
  color: #BA7517;
}

.json-bool {
  color: #185FA5;
}

.json-null {
  color: var(--color-fg-muted);
  font-style: italic;
}
</style>
