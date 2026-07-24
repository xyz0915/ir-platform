<template>
  <div class="trace-tree">
    <el-empty v-if="!trace.length" description="暂无 trace 数据" :image-size="50" />
    <div v-for="node in tree" :key="node.span_id" class="tt-node" :style="{ paddingLeft: node.depth * 18 + 8 + 'px' }">
      <span class="tt-bar" :style="{ background: colorFor(node) }" />
      <span class="tt-name">{{ node.name }}</span>
      <span class="tt-dur">{{ formatMs(node.duration_ms) }}</span>
      <span class="tt-time" v-if="node.started_at">{{ shortTime(node.started_at) }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** TraceSpan[] */
  trace: { type: Array, default: () => [] },
})

/** 根据 parent_id 计算树深度 */
const tree = computed(() => {
  const map = new Map(props.trace.map((s) => [s.span_id, { ...s, depth: 0 }]))
  // 记录子节点，按出现顺序保持
  const visited = new Set()
  const ordered = []
  const roots = props.trace.filter((s) => !s.parent_id || !map.has(s.parent_id))
  const queue = [...roots]
  while (queue.length) {
    const cur = queue.shift()
    if (!cur || visited.has(cur.span_id)) continue
    visited.add(cur.span_id)
    const node = map.get(cur.span_id)
    ordered.push(node)
    props.trace
      .filter((s) => s.parent_id === cur.span_id)
      .forEach((child) => {
        const cn = map.get(child.span_id)
        if (cn) cn.depth = (node?.depth || 0) + 1
        queue.push(child)
      })
  }
  // 补充未被树覆盖的孤立节点
  props.trace.forEach((s) => {
    if (!visited.has(s.span_id)) {
      const cn = map.get(s.span_id)
      if (cn) { cn.depth = 0; ordered.push(cn); visited.add(s.span_id) }
    }
  })
  return ordered
})

function colorFor(node) {
  const n = (node.name || '').toLowerCase()
  if (n.includes('guardrail')) return '#F59E0B'
  if (n.includes('hitl')) return '#22C55E'
  if (n.includes('reflect')) return '#8B5CF6'
  if (n.includes('error') || n.includes('fail')) return '#EF4444'
  return '#3B82F6'
}

function formatMs(ms) {
  if (!ms) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function shortTime(iso) {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}
</script>

<style scoped>
.trace-tree { display: flex; flex-direction: column; gap: 2px; }
.tt-node { display: flex; align-items: center; gap: 8px; padding: 5px 6px; border-radius: 6px; font-size: 12px; }
.tt-node:hover { background: var(--color-canvas-subtle); }
.tt-bar { width: 3px; height: 14px; border-radius: 2px; flex-shrink: 0; }
.tt-name { font-weight: 500; color: var(--color-fg-default); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tt-dur { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--color-fg-muted); }
.tt-time { color: var(--color-fg-subtle); font-size: 11px; font-family: ui-monospace, monospace; }
</style>
