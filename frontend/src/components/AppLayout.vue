<template>
  <el-container class="app-layout">
    <!-- ========== 移动端遮罩层 ========== -->
    <div
      v-if="isMobile && mobileOpen"
      class="mobile-overlay"
      @click="closeMobileMenu"
    />

    <!-- ========== 侧边栏 ========== -->
    <el-aside
      :width="!isMobile ? asideWidth + 'px' : '210px'"
      class="app-aside"
      :class="{
        collapsed: !isMobile && collapsed,
        'mobile-open': isMobile && mobileOpen
      }"
    >
      <!-- Logo 区 -->
      <div class="logo">
        <el-icon :size="22"><Lock /></el-icon>
        <span class="logo-text" :class="{ 'logo-text--hidden': !isMobile && collapsed }">
          应急响应平台
        </span>
      </div>

      <!-- 导航菜单 — 使用 el-menu 原生 collapse，不切换 DOM 结构（避免销毁/重建开销） -->
      <el-menu
        :default-active="activeMenu"
        :collapse="!isMobile && collapsed"
        router
        class="app-menu"
      >
        <template v-for="item in navItems" :key="item.index">
          <!-- tooltip 在展开时 disabled，折叠时启用；DOM 不销毁，只切换 disabled 状态 -->
          <el-tooltip
            :content="item.label"
            placement="right"
            effect="dark"
            :show-after="300"
            :disabled="!(!isMobile && collapsed)"
          >
            <el-menu-item :index="item.index" @click="closeMobileMenu">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </el-menu-item>
          </el-tooltip>
        </template>
      </el-menu>

      <!-- 底部折叠按钮（桌面端） -->
      <div v-if="!isMobile" class="sidebar-collapse-btn" @click="collapsed = !collapsed">
        <el-icon :size="16">
          <component :is="collapsed ? DArrowRight : DArrowLeft" />
        </el-icon>
        <span v-show="!collapsed" class="collapse-label">折叠</span>
      </div>
    </el-aside>

    <!-- ========== 主内容区 ========== -->
    <el-container>
      <el-header class="app-header">
        <div class="header-left">
          <!-- 移动端汉堡菜单 -->
          <el-button
            v-if="isMobile"
            class="hamburger-btn"
            text
            @click="toggleMobileMenu"
          >
            <el-icon :size="20"><component :is="mobileOpen ? Close : Expand" /></el-icon>
          </el-button>
          <!-- 桌面端折叠切换 -->
          <el-button
            v-if="!isMobile"
            class="collapse-toggle-btn"
            text
            @click="collapsed = !collapsed"
          >
            <el-icon :size="20"><Fold /></el-icon>
          </el-button>
          <!-- 面包屑区 -->
          <div class="breadcrumb-area">
            <span class="page-breadcrumb">{{ currentRouteName }}</span>
            <span v-if="pageSubtitle" class="page-subtitle">{{ pageSubtitle }}</span>
          </div>
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
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import {
  Cpu, Lock, CircleCheck, Warning, Connection, Collection,
  Setting, Folder, Sunny, Moon, User, ArrowDown, Monitor,
  DArrowLeft, DArrowRight, Expand, Close, Fold
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()

// ==================== 状态 ====================
const collapsed = ref(false)
const mobileOpen = ref(false)
const isMobile = ref(window.innerWidth < 768)

// ==================== 导航项配置 ====================
const navItems = [
  { index: '/', label: '全局态势', icon: Monitor },
  { index: '/alerts', label: '告警监控', icon: Warning },
  { index: '/cases', label: '案件管理', icon: Folder },
  { index: '/ai', label: 'AI 分析', icon: Cpu },
  { index: '/rules', label: '规则管理', icon: Setting },
  { index: '/whitelist', label: '白名单配置', icon: CircleCheck },
  { index: '/iocs', label: 'IOC 指标', icon: Warning },
  { index: '/threat-intel-config', label: '威胁情报外联', icon: Connection },
  { index: '/knowledge', label: '知识库', icon: Collection }
]

// ==================== 计算属性 ====================
const asideWidth = computed(() => collapsed.value ? 64 : 210)

const activeMenu = computed(() => {
  if (route.path === '/') return '/'
  if (route.path === '/alerts') return '/alerts'
  if (route.path.startsWith('/cases') || route.path.startsWith('/hosts')) return '/cases'
  if (route.path === '/whitelist') return '/whitelist'
  if (route.path === '/iocs') return '/iocs'
  if (route.path === '/knowledge') return '/knowledge'
  if (route.path === '/threat-intel-config') return '/threat-intel-config'
  return route.path
})

const routeMeta = computed(() => {
  const names = {
    'Dashboard': { title: '全局态势', subtitle: '应急响应全局态势感知' },
    'AlertCenter': { title: '告警监控', subtitle: '一体化告警监控与处置中心' },
    'CaseList': { title: '案件管理', subtitle: '应急响应案件总览与调度' },
    'CaseDetail': { title: '案件详情', subtitle: '' },
    'HostDetail': { title: '主机详情', subtitle: '' },
    'Report': { title: '分析报告', subtitle: '' },
    'Rules': { title: '规则管理', subtitle: '配置检测规则与响应策略' },
    'Whitelist': { title: '白名单配置', subtitle: '管理信任名单与豁免规则' },
    'Iocs': { title: 'IOC 指标管理', subtitle: '威胁情报指标库维护' },
    'AiConfig': { title: 'AI 分析', subtitle: '智能辅助分析与研判' },
    'ThreatIntelConfig': { title: '威胁情报外联配置', subtitle: '外部情报源接入管理' },
    'Knowledge': { title: '知识库管理', subtitle: '安全知识沉淀与检索' }
  }
  return names[route.name] || { title: '应急响应平台', subtitle: '' }
})

const currentRouteName = computed(() => routeMeta.value.title)

const pageSubtitle = computed(() => routeMeta.value.subtitle)

// ==================== 方法 ====================
function toggleMobileMenu() {
  mobileOpen.value = !mobileOpen.value
}

function closeMobileMenu() {
  mobileOpen.value = false
}

function handleCommand(command) {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}

function handleResize() {
  // rAF 防抖：在一帧内只触发一次，避免频繁 resize 事件（如拖拽窗口时）导致多次重排
  if (_resizeRaf) return
  _resizeRaf = requestAnimationFrame(() => {
    _resizeRaf = null
    isMobile.value = window.innerWidth < 768
  })
}
let _resizeRaf = null

// 路由切换时自动关闭移动端侧边栏
watch(() => route.path, () => {
  if (isMobile.value) {
    mobileOpen.value = false
  }
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
/* ============================================================
 * 基础布局
 * ============================================================ */
.app-layout {
  height: 100%;
}

/* ============================================================
 * 侧边栏
 *
 * 性能优化：
 * - will-change: width   → 提前告示浏览器，提升为独立合成层（GPU 加速）
 * - contain: layout       → 隔离侧边栏的布局重排，避免传播到主内容区
 * - 使用 width 过渡而非 transform：el-container 的 flex 布局下 width 不可避免，
 *   但配合 will-change + contain 可大幅降低重排开销
 * - logo 区用 max-width 替代 width 过渡（避免文字回流的二次重排）
 * ============================================================ */
.app-aside {
  background: var(--color-sidebar-bg);
  overflow: hidden;
  transition: width 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  will-change: width;
  contain: layout style;
}

/* 折叠时宽度由 el-aside 的 :width 属性控制，
   .collapsed 类提供额外样式覆盖（防御） */
.app-aside.collapsed {
  width: 64px !important;
  min-width: 64px !important;
}

/* ---------- Logo 区 ---------- */
.logo {
  height: 60px;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-fg-on-emphasis);
  font-size: 16px;
  font-weight: bold;
  gap: 8px;
  border-bottom: 1px solid var(--color-sidebar-border);
  padding: 0 16px;
  white-space: nowrap;
}

.logo .el-icon {
  flex-shrink: 0;
}

.logo-text {
  overflow: hidden;
  white-space: nowrap;
  /* max-width 替代 width：避免文字回流时的二次重排，动画更平滑 */
  max-width: 200px;
  opacity: 1;
  transition: opacity 0.15s ease, max-width 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.logo-text--hidden {
  opacity: 0;
  max-width: 0;
}

/* ---------- 导航菜单 ---------- */
.app-menu {
  border: none;
  background: var(--color-sidebar-bg);
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.app-menu .el-menu-item {
  color: var(--color-sidebar-fg-muted);
  transition: background 0.15s ease, color 0.15s ease;
}

.app-menu .el-menu-item:hover {
  background: var(--color-sidebar-hover-bg);
}

.app-menu .el-menu-item.is-active {
  background: var(--color-sidebar-active-bg);
  color: var(--color-fg-on-emphasis);
}

/* 折叠时菜单项样式 — 确保文字完全隐藏，不截断溢出 */
.app-aside.collapsed .app-menu .el-menu-item {
  justify-content: center;
  padding: 0 !important;
}

/* 关键：el-menu collapse 模式下 <span> 文字必须完全隐藏，
   防止文字截断导致的视觉混乱（如"案件管""规则管"） */
.app-aside.collapsed .app-menu .el-menu-item span {
  display: none;
}

/* 展开时文字正常显示 */
.app-menu .el-menu-item span {
  display: inline;
}

/* ---------- 底部折叠按钮 ---------- */
.sidebar-collapse-btn {
  height: 48px;
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--color-sidebar-fg-muted);
  cursor: pointer;
  border-top: 1px solid var(--color-sidebar-border);
  transition: background 0.15s ease, color 0.15s ease;
  user-select: none;
  white-space: nowrap;
}

.sidebar-collapse-btn:hover {
  background: var(--color-sidebar-hover-bg);
  color: var(--color-sidebar-fg);
}

.collapse-label {
  font-size: 13px;
}

.app-aside.collapsed .sidebar-collapse-btn {
  justify-content: center;
}

/* ============================================================
 * 移动端 overlay 模式
 *
 * 性能优化：使用 transform: translateX 而非 left/width，
 * transform 只触发 composite，不触发 layout/paint
 * ============================================================ */
@media (max-width: 767px) {
  .app-aside {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 1000;
    transform: translateX(-100%);
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    will-change: transform;
    width: 210px !important;
    min-width: 210px !important;
  }

  .app-aside.mobile-open {
    transform: translateX(0);
    box-shadow: 4px 0 12px rgba(0, 0, 0, 0.25);
  }

  .mobile-overlay {
    position: fixed;
    inset: 0;
    z-index: 999;
    background: rgba(0, 0, 0, 0.5);
    animation: fadeIn 0.2s ease;
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }
}

/* ============================================================
 * 顶部 Header
 * ============================================================ */
.app-header {
  background: var(--color-canvas-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--color-border-default);
  height: 60px;
  padding: 0 20px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-right {
  display: flex;
  align-items: center;
}

/* ---------- 汉堡按钮 / 折叠按钮 ---------- */
.hamburger-btn,
.collapse-toggle-btn {
  color: var(--color-fg-muted);
  padding: 6px;
  border-radius: 6px;
  transition: background 0.15s ease;
}

.hamburger-btn:hover,
.collapse-toggle-btn:hover {
  background: var(--color-canvas-subtle);
  color: var(--color-fg-default);
}

/* ---------- 面包屑 ---------- */
.breadcrumb-area {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.page-breadcrumb {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-fg-default);
  line-height: 1.3;
}

.page-subtitle {
  font-size: 12px;
  color: var(--color-fg-muted);
  line-height: 1.3;
}

/* ---------- 主题切换 + 用户 ---------- */
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
  font-size: 14px;
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.15s ease;
}

.user-info:hover {
  background: var(--color-canvas-subtle);
}

.user-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-arrow {
  font-size: 12px;
  margin-left: 2px;
}

/* ============================================================
 * 主内容区
 * ============================================================ */
.app-main {
  background: var(--color-canvas-subtle);
  padding: 24px;
  overflow-y: auto;
}

@media (max-width: 767px) {
  .app-main {
    padding: 16px;
  }

  .app-header {
    padding: 0 12px;
  }
}
</style>
