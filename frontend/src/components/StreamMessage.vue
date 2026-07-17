<template>
  <span class="stream-msg" :class="{ streaming }">
    {{ displayText }}<span v-if="streaming" class="cursor">|</span>
  </span>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
})

const displayText = ref('')

// 监听 text 变化，直接更新 displayText（由父组件逐字传入）
watch(() => props.text, (val) => {
  displayText.value = val
}, { immediate: true })
</script>

<style scoped>
.stream-msg { white-space: pre-wrap; word-break: break-word; }
.cursor {
  display: inline-block; width: 2px; height: 1em;
  background: var(--color-accent-fg, #2563eb);
  margin-left: 1px; animation: blink .8s step-end infinite; vertical-align: text-bottom;
}
.streaming .cursor { visibility: visible; }
@keyframes blink { 50% { opacity: 0; } }
</style>
