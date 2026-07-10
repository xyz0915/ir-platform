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
import { Cpu, Lock, CircleCheck, Warning, Connection } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

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
  background: #304156;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 16px;
  font-weight: bold;
  gap: 8px;
  border-bottom: 1px solid #3d4d5f;
}

.app-menu {
  border: none;
  background: #304156;
}

.app-menu .el-menu-item {
  color: #bfcbd9;
}

.app-menu .el-menu-item:hover {
  background: #263445;
}

.app-menu .el-menu-item.is-active {
  background: #1f2d3d;
  color: #409EFF;
}

.app-header {
  background: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e6e6e6;
  height: 60px;
}

.page-breadcrumb {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  color: #606266;
}

.app-main {
  background: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}
</style>
