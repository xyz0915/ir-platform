<template>
  <div class="stat-card">
    <div class="sc-head">
      <el-icon v-if="icon" :size="18"><component :is="icon" /></el-icon>
      <span class="sc-label">{{ label }}</span>
    </div>
    <div class="sc-value">
      {{ value }}<small v-if="unit">{{ unit }}</small>
    </div>
  </div>
</template>

<script setup>
/**
 * 设置模块统一统计卡（扁平描边风格）
 *
 * 供 AgentManagement / DataStorageView / AiView 三个页面复用，
 * 保证「三页统计卡视觉规格完全一致」。
 *
 * 设计契约（不可放宽）：
 * - **不提供 color / tone prop** —— 从类型层面杜绝「四张卡四种颜色」回潮；
 * - 图标不单独着色，靠 `currentColor` 继承 `.sc-head` 的中性灰；
 * - 无背景实底块、无 box-shadow、无渐变，仅 0.5px 描边。
 */
defineProps({
  /** 统计项名称，例如「本月总 Token」 */
  label: { type: String, required: true },
  /** 统计数值，已格式化好的字符串或原始数字 */
  value: { type: [String, Number], default: '—' },
  /** 数值单位后缀，例如 'ms' / '%'；留空则不渲染 */
  unit: { type: String, default: '' },
  /** 线性图标组件引用，仅接受 @element-plus/icons-vue 的组件；不传则不渲染图标 */
  icon: { type: [Object, Function], default: null },
})
</script>

<style scoped>
.stat-card {
  flex: 1;
  min-width: 0;
  padding: 16px 20px;
  background: var(--color-canvas-default, #ffffff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
}

.sc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  /* 图标不单独着色，通过 currentColor 继承此处的中性灰 */
  color: var(--color-fg-subtle, #888888);
}

.sc-label {
  font-size: 12px;
  font-weight: 400;
}

.sc-value {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 500;
  line-height: 1.2;
  color: var(--color-fg-default, #111111);
}

.sc-value small {
  margin-left: 2px;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
}
</style>
