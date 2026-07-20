<template>
  <div class="app-layout">
    <!-- ===== 横向导航栏 ===== -->
    <div class="top-nav" @mouseleave="hoverGroup = ''">
      <div class="nav-left">
        <div class="logo">
          <el-icon :size="20"><Lock /></el-icon>
          <span>应急平台</span>
        </div>

        <div
          v-for="group in navGroups"
          :key="group.label"
          :class="['nav-tab', { active: activeGroup === group.label }]"
          @mouseenter="hoverGroup = group.label"
          @mouseleave="hoverGroup = ''"
          @click="openFirstChild(group)"
        >
          <el-icon class="nav-tab-icon" :size="18">
            <component :is="group.icon" />
          </el-icon>
          <span class="nav-tab-text">{{ group.label }}</span>
          <span v-if="group.badge" class="nav-badge">{{ alertCount }}</span>

          <transition name="dropdown">
            <div class="nav-dropdown" v-if="hoverGroup === group.label">
              <div
                v-for="child in group.children"
                :key="child.path"
                :class="['nav-item', { active: route.path === child.path || (child.activeMatch && route.path.startsWith(child.activeMatch)) }]"
                @click.stop="navigate(child)"
              >
                <el-icon class="nav-item-icon" :size="14"><component :is="child.icon" /></el-icon>
                <span>{{ child.label }}</span>
                <span v-if="child.badge" class="nav-item-badge">{{ alertCount }}</span>
              </div>
            </div>
          </transition>
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
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import {
  Lock, Sunny, Moon, User, ArrowDown,
  DataAnalysis, Folder, Document, MagicStick, Setting, Tools,
  Monitor, Bell, FolderOpened, Cpu, Tickets,
  Aim, Search, Reading,
  Collection, List, CircleCheck, Notification, Connection,
  Avatar, Coin,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()

const hoverGroup = ref('')

// ===== 导航配置 =====
const alertCount = computed(() => 0) // 可从告警 store 获取

const navGroups = [
  {
    icon: DataAnalysis,
    label: '态势感知',
    path: '/',
    children: [
      { icon: Monitor, label: '全局态势', path: '/' },
      { icon: Bell, label: '告警监控', path: '/alerts', badge: true, activeMatch: '/alerts' },
      { icon: Document, label: '日志分析', path: '/logs', activeMatch: '/logs' },
    ],
  },
  {
    icon: Folder,
    label: '案件管理',
    path: '/cases',
    children: [
      { icon: FolderOpened, label: '案件列表', path: '/cases', activeMatch: '/cases' },
      { icon: Cpu, label: '主机详情', path: '/hosts/:id', activeMatch: '/hosts' },
    ],
  },
  {
    icon: Document,
    label: '报告输出',
    path: '/reports',
    activeMatch: '/reports',
    children: [
      { icon: Tickets, label: '报告列表', path: '/reports' },
    ],
  },
  {
    icon: MagicStick,
    label: '智能分析',
    path: '',
    children: [
      { icon: MagicStick, label: 'AI 分析', path: '/ai' },
      { icon: Aim, label: 'AI 实验室', path: '/ai-advanced', activeMatch: '/ai-advanced' },
      { icon: DataAnalysis, label: '分析中心', path: '/analysis-center', activeMatch: '/analysis-center' },
      { icon: Search, label: '日志检索', path: '/log-search', activeMatch: '/log-search' },
      { icon: Reading, label: '知识库', path: '/knowledge', activeMatch: '/knowledge' },
      { icon: Connection, label: '智能体编排', path: '/agent-orchestration', activeMatch: '/agent-orchestration' },
      { icon: Connection, label: '事件归并', path: '/incident-clusters', activeMatch: '/incident-clusters' },
      { icon: Aim, label: '根因分析', path: '/root-cause', activeMatch: '/root-cause' },
      { icon: Collection, label: '知识自进化', path: '/kb-feedback', activeMatch: '/kb-feedback' },
    ],
  },
  {
      icon: Setting,
      label: '检测配置',
      path: '',
      children: [
        { icon: Collection, label: '规则管理', path: '/rules' },
        { icon: MagicStick, label: '规则草稿', path: '/rule-drafts', activeMatch: '/rule-drafts' },
        { icon: List, label: '策略配置', path: '/policies' },
        { icon: CircleCheck, label: '白名单', path: '/whitelist' },
        { icon: Notification, label: 'IOC 指标', path: '/iocs' },
        { icon: Connection, label: '威胁情报', path: '/threat-intel-config' },
      ],
    },
  {
    icon: Tools,
    label: '系统设置',
    path: '/settings',
    children: [
      { icon: User, label: '用户与权限', path: '/settings/users' },
      { icon: Tickets, label: '审计日志', path: '/settings/audit-logs' },
      { icon: Avatar, label: 'Agent 管理', path: '/settings/agents' },
      { icon: Coin, label: '数据与存储', path: '/settings/storage' },
      { icon: Tools, label: '系统参数', path: '/settings/params' },
      { icon: MagicStick, label: '主题与外观', path: '/settings/theme' },
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
    'LogSearch': { title: '日志检索', subtitle: 'Agent 原始数据全文检索与分析' },
    'CaseList': { title: '案件管理', subtitle: '应急响应案件总览与调度' },
    'CaseDetail': { title: '案件详情', subtitle: '' },
    'HostDetail': { title: '主机详情', subtitle: '' },
    'Report': { title: '分析报告', subtitle: '应急响应分析报告输出' },
    'Rules': { title: '规则管理', subtitle: '配置检测规则与响应策略' },
    'RuleDrafts': { title: '规则草稿', subtitle: 'AI 自生成检测规则 · 影子运行与人审启用' },
    'Whitelist': { title: '白名单配置', subtitle: '管理信任名单与豁免规则' },
    'Iocs': { title: 'IOC 指标管理', subtitle: '威胁情报指标库维护' },
    'AiConfig': { title: 'AI 分析', subtitle: '智能辅助分析与研判' },
    'ThreatIntelConfig': { title: '威胁情报外联配置', subtitle: '外部情报源接入管理' },
    'Knowledge': { title: '知识库管理', subtitle: '安全知识沉淀与检索' },
    'PolicyConfig': { title: '策略配置', subtitle: '检测策略管理与规则选择' },
    'AiAdvanced': { title: 'AI 实验室', subtitle: '高级关联功能 · 智能辅助分析与研判' },
    'AnalysisCenter': { title: '分析中心', subtitle: '一站式事件调查工作台 · 攻击链可视化' },
    'AgentOrchestration': { title: '智能体编排', subtitle: '多智能体协同处置闭环 · 人在回路审批' },
    'IncidentClusters': { title: '事件归并', subtitle: '语义级跨资产告警降噪 2.0 · 可疑事件归并簇' },
    'RootCause': { title: '根因分析', subtitle: '进程树回溯根因归因 · 因果链可视化' },
    'KbFeedback': { title: '知识自进化', subtitle: '误报 → 抑制 → 沉淀 · 知识库自进化闭环' },
    'UserManagement': { title: '用户与权限', subtitle: '平台用户管理与权限分配' },
    'AuditLogs': { title: '审计日志', subtitle: '平台操作审计与追踪' },
    'AgentManagement': { title: 'Agent 管理', subtitle: 'Agent 客户端管理与监控' },
    'DataStorage': { title: '数据与存储', subtitle: '数据存储与清理管理' },
    'SystemParams': { title: '系统参数', subtitle: '平台系统参数配置' },
    'ThemeCustomize': { title: '主题与外观', subtitle: '自定义平台主题与外观颜色' },
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
  height: 56px;
  min-height: 56px;
  padding: 0 24px;
  background: var(--color-canvas-default);
  border-bottom: 1px solid var(--color-border-default);
  display: flex;
  align-items: center;
  gap: 0;
  z-index: 200;
}

.nav-left {
  display: flex;
  align-items: center;
  flex: 1;
  gap: 0;
  position: relative;
}

/* logo 与导航之间的细分隔线 */
.nav-left::after {
  content: '';
  position: absolute;
  left: 168px;
  top: 12px;
  bottom: 12px;
  width: 1px;
  background: var(--color-border-default);
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
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--color-fg-default);
  margin-right: 32px;
  flex-shrink: 0;
}

/* ===== 一级导航标签 ===== */
.nav-tab {
  position: relative;
  height: 56px;
  padding: 0 18px;
  font-size: 14px;
  font-weight: 400;
  color: var(--color-fg-muted);
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 7px;
  transition: color 0.15s ease, background 0.15s ease;
}

.nav-tab:hover {
  color: var(--color-fg-default);
  background: var(--color-canvas-subtle);
}

.nav-tab.active {
  color: var(--color-accent-fg);
  background: var(--color-accent-subtle, rgba(99, 153, 34, 0.06));
}

/* 激活下划线：只显示中间短段 */
.nav-tab.active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 18px;
  right: 18px;
  height: 2px;
  background: var(--color-accent-fg);
  border-radius: 2px 2px 0 0;
  opacity: 0.9;
}

.nav-tab-icon {
  color: var(--color-fg-muted);
  flex-shrink: 0;
}

.nav-tab:hover .nav-tab-icon,
.nav-tab.active .nav-tab-icon {
  color: var(--color-accent-fg);
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
  position: absolute;
  top: calc(100% + 4px);
  left: 12px;
  min-width: 180px;
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
  padding: 6px;
  z-index: 300;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--color-fg-default);
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  transition: background 0.12s ease;
}

.nav-item:hover {
  background: var(--color-canvas-subtle);
}

.nav-item.active {
  color: var(--color-accent-fg);
  background: var(--color-accent-subtle, rgba(99, 153, 34, 0.06));
  font-weight: 500;
}

/* 激活项左侧 3px 圆角色条（替代 nav-dot） */
.nav-item.active::before {
  content: '';
  position: absolute;
  left: -6px;
  top: 8px;
  bottom: 8px;
  width: 3px;
  background: var(--color-accent-fg);
  border-radius: 2px;
}

.nav-item-icon {
  color: var(--color-fg-muted);
  flex-shrink: 0;
}

.nav-item.active .nav-item-icon,
.nav-item:hover .nav-item-icon {
  color: var(--color-accent-fg);
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

/* ===== 下拉过渡 ===== */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-6px);
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
  padding: 0;
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
}
@media (max-width: 767px) {
  .main-content { padding: 16px 8px; }
}
</style>
