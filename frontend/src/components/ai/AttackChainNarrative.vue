<template>
  <div class="attack-chain-narrative">
    <div class="ac-title">攻击链叙述（引擎命中，仅叙述不重判）</div>
    <el-empty v-if="!hits.length" description="无攻击链命中" :image-size="48" />

    <div v-for="(hit, i) in hits" :key="i" class="ac-hit">
      <div class="ac-head">
        <span class="ac-rule">{{ hit.rule_name }}</span>
        <el-tag :type="sevType(hit.severity)" size="small" effect="dark">{{ hit.severity }}</el-tag>
      </div>
      <div class="ac-reason">{{ hit.reason }}</div>
      <ol v-if="hit.steps?.length" class="ac-steps">
        <li v-for="(s, si) in hit.steps" :key="si">
          步骤 {{ s.step }} · {{ s.dimension }}：{{ s.summary }}
        </li>
      </ol>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  attackChainHits: { type: Array, default: () => [] },
})

const hits = computed(() => props.attackChainHits || [])

function sevType(s) {
  const m = { critical: 'danger', high: 'danger', medium: 'warning', low: 'success' }
  return m[s] || 'info'
}
</script>

<style scoped>
.attack-chain-narrative { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 12px 14px; }
.ac-title { font-weight: 600; font-size: 15px; margin-bottom: 8px; }
.ac-hit { border-top: 1px dashed var(--el-border-color); padding: 8px 0; }
.ac-head { display: flex; align-items: center; gap: 8px; }
.ac-rule { font-weight: 600; }
.ac-reason { color: #555; font-size: 13px; margin: 4px 0; white-space: pre-wrap; }
.ac-steps { margin: 4px 0 0; padding-left: 18px; color: #666; font-size: 12px; }
</style>
