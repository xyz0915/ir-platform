<template>
  <router-view />
</template>

<script setup>
// 根组件 — 仅渲染路由视图；启动时同步主题，防止刷新闪烁
import { onMounted } from 'vue'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
onMounted(() => {
  themeStore.initTheme()
})
</script>
