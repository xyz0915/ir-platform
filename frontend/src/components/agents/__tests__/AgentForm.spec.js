/**
 * Fix A 组件层测试：AgentForm.vue
 *   - 数据来源改为标签输入（el-select multiple + filterable + allow-create + default-first-option）
 *   - 保存 payload 结构：data_sources 为数组；tools / model_profile 为选中值
 *
 * 通过 stub el-* 与 mock store / agentApi，隔离 Element Plus 与后端。
 * 设计依据：01-design.md §3.2 / T3。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AgentForm from '@/components/agents/AgentForm.vue'

// ── mock 依赖 ──
const registerAgent = vi.fn(() => Promise.resolve({}))
const updateAgentAction = vi.fn(() => Promise.resolve({}))

vi.mock('@/stores/agentManagement', () => ({
  useAgentManagementStore: () => ({
    agents: [{ name: 'other', display_name: 'Other Agent' }],
    registerAgent,
    updateAgentAction,
  }),
}))

vi.mock('@/api/agent', () => ({
  default: {
    tools: { listTools: vi.fn(() => Promise.resolve({ data: [{ tool_id: 't1', name: 'T1' }] })) },
    settings: {
      listModelProfiles: vi.fn(() =>
        Promise.resolve({ data: [{ profile_id: 'p1', name: 'P1', provider: 'openai' }] }),
      ),
    },
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), warning: vi.fn() },
}))

// ── stub el-* ──
const ElSelectStub = {
  name: 'ElSelect',
  props: ['modelValue', 'multiple', 'filterable', 'allowCreate', 'defaultFirstOption'],
  emits: ['update:modelValue'],
  template: `<div class="el-select-stub"
    :data-multiple="multiple"
    :data-allow-create="allowCreate"
    :data-default-first-option="defaultFirstOption"><slot /></div>`,
}

const stubs = {
  'el-select': ElSelectStub,
  'el-option': { template: '<option />' },
  'el-input': { template: '<input />' },
  'el-button': { template: '<button><slot /></button>' },
  'el-dialog': { template: '<div class="el-dialog-stub"><slot /><slot name="footer" /></div>' },
  'el-form': { template: '<form class="el-form-stub"><slot /></form>' },
  'el-form-item': { template: '<div class="el-form-item-stub"><slot /></div>' },
}

function mountForm(props) {
  const wrapper = mount(AgentForm, { props, global: { stubs } })
  return wrapper
}

describe('Fix A：AgentForm.vue 标签输入 + 保存 payload 结构', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('数据来源使用标签输入（el-select multiple + allow-create + default-first-option）', async () => {
    const wrapper = mountForm({ visible: true, editingAgent: null })
    await flushPromises()
    const selects = wrapper.findAll('.el-select-stub')
    expect(selects.length).toBeGreaterThanOrEqual(1)
    // 「数据来源」是模板中唯一带 allow-create 的 el-select
    const dataSources = selects.find((s) => {
      const a = s.attributes() || {}
      return 'allow-create' in a || 'data-allow-create' in a
    })
    expect(dataSources).toBeTruthy()
    const a = dataSources.attributes() || {}
    // multiple 可能以 data-multiple 或 allow-create 同级属性形式出现（取决于 stub 绑定）
    expect('multiple' in a || 'data-multiple' in a).toBe(true)
    expect('allow-create' in a || 'data-allow-create' in a).toBe(true)
    expect('default-first-option' in a || 'data-default-first-option' in a).toBe(true)
  })

  it('新建保存：payload.data_sources 为数组，tools / model_profile 为选中值', async () => {
    const wrapper = mountForm({ visible: true, editingAgent: null })
    await flushPromises()

    wrapper.vm.form.name = 'a1'
    wrapper.vm.form.display_name = 'A1'
    wrapper.vm.form.data_sources = ['邮件网关', 'DNS 日志']
    wrapper.vm.form.tools = ['t1']
    wrapper.vm.form.model_profile = 'p1'

    await wrapper.vm.onSave()
    await flushPromises()

    expect(registerAgent).toHaveBeenCalledTimes(1)
    const payload = registerAgent.mock.calls[0][0]
    expect(Array.isArray(payload.data_sources)).toBe(true)
    expect(payload.data_sources).toEqual(['邮件网关', 'DNS 日志'])
    expect(payload.tools).toEqual(['t1'])
    expect(payload.model_profile).toBe('p1')
  })

  it('编辑保存走 updateAgentAction，payload 结构与回显一致', async () => {
    const editing = {
      name: 'a1',
      display_name: 'A1',
      description: 'd',
      data_sources: ['x'],
      depends_on: [],
      tools: ['t1'],
      model_profile: 'p1',
    }
    const wrapper = mountForm({ visible: false, editingAgent: editing })
    // 模拟 dialog 由关闭到打开，触发 watch(props.visible) 回填表单
    await wrapper.setProps({ visible: true })
    await flushPromises()

    // 回显：data_sources 应为数组
    expect(Array.isArray(wrapper.vm.form.data_sources)).toBe(true)
    expect(wrapper.vm.form.data_sources).toEqual(['x'])

    await wrapper.vm.onSave()
    await flushPromises()

    expect(updateAgentAction).toHaveBeenCalledTimes(1)
    const [nameArg, payload] = updateAgentAction.mock.calls[0]
    expect(nameArg).toBe('a1')
    expect(payload.data_sources).toEqual(['x'])
    expect(payload.tools).toEqual(['t1'])
    expect(payload.model_profile).toBe('p1')
  })
})
