/**
 * 验证阶段 · 视图挂载冒烟（端到端验收 §2）
 *
 * 用 vitest + happy-dom + @vue/test-utils 对每个集成视图做 mount 冒烟：
 *   - mock 掉 agentApi 适配层（@/api/agent）与 M2/M6/M8 直连的真实接口模块；
 *   - mock echarts（happy-dom 无 canvas）；
 *   - 补齐 ResizeObserver / matchMedia / IntersectionObserver（element-plus 依赖）；
 *   - 预置 auth token + admin 角色，使 HITL 视图进入队列渲染分支。
 * 断言：挂载不抛错，且关键元素（标题 / 表格 / 画布容器）存在。
 */
import { describe, it, expect, beforeAll, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

// ── 统一信封 ──
const ok = (data) => Promise.resolve({ code: 0, data, message: 'ok' })

// ── Mock：agentApi 适配层 ──
vi.mock('@/api/agent', () => ({
  default: {
    runs: {
      listAgentRuns: () => ok({ items: [], total: 0 }),
      getAgentRun: () => ok({ run: { status: 'completed' }, steps: [] }),
    },
    stats: { getAgentStats: () => ok({ running: 0, success_rate: 0, pending_hitl: 0, guardrail_blocks: 0 }) },
    dashboard: { getTrend: () => ok([]), getGuardrailBlocks: () => ok(0) },
    hitl: { listPendingApprovals: () => ok({ items: [] }) },
    guardrail: {
      listPolicies: () => ok([]),
      listHits: () => ok([]),
      createPolicy: () => ok({}),
      updatePolicy: () => ok({}),
      deletePolicy: () => ok(null),
      evaluate: () => ok({ passed: true }),
    },
    tools: { listTools: () => ok([]), listMcpServers: () => ok([]) },
    memory: {
      listKnowledgeBases: () => ok([]),
      // P2 长期记忆（MemoryRagView onMounted 会调 fetchMemories）
      listMemories: () => ok({ items: [], total: 0, page: 1, page_size: 10 }),
      searchMemories: () => ok({ items: [], total: 0 }),
      createMemory: () => ok({ id: 1, created_at: '' }),
      deleteMemory: () => ok({ deleted: true }),
    },
    settings: {
      listModelProfiles: () => ok([]),
      getDeploymentConfig: () => ok({ stateless_enabled: true, redis_connected: true, sse_protocol: 'step_*', hitl_protocol: 'hitl_approval + resume' }),
    },
    observability: { getRun: () => ok({ trace: [], logs: [] }) },
    pipeline: {
      getSample: () => ok({ nodes: [], edges: [] }),
      run: () => ok({ run_id: 'r1' }),
      validate: () => ok({ valid: true, warnings: [] }),
      getRunStatus: () => ok({}),
      cancel: () => ok({}),
      resume: () => ok({}),
      getSSEUrl: () => ok(''),
      getPresets: () => ok([]),
    },
  },
  useGuardrail: () => ({ evaluate: () => ok({ passed: true }) }),
}))

// ── Mock：M2 直连真实接口模块 ──
vi.mock('@/api/agentManagement', () => ({
  listAgents: () => ok([]),
  createAgent: () => ok({}),
  updateAgent: () => ok({}),
  deleteAgent: () => ok(null),
  validatePipeline: () => ok({ valid: true, warnings: [] }),
  runPipeline: () => ok({ run_id: 'r1' }),
  getRunStatus: () => ok({}),
  cancelRun: () => ok({}),
  resumeRun: () => ok({}),
  getPipelineSSEUrl: () => ok(''),
  listPresets: () => ok([]),
  createPreset: () => ok({}),
  deletePreset: () => ok(null),
  getDependencyGraph: () => ok({}),
  getCacheStats: () => ok({}),
  invalidateCache: () => ok(null),
}))

// ── Mock：M6 / M8 直连真实接口模块 ──
vi.mock('@/api/agentOrchestration', () => ({
  createAgentRun: () => ok({ run_id: 'r1' }),
  listAgentRuns: () => ok({ items: [], total: 0 }),
  getAgentRun: () => ok({ run: { status: 'completed' }, steps: [] }),
  approveAgentRun: () => ok({}),
  rejectAgentRun: () => ok({}),
  listPendingApprovals: () => ok({ items: [] }),
  getSSEUrl: () => ok(''),
}))

// ── Mock：echarts（happy-dom 无 canvas） ──
vi.mock('echarts', () => ({
  init: () => ({ setOption() {}, resize() {}, dispose() {} }),
  graphic: { LinearGradient: class {} },
}))

// ── happy-dom 缺省 API polyfill ──
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  if (!window.matchMedia) {
    window.matchMedia = () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    })
  }
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.token = 'verify-fake-token'
  auth.user = { role: 'admin', name: 'verifier' }
})

