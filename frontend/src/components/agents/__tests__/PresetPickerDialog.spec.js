/**
 * Test: PresetPickerDialog.vue 卡片选择器逻辑。
 *
 * 覆盖（Test 5）：
 *  - parsePreset：nodeCount / typeSummary 计算（agents 带 type、nodes 优先、字符串 agent、
 *    缺失 type 回退 name/agent）
 *  - 搜索过滤：name / description / tags 匹配（大小写不敏感）
 *  - 分类过滤：category 去重下拉 + 选择后过滤
 *  - 空状态：presets 为空 →「暂无预设」；搜索无结果 →「无匹配预设」；加载失败兜底为空
 *  - recordPresetUse 调用时机：确认加载时以 preset.id 调用，并 emit('selected') / emit('close')
 *
 * 通过 stub el-* 与 mock @/api/agent 隔离 Element Plus 与后端（参照 AgentForm.spec 模式）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import PresetPickerDialog from '@/components/agents/PresetPickerDialog.vue'

const getPresets = vi.fn()
const recordPresetUse = vi.fn()

vi.mock('@/api/agent', () => ({
  default: {
    pipeline: {
      getPresets: (...a) => getPresets(...a),
      recordPresetUse: (...a) => recordPresetUse(...a),
    },
  },
}))

const stubs = {
  'el-dialog': {
    template: '<div class="el-dialog-stub"><slot name="header" /><slot /><slot name="footer" /></div>',
  },
  'el-select': {
    template:
      '<div class="el-select-stub"><button class="sel-trigger" @click="$emit(\'update:modelValue\', \'取证\')">触发</button><slot /></div>',
    emits: ['update:modelValue'],
  },
  'el-option': { props: ['label', 'value'], template: '<div class="el-option-stub">{{ label }}</div>' },
  'el-button': {
    props: ['disabled', 'type'],
    template: '<button class="el-button-stub" :disabled="disabled" :type="type"><slot /></button>',
  },
  'el-icon': { template: '<i class="el-icon-stub"><slot /></i>' },
}

/** 按文本找按钮（取消 / 加载选中），避免 find 命中第一个按钮。 */
function findButton(wrapper, text) {
  return wrapper.findAll('.el-button-stub').find((b) => b.text() === text)
}

function presetRow(overrides = {}) {
  return {
    id: 1,
    name: '取证模板',
    description: '快速取证流程',
    agents: [
      { type: 'collector', name: 'c1' },
      { type: 'collector', name: 'c2' },
      { type: 'analyzer', name: 'a1' },
    ],
    category: '取证',
    tags: ['fast', 'forensic'],
    created_at: '2026-01-02 10:00:00',
    usage_count: 3,
    author: 'alice',
    ...overrides,
  }
}

function mountDialog(visible = false) {
  return mount(PresetPickerDialog, {
    props: { visible },
    global: {
      stubs,
      directives: { loading: () => {} }, // Element Plus v-loading 指令桩
    },
  })
}

async function openDialog(wrapper) {
  await wrapper.setProps({ visible: true })
  await flushPromises()
}

beforeEach(() => {
  getPresets.mockReset()
  recordPresetUse.mockReset()
})

describe('parsePreset: nodeCount / typeSummary', () => {
  it('agents 带 type → 统计分布，count>1 显示 ×n，按数量降序', async () => {
    getPresets.mockResolvedValue({ data: [presetRow()] })
    const wrapper = mountDialog()
    await openDialog(wrapper)

    const card = wrapper.find('.preset-card')
    expect(card.find('.node-count').text()).toContain('3')
    expect(card.find('.type-summary').text()).toBe('collector×2 · analyzer')
  })

  it('nodes 存在时优先使用 nodes（不回退 agents）', async () => {
    getPresets.mockResolvedValue({
      data: [presetRow({ nodes: [{ type: 'x' }, { type: 'y' }, { type: 'y' }], agents: [] })],
    })
    const wrapper = mountDialog()
    await openDialog(wrapper)

    const card = wrapper.find('.preset-card')
    expect(card.find('.node-count').text()).toContain('3')
    expect(card.find('.type-summary').text()).toBe('y×2 · x')
  })

  it('字符串 agent 数组 → 以字符串本身作为类型统计', async () => {
    getPresets.mockResolvedValue({ data: [presetRow({ agents: ['collector', 'collector', 'analyzer'] })] })
    const wrapper = mountDialog()
    await openDialog(wrapper)

    const card = wrapper.find('.preset-card')
    expect(card.find('.node-count').text()).toContain('3')
    expect(card.find('.type-summary').text()).toBe('collector×2 · analyzer')
  })

  it('对象缺失 type → 回退 name / agent 字段', async () => {
    getPresets.mockResolvedValue({
      data: [presetRow({ agents: [{ name: 'custom' }, { agent: 'other' }] })],
    })
    const wrapper = mountDialog()
    await openDialog(wrapper)

    const card = wrapper.find('.preset-card')
    expect(card.find('.node-count').text()).toContain('2')
    expect(card.find('.type-summary').text()).toBe('custom · other')
  })

  it('无 nodes/agents → nodeCount 0 且无 typeSummary', async () => {
    getPresets.mockResolvedValue({ data: [presetRow({ agents: [] })] })
    const wrapper = mountDialog()
    await openDialog(wrapper)

    const card = wrapper.find('.preset-card')
    expect(card.find('.node-count').text()).toContain('0')
    expect(card.find('.type-summary').exists()).toBe(false)
  })
})

