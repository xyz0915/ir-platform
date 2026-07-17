<template>
  <div class="attack-path" v-if="nodes.length">
    <div class="ap-title">攻击路径分析</div>
    <svg class="ap-svg" :width="svgWidth" :height="svgHeight" viewBox="0 0 600 180">
      <!-- 连线 -->
      <line v-for="e in edges" :key="e.source_id+'-'+e.target_id"
        :x1="nodeX(e.source_id)" y1="60" :x2="nodeX(e.target_id)" y2="60"
        stroke="var(--color-danger-fg, #dc2626)" stroke-width="1.5"
        stroke-dasharray="4,3" marker-end="url(#arrow)" />
      <!-- 标签 -->
      <text v-for="e in edges" :key="'l'+e.source_id"
        :x="(nodeX(e.source_id) + nodeX(e.target_id)) / 2" y="48"
        text-anchor="middle" font-size="9" fill="var(--color-fg-subtle, #888)">
        {{ e.technique_id }}
      </text>
      <!-- 节点 -->
      <g v-for="n in nodes" :key="n.id" @click="$emit('node-click', n)" style="cursor:pointer">
        <rect :x="nodeX(n.id) - 40" y="50" width="80" height="20" rx="4"
          :fill="n.risk_level === 'critical' ? 'var(--color-danger-fg, #dc2626)' : 'var(--color-accent-fg, #2563eb)'" />
        <text :x="nodeX(n.id)" y="63" text-anchor="middle" font-size="10" fill="#fff">{{ n.hostname || n.label }}</text>
      </g>
      <!-- 箭头 -->
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10" fill="var(--color-danger-fg, #dc2626)" />
        </marker>
      </defs>
    </svg>
    <div class="ap-summary">{{ summary }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  summary: { type: String, default: '' },
})
defineEmits(['node-click'])

const svgWidth = 600
const svgHeight = 180

function nodeX(nodeId) {
  const idx = props.nodes.findIndex(n => n.id === nodeId)
  return 60 + idx * (svgWidth - 120) / Math.max(1, props.nodes.length - 1)
}
</script>

<style scoped>
.attack-path { margin-top: 8px; }
.ap-title { font-size: 12px; font-weight: 500; color: var(--color-fg-default, #111); margin-bottom: 4px; }
.ap-svg { width: 100%; max-width: 600px; }
.ap-summary { font-size: 11px; color: var(--color-fg-subtle, #888); margin-top: 4px; line-height: 1.4; }
</style>
