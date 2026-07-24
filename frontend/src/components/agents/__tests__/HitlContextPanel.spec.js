/**
 * 集成链路 B（组件层）：HITL 上下文面板 × 护栏联动（M6 × M7）。
 *   - 任务自带 guardrail_result → 直接渲染，不触发 evaluate（热插拔可切换）
 *   - 任务无 guardrail_result → 调用 useGuardrail().evaluate() 热插拔计算并渲染
 *
 * 通过 stub 子组件与 el-* 元素、mock 依赖 store/guardrail，隔离真实 Element Plus 与后端。
 * 设计依据：01-arch-design.md Q2 / 01-api-spec.md §6.1。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import HitlContextPanel from '@/components/agents/HitlContextPanel.vue'

// ── mock 依赖 ──
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { role: 'admin' } }),
}))
vi.mock('@/stores/agents', () => ({
  useAgentOrchestrationStore: () => ({
    approve: vi.fn(() => Promise.resolve({})),
    reject: vi.fn(() => Promise.resolve({})),
    fetchApprovals: vi.fn(() => Promise.resolve()),
  }),
}))
const guardrailEvaluate = vi.fn((action) => Promise.resolve({
  code: 0,
  data: {
    policy_id: 'gp-x', whitelist_hit: false,
    requires_confirm: true, requires_rollback_plan: true, passed: true,
  },
  message: 'ok',
}))
vi.mock('@/api/agent', () => ({
  default: {},
  useGuardrail: () => ({ evaluate: guardrailEvaluate }),
}))

// ── stub 子组件与 el-* ──
const GuardrailChipStub = {
  props: ['result'],
  template: '<div class="grc">{{ result && result.policy_id }}</div>',
}
const StatusBadgeStub = {
  props: ['type', 'value'],
  template: '<div class="sb"></div>',
}
const stubs = {
  GuardrailChip: GuardrailChipStub,
  StatusBadge: StatusBadgeStub,
  'el-empty': true,
  'el-icon': true,
  'el-input': true,
  'el-button': true,
}

const taskWithResult = {
  run_id: 'r1', id: 1, approval_id: 1, agent_name: '处置响应 Agent',
  action: 'host:isolate:X', impact_scope: '主机 WIN-X', status: 'pending',
  guardrail_result: {
    policy_id: 'gp-host', whitelist_hit: true,
    requires_confirm: true, requires_rollback_plan: true, passed: true,
  },
}
const taskWithout = {
  run_id: 'r2', id: 2, approval_id: 2, agent_name: '处置响应 Agent',
  action: 'host:isolate:Y', impact_scope: '主机 WIN-Y', status: 'pending',
}

describe('集成链路 B：HITL 上下文面板 × 护栏联动（M6 × M7）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('任务自带 guardrail_result → 直接渲染，不调用 evaluate（热插拔可零改动切换）', async () => {
    const wrapper = mount(HitlContextPanel, {
      props: { task: taskWithResult },
      global: { stubs },
    })
    await flushPromises() // 让 onMounted 触发的响应式重渲染生效
    const chip = wrapper.findComponent(GuardrailChipStub)
    expect(chip.props('result')).toEqual(taskWithResult.guardrail_result)
    expect(guardrailEvaluate).not.toHaveBeenCalled()
  })

  it('任务无 guardrail_result → 热插拔 useGuardrail().evaluate 计算并渲染', async () => {
    const wrapper = mount(HitlContextPanel, {
      props: { task: taskWithout },
      global: { stubs },
    })
    await flushPromises()
    expect(guardrailEvaluate).toHaveBeenCalledWith('host:isolate:Y', expect.objectContaining({ run_id: 'r2' }))
    const chip = wrapper.findComponent(GuardrailChipStub)
    expect(chip.props('result').policy_id).toBe('gp-x')
  })

  it('渲染动作与影响范围（M6 上下文面板内容）', async () => {
    const wrapper = mount(HitlContextPanel, {
      props: { task: taskWithResult },
      global: { stubs },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('host:isolate:X')
    expect(wrapper.text()).toContain('主机 WIN-X')
  })
})
