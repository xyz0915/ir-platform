<template>
  <div v-if="visible" class="confirm-overlay" @click.self="cancel">
    <div class="confirm-card">
      <div class="confirm-title">⚠ 确认操作</div>
      <div class="confirm-body">
        <p>即将{{ actionLabel }}<strong>{{ target }}</strong></p>
        <p class="confirm-reason">{{ reason }}</p>
      </div>
      <div class="confirm-actions">
        <el-button size="small" @click="cancel">取消</el-button>
        <el-button size="small" type="primary" @click="confirm">确认执行</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({
  visible: Boolean, action: String, target: String, reason: String, confirmId: String,
})
const emit = defineEmits(['confirm', 'cancel'])
const actionLabel = computed(() => ({ block_ip: '封锁 IP ', isolate_host: '隔离主机 ' })[props.action] || props.action + ' ')
function confirm() { emit('confirm', { action: props.action, target: props.target, confirm_id: props.confirmId }) }
function cancel() { emit('cancel') }
</script>

<style scoped>
.confirm-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; z-index: 2000; }
.confirm-card { background: var(--color-canvas-default, #fff); border-radius: 12px; padding: 24px; max-width: 400px; width: 90%; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
.confirm-title { font-size: 15px; font-weight: 500; margin-bottom: 12px; }
.confirm-body { font-size: 13px; color: var(--color-fg-default, #111); margin-bottom: 20px; line-height: 1.6; }
.confirm-reason { font-size: 12px; color: var(--color-fg-subtle, #888); }
.confirm-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
