<template>
  <el-tag :type="tagType" :size="size" effect="dark">
    {{ label }}
  </el-tag>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  level: { type: String, default: 'info' },
  size: { type: String, default: 'default' }
})

const tagType = computed(() => {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary',
    info: 'info'
  }
  return map[props.level] || 'info'
})

const label = computed(() => {
  const map = {
    critical: '严重',
    high: '高危',
    medium: '中危',
    low: '低危',
    info: '信息'
  }
  return map[props.level] || props.level
})
</script>
