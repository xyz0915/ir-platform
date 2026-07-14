<template>
  <div class="chs">
    <div class="chs-group">
      <label class="chs-label">案件</label>
      <select
        class="chs-select"
        :value="selectedCaseId"
        @change="onCaseChange"
      >
        <option :value="null">全部案件</option>
        <option v-for="c in cases" :key="c.id" :value="c.id">
          {{ c.name || ('案件 #' + c.id) }}
        </option>
      </select>
    </div>
    <div class="chs-group">
      <label class="chs-label">主机</label>
      <select
        class="chs-select"
        :value="selectedHostId"
        :disabled="!selectedCaseId"
        @change="onHostChange"
      >
        <option :value="null">{{ selectedCaseId ? '全部主机' : '请先选择案件' }}</option>
        <option v-for="h in filteredHosts" :key="h.id" :value="h.id">
          {{ h.hostname || ('主机 #' + h.id) }}
          <template v-if="h.ip_address">({{ h.ip_address }})</template>
        </option>
      </select>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  cases: { type: Array, default: () => [] },
  hosts: { type: Array, default: () => [] },
  selectedCaseId: { type: Number, default: null },
  selectedHostId: { type: Number, default: null },
})

const emit = defineEmits(['update:caseId', 'update:hostId'])

const filteredHosts = computed(() => {
  if (!props.selectedCaseId) return []
  return props.hosts.filter(h => h.case_id === props.selectedCaseId)
})

function onCaseChange(e) {
  const val = e.target.value === '' ? null : Number(e.target.value)
  emit('update:caseId', val)
  // 切换案件时清空主机
  if (val !== props.selectedCaseId) {
    emit('update:hostId', null)
  }
}

function onHostChange(e) {
  const val = e.target.value === '' ? null : Number(e.target.value)
  emit('update:hostId', val)
}
</script>

<style scoped>
.chs {
  display: flex;
  gap: 12px;
  align-items: center;
}
.chs-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.chs-label {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  white-space: nowrap;
}
.chs-select {
  font-size: 12px;
  padding: 4px 8px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  outline: none;
  min-width: 120px;
  cursor: pointer;
}
.chs-select:focus {
  border-color: var(--color-accent-fg, #2563eb);
}
.chs-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
