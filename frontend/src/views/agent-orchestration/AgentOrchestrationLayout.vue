<template>
  <div class="ao-layout">
    <!-- 左侧 9 模块子导航 -->
    <aside class="ao-sidebar">
      <div class="ao-sb-title">智能体编排</div>
      <nav class="ao-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="ao-nav-item"
          :class="{ active: isActive(item) }"
        >
          <el-icon :size="16"><component :is="item.icon" /></el-icon>
          <span class="ao-nav-label">{{ item.label }}</span>
          <span v-if="item.badge" class="ao-nav-badge">{{ pendingBadge }}</span>
        </router-link>
      </nav>
    </aside>

    <!-- 右侧内容区 -->
    <section class="ao-content">
      <div class="ao-content-head">
        <div class="ao-ch-title">{{ currentTitle }}</div>
        <div class="ao-ch-actions">
          <el-button text size="small" @click="toggleTheme" class="ao-theme-btn">
            <el-icon :size="16"><component :is="themeMode === 'dark' ? Sunny : Moon" /></el-icon>
            {{ themeMode === 'dark' ? '暗色' : '亮色' }}
          </el-button>
        </div>
      </div>
      <div class="ao-view">
        <router-view />
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAgentOrchestrationStore } from '@/stores/agents'
import { useAgentTheme } from '@/composables/useAgentTheme'
import {
  DataAnalysis, Cpu, Share, Tools, Collection, Stamp, Lock, List, Setting, Sunny, Moon,
} from '@element-plus/icons-vue'

const route = useRoute()
const authStore = useAuthStore()
const store = useAgentOrchestrationStore()
const { mode: themeMode, toggleMode } = useAgentTheme()

const isAdmin = computed(() => authStore.user?.role === 'admin')
const pendingBadge = computed(() => store.pendingCount)

const navItems = [
  { path: '/agent-orchestration/dashboard', label: '总览', icon: DataAnalysis },
  { path: '/agent-orchestration/agents', label: '智能体', icon: Cpu },
  { path: '/agent-orchestration/pipeline', label: '流水线', icon: Share },
  { path: '/agent-orchestration/tools', label: '工具与 MCP', icon: Tools },
  { path: '/agent-orchestration/memory', label: '记忆与 RAG', icon: Collection },
  { path: '/agent-orchestration/hitl', label: '人工审核', icon: Stamp, badge: true },
  { path: '/agent-orchestration/guardrail', label: '护栏', icon: Lock },
  { path: '/agent-orchestration/runs', label: '运行', icon: List },
  { path: '/agent-orchestration/settings', label: '设置', icon: Setting },
]

const titles = {
  '/agent-orchestration/dashboard': '编排总览',
  '/agent-orchestration/agents': '智能体管理',
  '/agent-orchestration/pipeline': '流水线 DAG 画布',
  '/agent-orchestration/tools': '工具与 MCP',
  '/agent-orchestration/memory': '记忆与 RAG',
  '/agent-orchestration/hitl': '人工审核台',
  '/agent-orchestration/guardrail': '护栏与安全',
  '/agent-orchestration/runs': '编排运行记录',
  '/agent-orchestration/settings': '编排设置',
}

const currentTitle = computed(() => {
  const base = titles[route.path]
  if (base) return base
  if (route.path.startsWith('/agent-orchestration/runs/')) return '运行详情'
  return '智能体编排管理'
})

function isActive(item) {
  if (item.path === '/agent-orchestration/runs') {
    return route.path === item.path || route.path.startsWith('/agent-orchestration/runs/')
  }
  return route.path === item.path
}

onMounted(() => {
  if (isAdmin.value) store.fetchApprovals()
})
</script>

<style scoped>
.ao-layout {
  display: flex;
  height: 100%;
  gap: 16px;
}
.ao-sidebar {
  flex: 0 0 180px;
  background: var(--color-canvas-default);
  border: 1px solid var(--color-border-default);
  border-radius: 12px;
  padding: 12px 10px;
  align-self: flex-start;
  position: sticky;
  top: 16px;
}
.ao-sb-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-fg-subtle);
  padding: 4px 8px 10px;
  letter-spacing: 0.5px;
}
.ao-nav { display: flex; flex-direction: column; gap: 2px; }
.ao-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-fg-muted);
  text-decoration: none;
  transition: all 0.15s;
  position: relative;
}
.ao-nav-item:hover { background: var(--color-canvas-subtle); color: var(--color-fg-default); }
.ao-nav-item.active {
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
  font-weight: 500;
}
.ao-nav-label { flex: 1; }
.ao-nav-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  background: var(--color-danger-subtle, #fee2e2);
  color: var(--color-danger-fg, #dc2626);
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.ao-content { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.ao-content-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.ao-ch-title { font-size: 18px; font-weight: 600; color: var(--color-fg-default); }
.ao-theme-btn { color: var(--color-fg-muted); }
.ao-view { flex: 1; min-width: 0; }
</style>