describe('搜索过滤', () => {
  it('按 name 匹配（大小写不敏感）', async () => {
    getPresets.mockResolvedValue({
      data: [presetRow({ id: 1, name: 'AlphaFlow' }), presetRow({ id: 2, name: 'BetaFlow' })],
    })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    expect(wrapper.findAll('.preset-card').length).toBe(2)

    await wrapper.find('.search-input').setValue('alpha')
    expect(wrapper.findAll('.preset-card').length).toBe(1)
    expect(wrapper.find('.card-name').text()).toBe('AlphaFlow')
  })

  it('按 description 匹配', async () => {
    getPresets.mockResolvedValue({
      data: [presetRow({ id: 1, description: '特殊取证' }), presetRow({ id: 2, description: '普通' })],
    })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    await wrapper.find('.search-input').setValue('特殊')
    expect(wrapper.findAll('.preset-card').length).toBe(1)
    expect(wrapper.find('.card-name').text()).toBe('取证模板')
  })

  it('按 tags 匹配', async () => {
    getPresets.mockResolvedValue({
      data: [presetRow({ id: 1, tags: ['wanted-tag'] }), presetRow({ id: 2, tags: ['other'] })],
    })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    await wrapper.find('.search-input').setValue('wanted-tag')
    expect(wrapper.findAll('.preset-card').length).toBe(1)
  })
})

describe('分类过滤', () => {
  it('category 去重生成下拉选项（含「全部分类」）', async () => {
    getPresets.mockResolvedValue({
      data: [
        presetRow({ id: 1, category: '取证' }),
        presetRow({ id: 2, category: '取证' }),
        presetRow({ id: 3, category: '分析' }),
        presetRow({ id: 4, category: undefined }), // 缺省归 other
      ],
    })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    const options = wrapper.findAll('.el-option-stub').map((o) => o.text())
    expect(options[0]).toBe('全部分类')
    expect(options).toContain('取证')
    expect(options).toContain('分析')
    expect(options).toContain('other')
    // 去重：取证只出现一次
    expect(options.filter((o) => o === '取证').length).toBe(1)
  })

  it('选择分类后仅显示该类预设', async () => {
    getPresets.mockResolvedValue({
      data: [presetRow({ id: 1, category: '取证' }), presetRow({ id: 2, category: '分析', name: '分析模板' })],
    })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    expect(wrapper.findAll('.preset-card').length).toBe(2)

    await wrapper.find('.sel-trigger').trigger('click') // 模拟选择「取证」
    expect(wrapper.findAll('.preset-card').length).toBe(1)
    expect(wrapper.find('.card-name').text()).toBe('取证模板')
  })
})

describe('空状态', () => {
  it('presets 为空 → 暂无预设', async () => {
    getPresets.mockResolvedValue({ data: [] })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    expect(wrapper.text()).toContain('暂无预设')
    expect(wrapper.findAll('.preset-card').length).toBe(0)
  })

  it('搜索无结果 → 无匹配预设', async () => {
    getPresets.mockResolvedValue({ data: [presetRow()] })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    await wrapper.find('.search-input').setValue('zzz-nothing')
    expect(wrapper.text()).toContain('无匹配预设')
  })

  it('加载失败 → 兜底为空态', async () => {
    getPresets.mockRejectedValue(new Error('network'))
    const wrapper = mountDialog()
    await openDialog(wrapper)
    expect(wrapper.text()).toContain('暂无预设')
  })
})

describe('recordPresetUse 调用时机', () => {
  it('确认加载时以 preset.id 调用并 emit selected/close', async () => {
    getPresets.mockResolvedValue({ data: [presetRow()] })
    recordPresetUse.mockResolvedValue({ code: 0 })
    const wrapper = mountDialog()
    await openDialog(wrapper)

    await wrapper.find('.preset-card').trigger('click') // 选中
    await findButton(wrapper, '加载选中').trigger('click') // 加载选中

    expect(recordPresetUse).toHaveBeenCalledTimes(1)
    expect(recordPresetUse).toHaveBeenCalledWith(1)
    expect(wrapper.emitted('selected')[0][0].id).toBe(1)
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('recordPresetUse 失败不阻断加载（catch 吞掉）', async () => {
    getPresets.mockResolvedValue({ data: [presetRow()] })
    recordPresetUse.mockRejectedValue(new Error('boom'))
    const wrapper = mountDialog()
    await openDialog(wrapper)

    await wrapper.find('.preset-card').trigger('click')
    await findButton(wrapper, '加载选中').trigger('click')

    expect(wrapper.emitted('selected')[0][0].id).toBe(1)
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('未选中时确认按钮禁用', async () => {
    getPresets.mockResolvedValue({ data: [presetRow()] })
    const wrapper = mountDialog()
    await openDialog(wrapper)
    // 未点击卡片 → 无 selectedPreset → 确认按钮 disabled（取消按钮不受影响）
    const confirmBtn = findButton(wrapper, '加载选中')
    const cancelBtn = findButton(wrapper, '取消')
    expect(confirmBtn.attributes('disabled')).toBeDefined()
    expect(cancelBtn.attributes('disabled')).toBeUndefined()
  })
})
