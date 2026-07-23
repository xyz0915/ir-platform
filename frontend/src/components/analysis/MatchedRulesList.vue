<template>
  <div class="matched-rules-card">
    <div class="mrc-title">命中规则 <span v-if="rules.length">({{ rules.length }})</span></div>

    <!-- 无匹配规则 -->
    <div class="mrc-empty" v-if="!rules.length">
      无匹配规则（基于模型推断）
    </div>

    <!-- 规则列表 -->
    <template v-else>
      <div
        v-for="(r, i) in visibleRules"
        :key="r.rule_id || r.rule_name || i"
        class="mrc-rule-item"
      >
        <div class="mrc-rule-top">
          <span class="mrc-rule-name">{{ r.rule_name || r.rule_id || ('规则#' + (i + 1)) }}</span>
          <span class="er-sev" :class="'er-sev-' + (r.severity || 'info')">{{ r.severity }}</span>
        </div>
        <span v-if="r.description" class="mrc-rule-desc">{{ r.description }}</span>
        <span v-if="r.confidence" class="mrc-rule-conf">置信度 {{ r.confidence }}</span>
      </div>

      <!-- 查看更多 -->
      <div class="mrc-more" v-if="rules.length > 3" @click="showAll = !showAll">
        {{ showAll ? '收起' : '查看更多 (' + rules.length + ')' }}
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  rules: { type: Array, default: () => [] },
})

const showAll = ref(false)

const visibleRules = computed(() => {
  if (showAll.value || props.rules.length <= 3) return props.rules
  return props.rules.slice(0, 3)
})
</script>

<style scoped>
.matched-rules-card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 12px;
}
.mrc-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 10px;
}
.mrc-empty {
  font-size: 12px;
  color: var(--color-fg-light);
  padding: 6px 0;
}
.mrc-rule-item {
  padding: 8px 10px;
  background: var(--color-canvas-inset);
  border-radius: 6px;
  margin-bottom: 6px;
}
.mrc-rule-top {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mrc-rule-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-default);
}
.er-sev {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
}
.er-sev-high, .er-sev-critical { background: rgba(220,38,38,0.1); color: #dc2626; }
.er-sev-medium { background: rgba(217,119,6,0.1); color: #d97706; }
.er-sev-low { background: rgba(37,99,235,0.1); color: #2563eb; }
.mrc-rule-desc {
  display: block;
  font-size: 11px;
  color: var(--color-fg-light);
  margin-top: 2px;
}
.mrc-rule-conf {
  display: block;
  font-size: 10px;
  color: var(--color-fg-light);
  margin-top: 2px;
}
.mrc-more {
  font-size: 11px;
  color: var(--color-accent-fg);
  cursor: pointer;
  text-align: center;
  padding: 4px;
  margin-top: 4px;
}
.mrc-more:hover {
  text-decoration: underline;
}
</style>
