<template>
  <svg
    class="platform-logo"
    :width="size"
    :height="size"
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    role="img"
    aria-label="应急平台标识"
  >
    <!-- 盾形轮廓：顶部切角，几何克制，传达「安全防护 + 应急响应」语义 -->
    <path
      d="M9 4H23L27 8V14C27 20.5 22.5 25.2 16 28C9.5 25.2 5 20.5 5 14V8Z"
      :stroke="shieldColor"
      stroke-width="2.5"
      stroke-linejoin="round"
    />
    <!-- 对勾：传达「处置完成 / 闭环溯源」语义 -->
    <path
      d="M10.5 15.8L14.3 19.6L21.5 11.8"
      :stroke="checkColor"
      stroke-width="3"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

/**
 * 应急平台统一标识（纯展示组件，无逻辑）。
 *
 * 设计语言：极简几何盾形 + 对勾，双色克制、无线条冗余，
 * 去除此前「白色圆圈云朵 / 通用锁」的 AI 味与通用感。
 *
 * Props:
 *   - size:    渲染尺寸（px），默认 20，同时控制 width / height
 *   - variant: 'light' → 白色图形（绿底/深底场景，如登录页卡头）
 *              'dark'  → 品牌绿盾形 + currentColor 对勾（浅底场景，如顶栏；
 *                        对勾继承文字色，暗色主题下自动变亮，保持可读）
 */
const props = defineProps({
  size: {
    type: Number,
    default: 20
  },
  variant: {
    type: String,
    default: 'dark',
    validator: (value) => ['light', 'dark'].includes(value)
  }
})

const shieldColor = computed(() => (props.variant === 'light' ? '#ffffff' : '#3fa84b'))
// dark 变体对勾用 currentColor：浅色主题下为深色墨迹，暗色主题下自动适配为浅色
const checkColor = computed(() => (props.variant === 'light' ? '#ffffff' : 'currentColor'))
</script>
