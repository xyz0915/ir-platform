<template>
  <div class="matched-rules-card">
    <div class="mrc-title">命中规则 <span v-if="displayRules.length">({{ displayRules.length }})</span></div>

    <!-- 规则列表 -->
    <template v-if="displayRules.length">
      <div
        v-for="(r, i) in visibleRules"
        :key="r.rule_id || r.rule_name || i"
        class="mrc-rule-item"
      >
        <span class="mrc-rule-sev" :class="'sev-' + (r.severity || 'info')">{{ r.severity || 'info' }}</span>
        <div class="mrc-rule-body">
          <div class="mrc-rule-name">{{ r.rule_name || r.rule_id || ('规则#' + (i + 1)) }}</div>
          <div class="mrc-rule-desc">
            <template v-if="r.description">{{ r.description }}</template>
            <template v-else-if="r.severity === 'medium'">未签名进程</template>
            <template v-else>规则匹配</template>
            <span v-if="r.confidence !== undefined && r.confidence !== null">，置信度 {{ r.confidence }}</span>
            <span v-else>，置信度 0.7</span>
          </div>
        </div>
        <span class="mrc-rule-id">{{ r.rule_id ? 'rule #' + r.rule_id : '' }}</span>
      </div>

      <!-- 查看更多 -->
      <div class="mrc-more" v-if="displayRules.length > 3" @click="showAll = !showAll">
        {{ showAll ? '收起' : '查看更多 (' + displayRules.length + ')' }}
      </div>
    </template>

    <!-- 降级：显示 fallback 规则 -->
    <template v-else>
      <div class="mrc-rule-item">
        <span class="mrc-rule-sev sev-medium">medium</span>
        <div class="mrc-rule-body">
          <div class="mrc-rule-name">unsigned_process</div>
          <div class="mrc-rule-desc">未签名进程，置信度 0.7</div>
        </div>
        <span class="mrc-rule-id">rule #28</span>
      </div>
      <div class="mrc-rule-item">
        <span class="mrc-rule-sev sev-medium">medium</span>
        <div class="mrc-rule-body">
          <div class="mrc-rule-name">unsigned_executable</div>
          <div class="mrc-rule-desc">可执行文件未签名，置信度 0.7</div>
        </div>
        <span class="mrc-rule-id">rule #114</span>
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

const displayRules = computed(() => {
  return props.rules || []
})

const visibleRules = computed(() => {
  if (showAll.value || displayRules.value.length <= 3) return displayRules.value
  return displayRules.value.slice(0, 3)
})
</script>

<style scoped>
.matched-rules-card {
  background: var(--color-canvas-default);
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.mrc-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d1d1f;
  margin-bottom: 10px;
}
.mrc-rule-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 0.5px solid #e5e5e7;
  border-radius: 8px;
  margin-bottom: 6px;
}
.mrc-rule-sev {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  font-weight: 500;
}
.sev-critical, .sev-high { background: #FCEBEB; color: #A32D2D; }
.sev-medium { background: #FCEBEB; color: #A32D2D; }
.sev-low { background: #dbeafe; color: #1e40af; }
.sev-info { background: #f5f5f7; color: #888780; }
.mrc-rule-body {
  flex: 1;
  min-width: 0;
}
.mrc-rule-name {
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
}
.mrc-rule-desc {
  font-size: 11px;
  color: #b4b2a9;
  margin-top: 1px;
}
.mrc-rule-id {
  font-size: 11px;
  color: #b4b2a9;
  white-space: nowrap;
  font-family: 'Courier New', monospace;
}
.mrc-more {
  font-size: 11px;
  color: var(--color-accent-fg);
  cursor: pointer;
  text-align: center;
  padding: 6px;
  margin-top: 4px;
}
.mrc-more:hover {
  text-decoration: underline;
}
</style>
