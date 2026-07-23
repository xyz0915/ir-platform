import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AttackChainTimeline from '@/components/analysis/AttackChainTimeline.vue'

describe('AttackChainTimeline.vue', () => {
  function createWrapper(props = {}) {
    return mount(AttackChainTimeline, {
      props: {
        timelineEvents: [],
        currentEventId: '',
        currentStage: '',
        ...props,
      },
    })
  }

  // ── Empty State ──
  it('shows empty state when no timeline events', () => {
    const wrapper = createWrapper({ timelineEvents: [] })
    expect(wrapper.find('.at-empty').exists()).toBe(true)
    expect(wrapper.find('.at-empty').text()).toBe('暂无时间线数据')
  })

  it('does not show empty state when events exist', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
    })
    expect(wrapper.find('.at-empty').exists()).toBe(false)
  })

  // ── Stage Rendering ──
  it('renders stages grouped by attack_stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify', severity: 'medium' },
      ],
    })
    const stages = wrapper.findAll('.at-stage')
    expect(stages.length).toBe(2)
    expect(stages[0].find('.at-stage-label').text()).toBe('执行')
    expect(stages[1].find('.at-stage-label').text()).toBe('持久化')
  })

  it('groups multiple events under the same stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'execution', event_type: 'process_terminate', severity: 'info' },
      ],
    })
    const stages = wrapper.findAll('.at-stage')
    expect(stages.length).toBe(1)
    const countEl = stages[0].find('.at-stage-count')
    expect(countEl.text()).toBe('2')
  })

  it('shows stage count with highlight when count > 0', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
    })
    const countEl = wrapper.find('.at-stage-count')
    expect(countEl.classes()).toContain('at-count-highlight')
  })

  // ── Current Stage Highlight ──
  it('highlights the current stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify', severity: 'medium' },
      ],
      currentStage: 'execution',
    })
    const stages = wrapper.findAll('.at-stage')
    expect(stages[0].classes()).toContain('at-stage-current')
    expect(stages[1].classes()).not.toContain('at-stage-current')
  })

  it('marks dot as current for the current stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
      currentStage: 'execution',
    })
    const dot = wrapper.find('.at-stage-dot')
    expect(dot.classes()).toContain('at-dot-current')
  })

  it('does not highlight any stage when currentStage is empty', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
      currentStage: '',
    })
    expect(wrapper.find('.at-stage-current').exists()).toBe(false)
  })

  // ── Expand / Collapse ──
  it('starts with current stage expanded', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify', severity: 'medium' },
      ],
      currentStage: 'execution',
    })
    await wrapper.vm.$nextTick()

    const stages = wrapper.findAll('.at-stage')
    // The current stage should be expanded automatically
    expect(stages[0].classes()).toContain('at-stage-expanded')
    // Non-current stage should not be expanded initially
    expect(stages[1].classes()).not.toContain('at-stage-expanded')
  })

  it('toggles stage expansion on click', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
    })
    await wrapper.vm.$nextTick()

    const stage = wrapper.find('.at-stage')
    // Click to expand
    await stage.trigger('click')
    expect(stage.classes()).toContain('at-stage-expanded')

    // Click to collapse
    await stage.trigger('click')
    expect(stage.classes()).not.toContain('at-stage-expanded')
  })

  it('emits toggle-stage event when stage is clicked', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
    })
    await wrapper.vm.$nextTick()

    await wrapper.find('.at-stage').trigger('click')
    expect(wrapper.emitted('toggle-stage')).toBeTruthy()
    expect(wrapper.emitted('toggle-stage')[0]).toEqual(['execution'])
  })

  // ── Event Items ──
  it('shows event items when stage is expanded', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
    })
    await wrapper.vm.$nextTick()

    // Expand the stage
    await wrapper.find('.at-stage').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.at-event-list').exists()).toBe(true)
    expect(wrapper.findAll('.at-event-item').length).toBe(1)
  })

  it('emits select-event when an event item is clicked', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
    })
    await wrapper.vm.$nextTick()

    // Expand the stage
    await wrapper.find('.at-stage').trigger('click')
    await wrapper.vm.$nextTick()

    // Click the event item
    await wrapper.find('.at-event-item').trigger('click')
    expect(wrapper.emitted('select-event')).toBeTruthy()
    expect(wrapper.emitted('select-event')[0]).toEqual(['e1'])
  })

  it('highlights current event item', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'execution', event_type: 'process_terminate', severity: 'info' },
      ],
      currentEventId: 'e1',
      currentStage: 'execution',
    })
    const items = wrapper.findAll('.at-event-item')
    expect(items[0].classes()).toContain('at-event-current')
    expect(items[1].classes()).not.toContain('at-event-current')
  })

  // ── Unknown Stage ──
  it('handles events with unknown attack_stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: '', event_type: 'process_start', severity: 'high' },
      ],
    })
    const stages = wrapper.findAll('.at-stage')
    expect(stages.length).toBe(1)
    expect(stages[0].find('.at-stage-label').text()).toBe('未知')
  })

  // ── Summary Text ──
  it('shows summary text for collapsed stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        {
          id: 'e1',
          attack_stage: 'execution',
          event_type: 'process_start',
          severity: 'high',
          summary: 'powershell.exe launched',
        },
      ],
    })
    expect(wrapper.find('.at-stage-summary').exists()).toBe(true)
    expect(wrapper.find('.at-summary-text').text()).toBe('powershell.exe launched')
  })

  it('hides summary when stage is expanded', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        {
          id: 'e1',
          attack_stage: 'execution',
          event_type: 'process_start',
          severity: 'high',
          summary: 'powershell.exe launched',
        },
      ],
    })
    await wrapper.vm.$nextTick()

    // Expand
    await wrapper.find('.at-stage').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.at-stage-summary').exists()).toBe(false)
  })
})
