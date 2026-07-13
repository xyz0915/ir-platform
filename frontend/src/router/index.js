import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

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
