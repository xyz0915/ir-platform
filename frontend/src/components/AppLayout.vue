<template>
  <div class="app-layout">
    <!-- ===== 横向导航栏 ===== -->
    <div class="top-nav">
      <div class="nav-left">
        <div class="logo">
          <el-icon :size="20"><Lock /></el-icon>
          <span>应急平台</span>
        </div>

        <div class="nav-tabs" v-for="group in navGroups" :key="group.label">
          <div
            :class="['nav-tab', { active: activeGroup === group.label }]"
            @mouseenter="hoverGroup = group.label"
            @mouseleave="hoverGroup = ''"
            @click="openFirstChild(group)"
          >
            {{ group.emoji }} {{ group.label }}
            <span v-if="group.badge" class="nav-badge">{{ alertCount }}</span>
            <div class="nav-dropdown" v-if="hoverGroup === group.label || activeGroup === group.label">
              <div
                v-for="child in group.children"
                :key="child.path"
                :class="['nav-item', { active: route.path === child.path || (child.activeMatch && route.path.startsWith(child.activeMatch)) }]"
                @click.stop="navigate(child)"
              >
                <span class="nav-dot" />
                {{ child.emoji }} {{ child.label }}
                <span v-if="child.badge" class="nav-item-badge">{{ alertCount }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="nav-right">
        <el-button text @click="themeStore.toggleTheme()" class="nav-btn">
          <el-icon size="18"><component :is="themeStore.theme === 'dark' ? Sunny : Moon" /></el-icon>
        </el-button>
        <el-dropdown @command="handleCommand">
          <span class="user-trigger">
            <el-icon><User /></el-icon>
            <span class="user-name">{{ authStore.user?.username || '用户' }}</span>
            <el-icon class="user-arrow"><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- ===== 主内容 ===== -->
    <div class="main-content">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { Lock, Sunny, Moon, User, ArrowDown } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()

const hoverGroup = ref('')

// ===== 导航配置 =====
const alertCount = computed(() => 0) // 可从告警 store 获取

const navGroups = [
  {
    emoji: '📊',
    label: '态势感知',
    path: '/',
    children: [
      { emoji: '📈', label: '全局态势', path: '/' },
      { emoji: '🚨', label: '告警监控', path: '/alerts', badge: true, activeMatch: '/alerts' },
      { emoji: '📋', label: '日志分析', path: '/logs', activeMatch: '/logs' },
    ],
  },
  {
    emoji: '📁',
    label: '案件管理',
    path: '/cases',
    children: [
      { emoji: '📂', label: '案件列表', path: '/cases', activeMatch: '/cases' },
      { emoji: '🖥', label: '主机详情', path: '/hosts/:id', activeMatch: '/hosts' },
    ],
  },
  {
    emoji: '📄',
    label: '报告输出',
    path: '',
    children: [
      { emoji: '📝', label: '分析报告', path: '/hosts/:id/report', activeMatch: '/report' },
    ],
  },
  {
    emoji: '🤖',
    label: '智能分析',
    path: '',
    children: [
      { emoji: '🧠', label: 'AI 分析', path: '/ai' },
      { emoji: '📚', label: '知识库', path: '/knowledge', activeMatch: '/knowledge' },
    ],
  },
  {
    emoji: '⚙️',
    label: '检测配置',
    path: '',
    children: [
      { emoji: '📏', label: '规则管理', path: '/rules' },
      { emoji: '🎯', label: '策略配置', path: '/policies' },
      { emoji: '✅', label: '白名单', path: '/whitelist' },
      { emoji: '⚡', label: 'IOC 指标', path: '/iocs' },
      { emoji: '🌐', label: '威胁情报', path: '/threat-intel-config' },
    ],
  },
]

// ===== 活跃分组 =====
const activeGroup = computed(() => {
  const p = route.path
  for (const g of navGroups) {
    for (const c of g.children) {
      if (p === c.path || (c.activeMatch && p.startsWith(c.activeMatch))) return g.label
    }
  }
  return navGroups[0].label
})

// ===== 页面元信息 =====
const routeMeta = computed(() => {
  const names = {
    'Dashboard': { title: '全局态势', subtitle: '应急响应全局态势感知' },
    'AlertCenter': { title: '告警监控', subtitle: '一体化告警监控与处置中心' },
    'LogAnalysis': { title: '日志分析', subtitle: '事件日志分析与检索' },
    'CaseList': { title: '案件管理', subtitle: '应急响应案件总览与调度' },
    'CaseDetail': { title: '案件详情', subtitle: '' },
    'HostDetail': { title: '主机详情', subtitle: '' },
    'Report': { title: '分析报告', subtitle: '应急响应分析报告输出' },
    'Rules': { title: '规则管理', subtitle: '配置检测规则与响应策略' },
    'Whitelist': { title: '白名单配置', subtitle: '管理信任名单与豁免规则' },
    'Iocs': { title: 'IOC 指标管理', subtitle: '威胁情报指标库维护' },
    'AiConfig': { title: 'AI 分析', subtitle: '智能辅助分析与研判' },
    'ThreatIntelConfig': { title: '威胁情报外联配置', subtitle: '外部情报源接入管理' },
    'Knowledge': { title: '知识库管理', subtitle: '安全知识沉淀与检索' },
    'PolicyConfig': { title: '策略配置', subtitle: '检测策略管理与规则选择' },
  }
  return names[route.name] || { title: '应急响应平台', subtitle: '' }
})

// ===== 导航跳转 =====
function navigate(child) {
  if (child.path === '/hosts/:id') {
    // 主机详情需要跳转到最近的案件主机
    router.push('/cases')
    return
  }
  if (child.path === '/hosts/:id/report') {
    router.push('/cases')
    return
  }
  router.push(child.path)
}

function openFirstChild(group) {
  // 点击一级菜单默认打开第一个二级页面
  if (group.children.length > 0) {
    // hover 处理下拉展开，不需要额外 action
  }
}

function handleCommand(command) {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--color-canvas-subtle);
}

