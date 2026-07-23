import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DispositionPanel from '@/components/analysis/DispositionPanel.vue'

describe('DispositionPanel.vue', () => {
  function createWrapper(props = {}) {
    return mount(DispositionPanel, {
      props: {
        dispositions: [],
        eventId: 'evt-123',
        ...props,
      },
    })
  }

  // ── Title ──
  it('renders title', () => {
    const wrapper = createWrapper()
    expect(wrapper.find('.dp-title').text()).toBe('处置记录')
  })

  // ── Empty State ──
  it('shows empty state when no dispositions', () => {
    const wrapper = createWrapper({ dispositions: [] })
    expect(wrapper.find('.dp-empty').exists()).toBe(true)
    expect(wrapper.find('.dp-empty').text()).toBe('暂无处置记录')
  })

  it('does not show empty state when dispositions exist', () => {
    const wrapper = createWrapper({
      dispositions: [{ id: 'd1', operator: 'admin', action: 'isolate' }],
    })
    expect(wrapper.find('.dp-empty').exists()).toBe(false)
  })

  // ── Disposition List ──
  it('renders disposition items', () => {
    const wrapper = createWrapper({
      dispositions: [
        { id: 'd1', operator: 'admin', action: 'isolate', created_at: '2024-01-01 10:00' },
        { id: 'd2', operator: 'analyst', action: 'review', created_at: '2024-01-02 14:30' },
      ],
    })
    expect(wrapper.findAll('.dp-item').length).toBe(2)
  })

  it('renders operator name', () => {
    const wrapper = createWrapper({
      dispositions: [{ id: 'd1', operator: 'admin', action: 'isolate' }],
    })
    expect(wrapper.find('.dp-actor').text()).toBe('admin')
  })

  it('renders action label', () => {
    const wrapper = createWrapper({
      dispositions: [{ id: 'd1', operator: 'admin', action: 'isolate' }],
    })
    expect(wrapper.find('.dp-action').text()).toBe('隔离主机')
  })

  it('renders comment when present', () => {
    const wrapper = createWrapper({
      dispositions: [{
        id: 'd1', operator: 'admin', action: 'isolate',
        comment: 'Confirmed malicious process',
      }],
    })
    expect(wrapper.find('.dp-comment').exists()).toBe(true)
    expect(wrapper.find('.dp-comment').text()).toBe('"Confirmed malicious process"')
  })

  it('does not render comment div when not present', () => {
    const wrapper = createWrapper({
      dispositions: [{ id: 'd1', operator: 'admin', action: 'isolate' }],
    })
    expect(wrapper.find('.dp-comment').exists()).toBe(false)
  })

  it('renders created_at timestamp', () => {
    const wrapper = createWrapper({
      dispositions: [{
        id: 'd1', operator: 'admin', action: 'isolate',
        created_at: '2024-06-15 08:30:00',
      }],
    })
    expect(wrapper.find('.dp-time').text()).toBe('2024-06-15 08:30:00')
  })

  it('maps action labels correctly', () => {
    const actions = [
      { key: 'isolate', label: '隔离主机' },
      { key: 'kill_process', label: '结束进程' },
      { key: 'block_ip', label: '封锁IP' },
      { key: 'add_rule', label: '添加规则' },
      { key: 'escalate', label: '上报' },
      { key: 'ignore', label: '忽略' },
      { key: 'review', label: '复核' },
    ]
    for (const { key, label } of actions) {
      const wrapper = createWrapper({
        dispositions: [{ id: 'd1', operator: 'admin', action: key }],
      })
      expect(wrapper.find('.dp-action').text()).toBe(label)
    }
  })

  it('shows raw action key when not in label map', () => {
    const wrapper = createWrapper({
      dispositions: [{ id: 'd1', operator: 'admin', action: 'custom_action' }],
    })
    expect(wrapper.find('.dp-action').text()).toBe('custom_action')
  })

  // ── Add Comment Input ──
  it('renders input field and submit button', () => {
    const wrapper = createWrapper()
    expect(wrapper.find('.dp-input').exists()).toBe(true)
    expect(wrapper.find('.dp-input-wrap .btn-primary').exists()).toBe(true)
  })

  it('submit button is disabled when input is empty', () => {
    const wrapper = createWrapper()
    const btn = wrapper.find('.dp-input-wrap .btn-primary')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('submit button is enabled when input has text', async () => {
    const wrapper = createWrapper()
    const input = wrapper.find('.dp-input')
    await input.setValue('Suspicious process found')

    const btn = wrapper.find('.dp-input-wrap .btn-primary')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('emits add-disposition with comment text on button click', async () => {
    const wrapper = createWrapper()
    const input = wrapper.find('.dp-input')
    await input.setValue('Suspicious process found')

    await wrapper.find('.dp-input-wrap .btn-primary').trigger('click')

    expect(wrapper.emitted('add-disposition')).toBeTruthy()
    expect(wrapper.emitted('add-disposition')[0]).toEqual(['Suspicious process found'])
  })

  it('clears input after submission', async () => {
    const wrapper = createWrapper()
    const input = wrapper.find('.dp-input')
    await input.setValue('Test comment')

    await wrapper.find('.dp-input-wrap .btn-primary').trigger('click')

    expect(input.element.value).toBe('')
  })

  it('emits add-disposition on Enter key', async () => {
    const wrapper = createWrapper()
    const input = wrapper.find('.dp-input')
    await input.setValue('Quick note')

    await input.trigger('keyup.enter')

    expect(wrapper.emitted('add-disposition')).toBeTruthy()
    expect(wrapper.emitted('add-disposition')[0]).toEqual(['Quick note'])
  })

  it('does not emit when submitting empty or whitespace', async () => {
    const wrapper = createWrapper()
    const input = wrapper.find('.dp-input')

    // Try submitting with just spaces
    await input.setValue('   ')
    await wrapper.find('.dp-input-wrap .btn-primary').trigger('click')
    expect(wrapper.emitted('add-disposition')).toBeFalsy()

    // Try empty string
    await input.setValue('')
    await wrapper.find('.dp-input-wrap .btn-primary').trigger('click')
    expect(wrapper.emitted('add-disposition')).toBeFalsy()
  })
})
