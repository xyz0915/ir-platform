<template>
  <el-container class="app-layout">
    <el-aside width="220px" class="app-aside">
      <div class="logo">
        <el-icon size="24"><Lock /></el-icon>
        <span>应急响应平台</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="app-menu"
      >
        <el-menu-item index="/">
          <el-icon><Folder /></el-icon>
          <span>案件管理</span>
        </el-menu-item>
        <el-menu-item index="/ai">
          <el-icon><Cpu /></el-icon>
          <span>AI 分析</span>
        </el-menu-item>
        <el-menu-item index="/rules">
          <el-icon><Setting /></el-icon>
          <span>规则管理</span>
        </el-menu-item>
        <el-menu-item index="/whitelist">
          <el-icon><CircleCheck /></el-icon>
          <span>白名单配置</span>
        </el-menu-item>
        <el-menu-item index="/iocs">
          <el-icon><Warning /></el-icon>
          <span>IOC 指标</span>
        </el-menu-item>
        <el-menu-item index="/threat-intel-config">
          <el-icon><Connection /></el-icon>
          <span>威胁情报外联</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <div class="header-left">
          <span class="page-breadcrumb">{{ currentRouteName }}</span>
        </div>
        <div class="header-right">
          <el-button
            class="theme-toggle"
            text
            :title="themeStore.theme === 'dark' ? '切换到亮色' : '切换到暗色'"
            @click="themeStore.toggleTheme()"
          >
            <el-icon size="18">
              <component :is="themeStore.theme === 'dark' ? Sunny : Moon" />
            </el-icon>
          </el-button>
          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-icon><User /></el-icon>
              {{ authStore.user?.username || '用户' }}
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { Cpu, Lock, CircleCheck, Warning, Connection, Sunny, Moon } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()

const activeMenu = computed(() => {
  if (route.path.startsWith('/cases') || route.path.startsWith('/hosts')) return '/'
  if (route.path === '/whitelist') return '/whitelist'
  if (route.path === '/iocs') return '/iocs'
  return route.path
})

const currentRouteName = computed(() => {
  const names = {
    'CaseList': '案件管理',
    'CaseDetail': '案件详情',
    'HostDetail': '主机详情',
    'Report': '分析报告',
    'Rules': '规则管理',
    'Whitelist': '白名单配置',
    'Iocs': 'IOC 指标管理',
    'ThreatIntelConfig': '威胁情报外联配置'
  }
  return names[route.name] || '应急响应平台'
})

function handleCommand(command) {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.app-layout {
  height: 100%;
}

.app-aside {
  background: var(--color-sidebar-bg);
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-fg-on-emphasis);
  font-size: 16px;
  font-weight: bold;
  gap: 8px;
  border-bottom: 1px solid var(--color-sidebar-border);
}

.app-menu {
  border: none;
  background: var(--color-sidebar-bg);
}

.app-menu .el-menu-item {
  color: var(--color-sidebar-fg-muted);
}

.app-menu .el-menu-item:hover {
  background: var(--color-sidebar-hover-bg);
}

.app-menu .el-menu-item.is-active {
  background: var(--color-sidebar-active-bg);
  color: var(--color-fg-on-emphasis);
}

.app-header {
  background: var(--color-canvas-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--color-border-default);
  height: 60px;
}

.page-breadcrumb {
  font-size: 16px;
  font-weight: bold;
  color: var(--color-fg-default);
}

.theme-toggle {
  margin-right: 8px;
  color: var(--color-fg-muted);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  color: var(--color-fg-muted);
}

.app-main {
  background: var(--color-canvas-subtle);
  padding: 20px;
  overflow-y: auto;
}
</style>
