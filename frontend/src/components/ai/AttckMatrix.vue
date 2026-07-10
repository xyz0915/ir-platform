<template>
  <div class="attck-matrix">
    <div class="am-title">
      ATT&CK 技术矩阵
      <span class="am-count">{{ techniques.length }} 项 / 攻击链 {{ chainCount }} 条</span>
    </div>
    <el-empty v-if="!techniques.length" description="本次分析未产出 ATT&CK 技术点" :image-size="48" />

    <div v-for="(group, tac) in grouped" :key="tac" class="am-group">
      <div class="am-tactic">{{ tac }}</div>
      <div class="am-chips">
        <el-tag
          v-for="(t, i) in group"
          :key="i"
          :type="t._inChain ? 'danger' : (t.known === false ? 'info' : 'primary')"
          effect="light"
          class="am-chip"
        >
          {{ t.id }} · {{ t.name }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  // mitreAttack: 已查表的技术点列表 [{id,name,tactic,tactic_id,known}]
  mitreAttack: { type: Array, default: () => [] },
  // attackChainHits: 攻击链命中列表（用于高亮）
  attackChainHits: { type: Array, default: () => [] },
})

const techniques = computed(() => props.mitreAttack || [])

const chainIds = computed(() => {
  const ids = new Set()
  for (const hit of props.attackChainHits || []) {
    for (const s of hit?.steps || []) {
      if (s?.technique_id) ids.add(String(s.technique_id))
    }
  }
  return ids
})

const grouped = computed(() => {
  const g = {}
  for (const t of techniques.value) {
    const tac = t.tactic || '未分类'
    const item = { ...t, _inChain: chainIds.value.has(String(t.id)) }
    ;(g[tac] = g[tac] || []).push(item)
  }
  return g
})

const chainCount = computed(() => (props.attackChainHits || []).length)
</script>

<style scoped>
.attck-matrix { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; }
.am-title { font-weight: 600; font-size: 15px; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
.am-count { font-size: 12px; color: #999; font-weight: 400; }
.am-group { border-top: 1px dashed var(--el-border-color); padding: 8px 0; }
.am-tactic { font-weight: 600; color: #444; font-size: 13px; margin-bottom: 6px; }
.am-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.am-chip { font-family: monospace; }
</style>
