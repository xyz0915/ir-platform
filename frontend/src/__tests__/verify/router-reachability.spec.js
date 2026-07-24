/**
 * 验证阶段 · 路由可达性测试（端到端验收 §2）
 *
 * 用 vitest 导入生产 router，对智能体编排 9 模块路由（含增强的 runs / runs/:runId）
 * 做两层断言：
 *   1) router.resolve(path) 命中 —— 路由已在 router/index.js 注册；
 *   2) router.push(path) 实际导航且组件经动态 import 解析成功 —— 组件可解析、不报错。
 *
 * 注：router 内置 beforeEach 鉴权重定向（无 token → /login），本测试在 setActivePinia
 * 后预置 authStore.token，使导航落到目标路由，从而真正验证「组件可解析」。
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

// 9 模块路由 + 增强的 runs / runs/:runId
const ROUTE_TARGETS = [
  { path: '/agent-orchestration/dashboard', name: 'AoDashboard' },
  { path: '/agent-orchestration/agents', name: 'AoAgents' },
  { path: '/agent-orchestration/pipeline', name: 'AoPipeline' },
  { path: '/agent-orchestration/tools', name: 'AoTools' },
  { path: '/agent-orchestration/memory', name: 'AoMemory' },
  { path: '/agent-orchestration/hitl', name: 'AoHitl' },
  { path: '/agent-orchestration/guardrail', name: 'AoGuardrail' },
  { path: '/agent-orchestration/runs', name: 'AoRuns' },
  { path: '/agent-orchestration/runs/RUN-VERIFY-001', name: 'AoRunDetail' },
  { path: '/agent-orchestration/settings', name: 'AoSettings' },
]

beforeAll(() => {
  setActivePinia(createPinia())
  // 预置 token 绕过鉴权重定向，确保导航落到目标模块
  useAuthStore().token = 'verify-fake-token'
})

describe('智能体编排 9 模块路由可达性', () => {
  it('全部模块路由已在 router 中注册（resolve 命中）', () => {
    for (const t of ROUTE_TARGETS) {
      const resolved = router.resolve(t.path)
      expect(resolved.matched.length, `路由未注册: ${t.path}`).toBeGreaterThanOrEqual(1)
      expect(resolved.name, `路由名不匹配: ${t.path}`).toBe(t.name)
    }
  })

  it('全部模块路由可导航且组件经动态 import 解析成功（无抛错）', async () => {
    for (const t of ROUTE_TARGETS) {
      // push 会触发 lazy component 的动态 import；若组件代码有问题会 reject
      await router.push(t.path)
      await router.isReady()
      await nextTick()
      const cur = router.currentRoute.value
      // 动态路由 runs/:runId 仅断言前缀，其余断言全等
      if (t.path.includes(':runId')) {
        expect(cur.path.startsWith('/agent-orchestration/runs/'), `导航失败: ${t.path}`).toBe(true)
      } else {
        expect(cur.fullPath, `导航失败: ${t.path}`).toBe(t.path)
      }
      expect(cur.name, `导航后路由名不匹配: ${t.path}`).toBe(t.name)
    }
  })

  it('组件定义均可静态解析（import 不抛错）', async () => {
    const viewImports = [
      () => import('@/views/agent-orchestration/DashboardView.vue'),
      () => import('@/views/agent-orchestration/AgentsView.vue'),
      () => import('@/views/agent-orchestration/PipelineCanvasView.vue'),
      () => import('@/views/agent-orchestration/ToolMcpView.vue'),
      () => import('@/views/agent-orchestration/MemoryRagView.vue'),
      () => import('@/views/agent-orchestration/HitlConsoleView.vue'),
      () => import('@/views/agent-orchestration/GuardrailView.vue'),
      () => import('@/views/agent-orchestration/SettingsView.vue'),
      () => import('@/views/AgentRunView.vue'),
      () => import('@/views/AgentRunDetailView.vue'),
      () => import('@/views/agent-orchestration/AgentOrchestrationLayout.vue'),
    ]
    for (const imp of viewImports) {
      const mod = await imp()
      expect(mod.default, '视图组件默认导出缺失').toBeTruthy()
    }
  })
})
