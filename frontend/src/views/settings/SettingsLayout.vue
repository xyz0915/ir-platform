<template>
  <div class="settings-layout">
    <div class="settings-sidebar">
      <div
        v-for="item in menuItems"
        :key="item.path"
        :class="['sidebar-item', { active: currentPath === item.path }]"
        @click="navigate(item.path)"
      >
        <span class="sidebar-emoji">{{ item.emoji }}</span>
        <span class="sidebar-label">{{ item.label }}</span>
      </div>
    </div>
    <div class="settings-content">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const menuItems = [
  { emoji: '👤', label: '用户与权限', path: '/settings/users' },
  { emoji: '📋', label: '审计日志', path: '/settings/audit-logs' },
  { emoji: '🤖', label: 'Agent 管理', path: '/settings/agents' },
  { emoji: '💾', label: '数据与存储', path: '/settings/storage' },
  { emoji: '🔧', label: '系统参数', path: '/settings/params' },
  { emoji: '🎨', label: '主题与外观', path: '/settings/theme' },
]

const currentPath = computed(() => route.path)

function navigate(path) {
  if (route.path !== path) {
    router.push(path)
  }
}
</script>

<style scoped>
.settings-layout {
  display: flex;
  height: 100%;
  min-height: calc(100vh - 52px);
}

.settings-sidebar {
  width: 200px;
  min-width: 200px;
  background: var(--color-canvas-default, #fff);
  border-right: 1px solid var(--color-border-default, #e5e7eb);
  padding: 16px 0;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  cursor: pointer;
  font-size: 14px;
  color: var(--color-fg-muted, #6b7280);
  transition: all 0.15s;
  border-left: 3px solid transparent;
}

.sidebar-item:hover {
  background: var(--color-canvas-subtle, #f9fafb);
  color: var(--color-accent-fg, #059669);
}

.sidebar-item.active {
  background: var(--color-accent-subtle, #ecfdf5);
  color: var(--color-accent-fg, #059669);
  font-weight: 600;
  border-left-color: var(--color-accent-emphasis, #059669);
}

.sidebar-emoji {
  font-size: 16px;
}

.sidebar-label {
  white-space: nowrap;
}

.settings-content {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
}
</style>
