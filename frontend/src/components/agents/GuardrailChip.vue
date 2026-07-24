<template>
  <div class="guardrail-chip">
    <!-- 总体结论 -->
    <el-tag :type="result?.passed ? 'success' : 'danger'" size="small" effect="light" class="gc-main">
      {{ result?.passed ? '护栏通过' : '护栏拦截' }}
    </el-tag>

    <!-- 命中策略 -->
    <el-tag v-if="result?.policy_id" size="small" effect="plain" class="gc-item">
      策略 {{ result.policy_id }}
    </el-tag>

    <!-- 白名单命中 -->
    <el-tag
      v-if="result?.policy_id"
      :type="result.whitelist_hit ? 'success' : 'info'"
      size="small"
      effect="plain"
      class="gc-item"
    >
      白名单{{ result.whitelist_hit ? '命中' : '未命中' }}
    </el-tag>

    <!-- 强制确认 -->
    <el-tag v-if="result?.requires_confirm" type="warning" size="small" effect="plain" class="gc-item">
      需确认
    </el-tag>

    <!-- 回滚预案 -->
    <el-tag v-if="result?.requires_rollback_plan" type="info" size="small" effect="plain" class="gc-item">
      有回滚预案
    </el-tag>
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
.gc-item { font-weight: 500; }
.gc-main { font-weight: 600; }
</style>
