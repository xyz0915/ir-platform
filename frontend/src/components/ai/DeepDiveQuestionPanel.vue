<template>
  <div class="panel">
    <div class="panel-header">推荐追问</div>
    <div v-if="questions.length" class="question-list">
      <el-button
        v-for="(item, index) in questions"
        :key="index"
        text
        class="question-btn"
        @click="$emit('select', item)"
      >
        <span class="question-title">{{ item.title }}</span>
        <span class="question-text">{{ item.question }}</span>
      </el-button>
    </div>
    <div v-else class="empty">暂无推荐追问</div>
  </div>
</template>

<script setup>
defineProps({
  questions: { type: Array, default: () => [] },
})

defineEmits(['select'])
</script>

<style scoped>
.panel { padding: 14px; border: 1px solid #ebeef5; border-radius: 8px; background: #fff; }
.panel-header { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.question-list { display: flex; flex-direction: column; gap: 8px; }
.question-btn { justify-content: flex-start; height: auto; white-space: normal; padding: 10px; border: 1px solid #ebeef5; border-radius: 6px; }
.question-title { display: block; font-weight: 600; color: #303133; margin-bottom: 4px; }
.question-text { display: block; font-size: 12px; color: #606266; line-height: 1.6; text-align: left; }
.empty { font-size: 12px; color: #909399; }
</style>
