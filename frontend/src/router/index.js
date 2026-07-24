import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AgentRunView from '@/views/AgentRunView.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue')
      },
      {
        path: 'cases',
        name: 'CaseList',
        component: () => import('@/views/CaseListView.vue')
      },
      {
        path: 'cases/:id',
        name: 'CaseDetail',
        component: () => import('@/views/CaseDetailView.vue')
      },
      {
        path: 'hosts/:id',
        name: 'HostDetail',
        component: () => import('@/views/HostDetailView.vue')
      },
      {
        path: 'hosts/:id/report',
        name: 'Report',
        component: () => import('@/views/ReportView.vue')
      },
      {
        path: 'rules',
        name: 'Rules',
        component: () => import('@/views/RulesView.vue')
      },
      {
        path: 'rule-drafts',
        name: 'RuleDrafts',
        component: () => import('@/views/RuleDraftView.vue')
      },
      {
        path: 'whitelist',
        name: 'Whitelist',
        component: () => import('@/views/WhitelistView.vue')
      },
      {
        path: 'iocs',
        name: 'Iocs',
        component: () => import('@/views/IocsView.vue')
      },
      {
        path: 'ai',
        name: 'AiConfig',
        component: () => import('@/views/AiView.vue')
      },
      {
        path: 'threat-intel-config',
        name: 'ThreatIntelConfig',
        component: () => import('@/views/ThreatIntelConfigView.vue')
      },
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: () => import('@/views/KnowledgeView.vue')
      },
      {
        path: 'knowledge/detail/:entryRef',
        name: 'KnowledgeDetail',
        component: () => import('@/views/KnowledgeDetailView.vue')
      },
      {
        path: 'alerts',
        name: 'AlertCenter',
        component: () => import('@/views/UnifiedAlertCenter.vue')
      },
      {
        path: 'logs',
        name: 'LogAnalysis',
        component: () => import('@/views/LogAnalysisView.vue')
      },
      {
        path: 'policies',
        name: 'PolicyConfig',
        component: () => import('@/views/PolicyConfigView.vue')
      },
      {
        path: 'reports',
        name: 'Reports',
        component: () => import('@/views/ReportOutputView.vue')
      },
      {
        path: 'ai-advanced',
        name: 'AiAdvanced',
        component: () => import('@/views/AiAdvancedView.vue')
      },
      {
        path: 'analysis-center',
        name: 'AnalysisCenter',
        component: () => import('@/views/AnalysisCenterView.vue')
      },
      {
        path: 'analysis-center/event/:id',
        name: 'EventDetail',
        component: () => import('@/views/EventDetailView.vue')
      },
      {
        path: 'log-search',
        name: 'LogSearch',
        component: () => import('@/views/LogSearchView.vue')
      },
      {
        path: 'incident-clusters',
        name: 'IncidentClusters',
        component: () => import('@/views/IncidentClusterView.vue')
      },
      {
        path: 'root-cause',
        name: 'RootCause',
        component: () => import('@/views/RootCauseView.vue')
      },
      {
        path: 'kb-feedback',
        name: 'KbFeedback',
        component: () => import('@/views/KbFeedbackView.vue')
      },
      {
        path: 'agent-management',
        name: 'AgentManagementV2',
        // 兼容别名：重定向到智能体编排管理下的智能体模块（M2）
        redirect: '/agent-orchestration/agents',
        meta: { title: '智能体管理' }
      },

      // ───────────────────────────────────────────────────────────
      // 智能体编排管理（9 模块父路由，承载子导航布局）
      // 现有 AgentRunView / AgentRunDetailView 重映射为 runs / runs/:runId
      // ───────────────────────────────────────────────────────────
      {
        path: 'agent-orchestration',
        component: () => import('@/views/agent-orchestration/AgentOrchestrationLayout.vue'),
        redirect: '/agent-orchestration/dashboard',
        children: [
          {
            path: '',
            redirect: { name: 'AoDashboard' },
          },
          {
            path: 'dashboard',
            name: 'AoDashboard',
            component: () => import('@/views/agent-orchestration/DashboardView.vue'),
            meta: { title: '编排总览' }
          },
          {
            path: 'agents',
            name: 'AoAgents',
            component: () => import('@/views/agent-orchestration/AgentsView.vue'),
            meta: { title: '智能体管理' }
          },
          {
            path: 'pipeline',
            name: 'AoPipeline',
            component: () => import('@/views/agent-orchestration/PipelineCanvasView.vue'),
            meta: { title: '流水线 DAG' }
          },
          {
            path: 'tools',
            name: 'AoTools',
            component: () => import('@/views/agent-orchestration/ToolMcpView.vue'),
            meta: { title: '工具与 MCP' }
          },
          {
            path: 'memory',
            name: 'AoMemory',
            component: () => import('@/views/agent-orchestration/MemoryRagView.vue'),
            meta: { title: '记忆与 RAG' }
          },
          {
            path: 'hitl',
            name: 'AoHitl',
            component: () => import('@/views/agent-orchestration/HitlConsoleView.vue'),
            meta: { title: '人工审核台' }
          },
          {
            path: 'guardrail',
            name: 'AoGuardrail',
            component: () => import('@/views/agent-orchestration/GuardrailView.vue'),
            meta: { title: '护栏与安全' }
          },
          {
            path: 'runs',
            name: 'AoRuns',
            component: AgentRunView,
            meta: { title: '编排运行记录' }
          },
          {
            path: 'runs/:runId',
            name: 'AoRunDetail',
            component: () => import('@/views/AgentRunDetailView.vue'),
            meta: { title: '运行详情' }
          },
          {
            path: 'settings',
            name: 'AoSettings',
            component: () => import('@/views/agent-orchestration/SettingsView.vue'),
            meta: { title: '编排设置' }
          },
        ]
      },

      {
        path: 'settings',
        component: () => import('@/views/settings/SettingsLayout.vue'),
        children: [
          {
            path: 'users',
            name: 'UserManagement',
            component: () => import('@/views/settings/UserManagement.vue')
          },
          {
            path: 'audit-logs',
            name: 'AuditLogs',
            component: () => import('@/views/settings/AuditLogView.vue')
          },
          {
            path: 'agents',
            name: 'AgentManagement',
            component: () => import('@/views/settings/AgentManagement.vue')
          },
          {
            path: 'storage',
            name: 'DataStorage',
            component: () => import('@/views/settings/DataStorageView.vue')
          },
          {
            path: 'params',
            name: 'SystemParams',
            component: () => import('@/views/settings/SystemParamsView.vue')
          },
          {
            path: 'theme',
            name: 'ThemeCustomize',
            component: () => import('@/views/settings/ThemeCustomizeView.vue'),
          },
        ]
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth !== false && !authStore.token) {
    next('/login')
  } else if (to.path === '/login' && authStore.token) {
    next('/')
  } else {
    next()
  }
})

export default router
