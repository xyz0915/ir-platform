<template>
  <div class="cfg-sect">
    <div v-if="warn" class="cfg-warn">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/>
        <line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
      <span>{{ warn }}</span>
      <a v-if="warnLink" style="margin-left:auto;cursor:pointer;color:var(--color-accent-fg)" @click="$emit('warnAction')">查看</a>
    </div>
    <div class="cfg-sect-title">{{ title }}</div>
    <slot />
  </div>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    required: true,
  },
  warn: {
    type: String,
    default: '',
  },
  warnLink: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['warnAction'])
</script>

<style scoped>
.cfg-sect {
  padding: 14px 16px;
  border-bottom: 0.5px solid var(--color-border-default);
}
.cfg-sect-title {
  font-size: 10px;
  font-weight: 500;
  color: var(--color-fg-light);
  letter-spacing: 0.3px;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.cfg-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  margin-bottom: 8px;
  background: var(--color-warning-subtle);
  border: 0.5px solid #fde68a;
  border-radius: var(--r-btn);
  font-size: 11px;
  color: var(--color-warning-fg);
}
</style>