// 每个视图：组件 + 期望出现的关键文本
const VIEWS = [
  // 注：in-view 标题已随去 AI 感改造移除（布局头部为唯一标题源），断言改为仍在页面内的稳定文本
  { name: 'M1 DashboardView', loader: () => import('@/views/agent-orchestration/DashboardView.vue'), expect: '近期运行' },
  { name: 'M2 AgentsView', loader: () => import('@/views/agent-orchestration/AgentsView.vue'), expect: '智能体' },
  { name: 'M3 PipelineRedesignView', loader: () => import('@/views/agent-orchestration/PipelineRedesignView.vue'), expect: '工作流编排' },
  { name: 'M4 ToolMcpView', loader: () => import('@/views/agent-orchestration/ToolMcpView.vue'), expect: '工具清单' },
  { name: 'M5 MemoryRagView', loader: () => import('@/views/agent-orchestration/MemoryRagView.vue'), expect: '长期记忆' },
  { name: 'M6 HitlConsoleView', loader: () => import('@/views/agent-orchestration/HitlConsoleView.vue'), expect: '待审批处置队列' },
  { name: 'M7 GuardrailView', loader: () => import('@/views/agent-orchestration/GuardrailView.vue'), expect: '护栏策略' },
  { name: 'M9 SettingsView', loader: () => import('@/views/agent-orchestration/SettingsView.vue'), expect: '多模型 Profile' },
]

describe('智能体编排集成视图挂载冒烟', () => {
  it.each(VIEWS.map((v) => [v.name, v.loader, v.expect]))(
    '%s 可挂载且不抛错、关键元素存在',
    async (name, loader, expectText) => {
      const mod = await loader()
      const View = mod.default
      const wrapper = mount(View, {
        global: {
          // 注册 ElementPlus 以贴近生产全局组件注册；表格类组件仍按 happy-dom 约定做桩
          plugins: [router, ElementPlus],
          // happy-dom 下 element-plus 的 el-table 列插槽作用域为 undefined，
          // 与本项目既有组件测试约定一致（stub el-* 元素），对重型表格/弹窗组件做桩，
          // 仅验证「挂载不抛错 + 关键结构（标题/卡片/画布）存在」，不改源码。
          stubs: {
            ElTable: { template: '<div class="stub-el-table"><slot /></div>' },
            ElTableColumn: {
              template: '<span class="stub-el-tc"><slot :row="{}" :column="{}" :$index="0" /></span>',
            },
            ElDialog: {
              template: '<div v-if="modelValue" class="stub-el-dialog"><slot /><slot name="footer" /></div>',
              props: ['modelValue'],
            },
            ElSelect: { template: '<div class="stub-el-select"><slot /></div>' },
            // P2 长期记忆：MemoryRagView 使用 el-option；stub ElSelect 后真实
            // ElOption 找不到注入会抛错，故一并桩掉（与 ElSelect 桩同层约定）。
            ElOption: { template: '<span class="stub-el-option" />' },
          },
        },
        attachTo: document.body,
      })
      // 等待 onMounted 异步 fetch（mock 已返回）触发重渲染
      await new Promise((r) => setTimeout(r, 0))
      await wrapper.vm?.$nextTick?.()
      const html = wrapper.html()
      expect(html.length, `${name} 渲染为空`).toBeGreaterThan(50)
      expect(wrapper.text(), `${name} 未出现关键文本「${expectText}」`).toContain(expectText)
      wrapper.unmount()
    }
  )
})
