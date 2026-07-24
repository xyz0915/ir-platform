<template>
  <div class="tool-schema-card">
    <!-- 头部：名称 + 状态 -->
    <div class="tsc-head">
      <div class="tsc-name">
        <span class="tsc-title">{{ tool.name }}</span>
        <span class="tsc-id gv-mono">{{ tool.tool_id }}</span>
      </div>
      <el-tag
        :type="statusType(tool.status)"
        size="small"
        effect="light"
        class="tsc-status"
      >
        {{ store.toolStatusLabel(tool.status) }}
      </el-tag>
    </div>

    <!-- 描述 -->
    <p class="tsc-desc">{{ tool.description }}</p>

    <!-- 元信息：超时 / 重试 / 幂等键 -->
    <div class="tsc-meta">
      <div class="tsc-meta-item">
        <span class="mi-label">超时</span>
        <span class="mi-value">{{ tool.timeout_ms }}ms</span>
      </div>
      <div class="tsc-meta-item">
        <span class="mi-label">重试</span>
        <span class="mi-value">{{ tool.retries }}</span>
      </div>
      <div class="tsc-meta-item tsc-idepo">
        <span class="mi-label">幂等键</span>
        <span class="mi-value gv-mono" :title="tool.idempotency_key">{{ tool.idempotency_key }}</span>
      </div>
    </div>

    <!-- JSON Schema 预览 -->
    <div class="tsc-schema">
      <div class="tsc-schema-head" @click="toggleSchema">
        <span>JSON Schema</span>
        <el-icon :class="{ 'rot': showSchema }"><ArrowDown /></el-icon>
      </div>
      <pre v-if="showSchema" class="tsc-schema-body gv-mono">{{ schemaText }}</pre>
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
const schemaText = computed(() => {
  try {
    return JSON.stringify(props.tool.schema || {}, null, 2)
  } catch {
    return '{}'
  }
})

function toggleSchema() {
  showSchema.value = !showSchema.value
}

function statusType(status) {
  return { available: 'success', degraded: 'warning', disabled: 'info' }[status] || 'info'
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
  gap: 10px;
  height: 100%;
}
.tsc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.tsc-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tsc-title { font-size: 14px; font-weight: 600; color: var(--color-fg-default); }
.tsc-id { font-size: 11px; color: var(--color-fg-subtle); }
.tsc-desc { margin: 0; font-size: 12px; color: var(--color-fg-muted); line-height: 1.5; }

.tsc-meta { display: flex; gap: 14px; flex-wrap: wrap; }
.tsc-meta-item { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tsc-idepo { flex: 1; min-width: 140px; }
.mi-label { font-size: 11px; color: var(--color-fg-subtle); }
.mi-value { font-size: 12px; color: var(--color-fg-default); }

.tsc-schema { border-top: 0.5px solid var(--color-border-default); padding-top: 8px; }
.tsc-schema-head {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; color: var(--color-fg-muted); cursor: pointer; user-select: none;
}
.tsc-schema-head .el-icon { transition: transform 0.2s; }
.tsc-schema-head .rot { transform: rotate(180deg); }
.tsc-schema-body {
  margin: 8px 0 0; font-size: 11px; line-height: 1.5;
  background: var(--color-canvas-inset); border-radius: 6px; padding: 10px;
  max-height: 220px; overflow: auto; color: var(--color-fg-default);
}
.gv-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
