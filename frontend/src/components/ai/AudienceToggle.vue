<template>
  <div class="audience-toggle">
    <span class="at-label">受众</span>
    <el-radio-group :model-value="modelValue" @update:model-value="onChange" size="small">
      <el-radio-button value="technical">技术</el-radio-button>
      <el-radio-button value="executive">管理层</el-radio-button>
      <el-radio-button value="both">双受众</el-radio-button>
    </el-radio-group>
  </div>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: String, default: 'technical' },
})

const emit = defineEmits(['update:modelValue'])

function onChange(val) {
  emit('update:modelValue', val)
}
</script>

<style scoped>
.audience-toggle { display: flex; align-items: center; gap: 8px; }
.at-label { font-size: 13px; color: #666; }
</style>
