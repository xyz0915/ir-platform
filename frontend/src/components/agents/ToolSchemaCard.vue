<template>
  <div class="tool-schema-card">
    <!-- 头部：名称 + 状态（状态并入名称区右上角，去彩色 tag） -->
    <div class="tsc-head">
      <div class="tsc-name">
        <span class="tsc-title" :title="tool.name">{{ tool.name }}</span>
        <span class="tsc-id gv-mono">{{ tool.tool_id }}</span>
      </div>
      <span class="tsc-status" :title="store.toolStatusLabel(tool.status)">
        <span class="tsc-dot" :class="'dot-' + statusClass(tool.status)" />
        {{ store.toolStatusLabel(tool.status) }}
      </span>
    </div>

    <!-- 描述 -->
    <p class="tsc-desc">{{ tool.description }}</p>

    <!-- 元信息单行：timeout · retries · idempotent key + JSON Schema 折叠 -->
    <div class="tsc-meta">
      <span class="tsc-meta-item gv-mono">timeout {{ fmtTimeout(tool.timeout_ms) }}</span>
      <span class="tsc-sep">·</span>
      <span class="tsc-meta-item gv-mono">retries {{ tool.retries }}</span>
      <span class="tsc-sep">·</span>
      <span class="tsc-meta-item gv-mono" :title="tool.idempotency_key">
        idempotent key: {{ idemLabel }}
      </span>
      <button class="tsc-schema-toggle" type="button" @click="toggleSchema">
        <span>JSON Schema</span>
        <el-icon :class="{ rot: showSchema }"><ArrowDown /></el-icon>
      </button>
    </div>

    <!-- JSON Schema：默认一行摘要，展开显示完整 -->
    <div class="tsc-schema">
      <pre v-if="showSchema" class="tsc-schema-body gv-mono">{{ schemaText }}</pre>
      <div v-else class="tsc-schema-summary gv-mono" :title="schemaText">{{ schemaSummary }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { useToolsStore } from '@/stores/tools'

const props = defineProps({
  /** ToolDef */
  tool: { type: Object, required: true },
})

const store = useToolsStore()

const showSchema = ref(false)

/** 状态点仅两色：可用（单绿 #16a34a）/ 其余（灰 #9ca3af） */
function statusClass(status) {
  return status === 'available' ? 'ok' : 'off'
}

const schemaText = computed(() => {
  try {
    return JSON.stringify(props.tool.schema || {}, null, 2)
  } catch {
    return '{}'
  }
})

/** 一行摘要：{ "type": "object", "properties": [3 个字段] }，超长截断 */
const schemaSummary = computed(() => {
  const s = props.tool.schema || {}
  const parts = [`"type": "${s.type || 'object'}"`]
  const keys = s.properties ? Object.keys(s.properties) : []
  if (keys.length > 0) {
    parts.push(`"properties": [${keys.length} 个字段]`)
  }
  if (Array.isArray(s.required) && s.required.length > 0) {
    parts.push(`"required": [${s.required.join(', ')}]`)
  }
  return `{ ${parts.join(', ')} }`
})

/** 幂等键：有配置显示 required，否则 optional */
const idemLabel = computed(() => (props.tool.idempotency_key ? 'required' : 'optional'))

/** 超时：整秒显示为 s，否则保留 ms */
function fmtTimeout(ms) {
  const n = Number(ms) || 0
  if (n <= 0) return '—'
  return n % 1000 === 0 ? `${n / 1000}s` : `${n}ms`
}

function toggleSchema() {
  showSchema.value = !showSchema.value
}
</script>

<style scoped>
.tool-schema-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  transition: box-shadow 0.15s, border-color 0.15s;
}
.tool-schema-card:hover {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  border-color: #d1d5db;
}
.tsc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.tsc-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tsc-title {
  font-size: 14px; font-weight: 600; color: var(--color-fg-default);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tsc-id { font-size: 11px; color: var(--color-fg-subtle); }
.tsc-status {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; color: var(--color-fg-muted);
  flex-shrink: 0; margin-top: 2px;
}
.tsc-dot { width: 7px; height: 7px; border-radius: 50%; }
.dot-ok { background: #16a34a; }
.dot-off { background: #9ca3af; }

.tsc-desc {
  margin: 0;
  font-size: 12px;
  color: var(--color-fg-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ===== 元信息单行 ===== */
.tsc-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-fg-subtle);
  white-space: nowrap;
  overflow: hidden;
}
.tsc-meta-item { min-width: 0; }
.tsc-sep { color: var(--color-fg-light); }
.tsc-schema-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11px;
  color: var(--color-fg-muted);
  cursor: pointer;
  user-select: none;
}
.tsc-schema-toggle:hover { color: var(--color-fg-default); }
.tsc-schema-toggle .el-icon { transition: transform 0.2s; }
.tsc-schema-toggle .rot { transform: rotate(180deg); }

/* ===== JSON Schema ===== */
.tsc-schema { display: flex; flex-direction: column; }
.tsc-schema-summary {
  font-size: 11px;
  line-height: 1.5;
  color: var(--color-fg-subtle);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tsc-schema-body {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  background: var(--color-canvas-inset);
  border-radius: 6px;
  padding: 10px;
  max-height: 220px;
  overflow: auto;
  color: var(--color-fg-default);
}
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
