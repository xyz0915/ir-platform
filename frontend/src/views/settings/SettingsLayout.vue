<template>
  <div class="settings-layout">
    <div class="settings-sidebar">
      <div
        v-for="item in menuItems"
        :key="item.path"
        :class="['sidebar-item', { active: currentPath === item.path }]"
        @click="navigate(item.path)"
      >
        <el-icon :size="16" class="sidebar-icon"><component :is="item.icon" /></el-icon>
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
import { User, Document, Monitor, Files, Tools, Brush, SetUp } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

/**
 * 侧边栏菜单项。
 * icon 存放 @element-plus/icons-vue 的线性图标组件引用（禁止 emoji）。
 * 「主机 Agent」使用 Monitor（受管终端语义），不用 Cpu，避免与系统资源监控混淆。
 */
const menuItems = [
  { icon: User, label: '用户与权限', path: '/settings/users' },
  { icon: Document, label: '审计日志', path: '/settings/audit-logs' },
  { icon: Monitor, label: '主机 Agent', path: '/settings/agents' },
  { icon: Files, label: '数据与存储', path: '/settings/storage' },
  { icon: Tools, label: '系统参数', path: '/settings/params' },
  { icon: Brush, label: '主题与外观', path: '/settings/theme' },
  { icon: SetUp, label: '模型配置与审计', path: '/settings/model-config-audit' },
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
  width: 240px;
  min-width: 240px;
  background: var(--color-canvas-default, #ffffff);
  border-right: 0.5px solid var(--color-border-default, #e5e5e5);
  padding: 16px 0;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 20px;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-fg-muted, #555555);
  transition: background-color 0.15s, color 0.15s;
  border-left: 2px solid transparent;
}

.sidebar-item:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-default, #111111);
}

.sidebar-item.active {
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
  font-weight: 500;
  border-left-color: var(--color-accent-fg, #2563eb);
}

/* 图标不单独着色，跟随 .sidebar-item 的文字色（currentColor） */
.sidebar-icon {
  flex-shrink: 0;
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
