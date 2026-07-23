import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AgentRunDetailView from '@/views/AgentRunDetailView.vue'
import AgentManagementView from '@/views/AgentManagementView.vue'

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
        path: 'agent-orchestration',
        name: 'AgentOrchestration',
        component: () => import('@/views/AgentRunView.vue')
      },
      {
        path: 'agent-orchestration/:runId',
        name: 'AgentRunDetail',
        component: AgentRunDetailView,
        meta: { title: '编排运行详情' }
      },
      {
        path: 'agent-management',
        name: 'AgentManagementV2',
        component: AgentManagementView,
        meta: { title: '智能体管理' }
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
      // 系统设置路由
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
