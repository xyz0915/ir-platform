<template>
  <div class="disposition-panel">
    <div class="dp-title">处置记录</div>

    <!-- 处置列表 -->
    <div class="dp-list" v-if="dispositions.length">
      <div v-for="d in dispositions" :key="d.id" class="dp-item">
        <span class="dp-time">{{ d.created_at }}</span>
        <div>
          <span class="dp-actor">{{ d.operator }}</span>
          <span class="dp-action">{{ actionLabel(d.action) }}</span>
          <div v-if="d.comment" class="dp-comment">"{{ d.comment }}"</div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div class="dp-empty" v-else>暂无处置记录</div>

    <!-- 快速添加备注 -->
    <div class="dp-input-wrap">
      <input v-model="comment" class="dp-input" placeholder="添加处置备注..." @keyup.enter="onAdd">
      <button class="btn btn-sm btn-primary" @click="onAdd" :disabled="!comment.trim()">发送</button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  dispositions: { type: Array, default: () => [] },
  eventId: { type: String, default: '' },
})

const emit = defineEmits(['add-disposition'])

const comment = ref('')

const ACTION_LABELS = {
  isolate: '隔离主机', kill_process: '结束进程', block_ip: '封锁IP',
  add_rule: '添加规则', escalate: '上报', ignore: '忽略',
  review: '复核',
}

function actionLabel(a) {
  return ACTION_LABELS[a] || a
}

function onAdd() {
  if (!comment.value.trim()) return
  emit('add-disposition', comment.value.trim())
  comment.value = ''
}
</script>

<style scoped>
.disposition-panel {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 10px;
}
.dp-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 10px;
}
.dp-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dp-item {
  display: flex;
  gap: 8px;
  font-size: 12px;
}
.dp-time {
  font-size: 10px;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
  white-space: nowrap;
  padding-top: 1px;
}
.dp-actor {
  font-weight: 500;
  margin-right: 8px;
}
.dp-action {
  color: var(--color-fg-subtle);
}
.dp-comment {
  font-size: 11px;
  color: var(--color-fg-light);
  margin-top: 2px;
  font-style: italic;
}
.dp-empty {
  font-size: 12px;
  color: var(--color-fg-light);
  padding: 4px 0;
}
.dp-input-wrap {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}
.dp-input {
  flex: 1;
  padding: 4px 8px;
  font-size: 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
  outline: none;
}
.dp-input:focus {
  border-color: var(--color-accent-fg);
}
.btn {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  font-size: 11px;
  border-radius: 6px;
  border: 0.5px solid var(--color-border-default);
  cursor: pointer;
  transition: all 0.15s;
}
.btn-sm { padding: 4px 10px; font-size: 11px; }
.btn-primary { background: var(--color-accent-fg, #2563eb); color: #fff; border-color: var(--color-accent-fg); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
