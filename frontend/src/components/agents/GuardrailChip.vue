<template>
  <div class="guardrail-chip">
    <!-- 总体结论：单色点 + 文字（通过绿 / 拦截红克制） -->
    <span class="gc-main" :class="result?.passed ? 'ok' : 'block'">
      <span class="gc-dot" />
      {{ result?.passed ? '护栏通过' : '护栏拦截' }}
    </span>

    <!-- 命中策略：中性 chip -->
    <span v-if="result?.policy_id" class="gc-item gc-mono">策略 {{ result.policy_id }}</span>

    <!-- 白名单命中：中性 chip -->
    <span v-if="result?.policy_id" class="gc-item">
      白名单{{ result.whitelist_hit ? '命中' : '未命中' }}
    </span>

    <!-- 强制确认：中性 chip -->
    <span v-if="result?.requires_confirm" class="gc-item">需确认</span>

    <!-- 回滚预案：中性 chip -->
    <span v-if="result?.requires_rollback_plan" class="gc-item">有回滚预案</span>
  </div>
</template>

<script setup>
/**
 * GuardrailChip —— 护栏结果 chips。
 *
 * 渲染 GuardrailResult（policy_id / whitelist_hit / requires_confirm /
 * requires_rollback_plan / passed），用于 HITL 上下文面板与护栏页联动展示。
 * 设计依据：01-api-spec.md §6.1 / §7。
 */
const props = defineProps({
  /** GuardrailResult */
  result: { type: Object, default: null },
})
</script>

<style scoped>
.guardrail-chip { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }

/* 总体结论：单色点 + 文字，不再使用 success/danger 彩色 tag */
.gc-main { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: #111827; }
.gc-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.gc-main.ok .gc-dot { background: #16a34a; }
.gc-main.block .gc-dot { background: #dc2626; }

/* 细节项：中性 chip（灰字 + 浅底 + 细边框） */
.gc-item {
  font-size: 12px; font-weight: 500; color: #4b5563;
  background: var(--color-canvas-subtle);
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  padding: 1px 8px;
}
.gc-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