/* ===== 横向顶栏 ===== */
.top-nav {
  height: 52px;
  min-height: 52px;
  background: var(--color-canvas-default);
  border-bottom: 1px solid var(--color-border-default);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 0;
  z-index: 200;
}

.nav-left {
  display: flex;
  align-items: center;
  flex: 1;
  gap: 0;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-fg-default);
  margin-right: 24px;
  flex-shrink: 0;
}

/* ===== 一级导航标签 ===== */
.nav-tabs {
  display: inline-flex;
  position: relative;
  height: 52px;
}
.nav-tab {
  position: relative;
  height: 52px;
  padding: 0 20px;
  font-size: 14px;
  color: var(--color-fg-muted);
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
  transition: color 0.15s, background 0.15s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.nav-tab:hover {
  color: var(--color-accent-fg);
  background: var(--color-canvas-subtle);
}

.nav-tab.active {
  color: var(--color-accent-fg);
  font-weight: 600;
}

.nav-tab.active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 8px;
  right: 8px;
  height: 2px;
  background: var(--color-success-emphasis, #059669);
  border-radius: 2px;
}

.nav-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  background: var(--color-danger-subtle, #fee2e2);
  color: var(--color-danger-fg, #dc2626);
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  margin-left: 2px;
}

/* ===== 下拉面板 ===== */
.nav-dropdown {
  display: none;
  position: absolute;
  top: 100%;
  left: 0;
  min-width: 160px;
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.08);
  padding: 6px 0;
  z-index: 300;
}

.nav-tab:hover .nav-dropdown {
  display: block;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 12px;
  color: var(--color-fg-muted);
  cursor: pointer;
  transition: background 0.1s;
}

.nav-item:hover {
  background: var(--color-canvas-subtle);
  color: var(--color-accent-fg);
}

.nav-item.active {
  color: var(--color-accent-fg);
  font-weight: 600;
  background: var(--color-accent-subtle, #ecfdf5);
}

.nav-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--color-border-default);
  flex-shrink: 0;
}

.nav-item.active .nav-dot {
  background: var(--color-accent-fg);
}

.nav-item-badge {
  margin-left: auto;
  background: var(--color-danger-subtle, #fee2e2);
  color: var(--color-danger-fg, #dc2626);
  font-size: 10px;
  padding: 0 6px;
  border-radius: 8px;
  font-weight: 700;
}

/* ===== 右侧用户 ===== */
.nav-btn {
  color: var(--color-fg-muted);
  padding: 6px;
  border-radius: 6px;
}

.nav-btn:hover {
  background: var(--color-canvas-subtle);
  color: var(--color-fg-default);
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  color: var(--color-fg-muted);
  font-size: 13px;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.15s;
}

.user-trigger:hover {
  background: var(--color-canvas-subtle);
}

.user-name {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-arrow {
  font-size: 12px;
}

/* ===== 主内容 ===== */
.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px 8px;
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
}
@media (max-width: 767px) {
  .main-content { padding: 16px 8px; }
}
</style>
