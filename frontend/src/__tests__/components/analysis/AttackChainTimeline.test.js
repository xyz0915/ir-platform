import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import AttackChainTimeline from '@/components/analysis/AttackChainTimeline.vue'

// ── 测试辅助函数 ──

function createWrapper(props = {}) {
  return mount(AttackChainTimeline, {
    props: {
      timelineEvents: [],
      currentEventId: '',
      currentStage: '',
      loading: false,
      error: '',
      ...props,
    },
  })
}

// ── 测试用样本数据 ──

const mockEvent = (overrides = {}) => ({
  id: 'evt1',
  timestamp: '2026-07-24T14:32:15Z',
  event_type: 'process_start',
  severity: 'high',
  attack_stage: 'execution',
  ...overrides,
})

const sampleEvents = [
  { id: 'evt1', timestamp: '2026-07-24T14:32:15Z', event_type: 'process_start', severity: 'high', attack_stage: 'execution', evidence: { process_name: 'LsaIso.exe', pid: 1088 } },
  { id: 'evt2', timestamp: '2026-07-24T14:32:18Z', event_type: 'network_outbound', severity: 'medium', attack_stage: 'execution', evidence: { remote_address: '1.2.3.4', remote_port: 443, process_name: 'ToDesk.exe' } },
  { id: 'evt3', timestamp: '2026-07-24T14:33:00Z', event_type: 'registry_modify', severity: 'low', attack_stage: 'persistence', evidence: { registry_key: 'HKLM\\System\\CurrentControlSet\\Services\\MalService' } },
  { id: 'evt4', timestamp: '2026-07-24T14:34:00Z', event_type: 'file_create', severity: 'critical', attack_stage: 'persistence', evidence: { file_path: 'C:\\Windows\\System32\\malicious.dll' } },
  { id: 'evt5', timestamp: '2026-07-24T14:35:00Z', event_type: 'dns_query', severity: 'info', attack_stage: 'command_and_control', evidence: { remote_address: 'evil.example.com', process_name: 'svchost.exe' } },
]

// ======================================================================
// 加载态（骨架屏）
// ======================================================================
describe('Loading State', () => {
  it('shows skeleton screen when loading=true and no events', () => {
    const wrapper = createWrapper({ loading: true, timelineEvents: [] })
    expect(wrapper.find('.at-loading').exists()).toBe(true)
    // 骨架屏包含 3 组骨架块
    expect(wrapper.findAll('.at-skeleton').length).toBe(3)
  })

  it('shows content when loading=true but events exist', () => {
    const wrapper = createWrapper({
      loading: true,
      timelineEvents: [sampleEvents[0]],
    })
    // 有事件时即使 loading=true 也应显示正常内容（骨架屏只在无事件时显示）
    expect(wrapper.find('.at-loading').exists()).toBe(false)
    expect(wrapper.find('.at-stages').exists()).toBe(true)
  })
})

// ======================================================================
// 错误态
// ======================================================================
describe('Error State', () => {
  it('shows error panel when error is non-empty', () => {
    const wrapper = createWrapper({ error: 'Network error' })
    expect(wrapper.find('.at-error').exists()).toBe(true)
    expect(wrapper.find('.at-error-text').text()).toBe('时间线数据加载失败')
    expect(wrapper.find('.at-error-detail').text()).toBe('Network error')
  })

  it('shows retry button in error state', () => {
    const wrapper = createWrapper({ error: 'Something went wrong' })
    expect(wrapper.find('.at-retry-btn').exists()).toBe(true)
    expect(wrapper.find('.at-retry-btn').text()).toBe('重试')
  })

  it('emits retry event when retry button is clicked', async () => {
    const wrapper = createWrapper({ error: 'Error' })
    await wrapper.find('.at-retry-btn').trigger('click')
    expect(wrapper.emitted('retry')).toBeTruthy()
  })

  it('shows loading skeleton when both loading and error are set (loading takes priority in template)', () => {
    // 模板中加载态条件 v-if="loading && !timelineEvents.length" 在 error 的 v-else-if 之前
    // 因此 loading=true 且无事件时，骨架屏优先显示
    const wrapper = createWrapper({ loading: true, error: 'Error' })
    expect(wrapper.find('.at-loading').exists()).toBe(true)
    expect(wrapper.find('.at-error').exists()).toBe(false)
  })
})

// ======================================================================
// 空状态
// ======================================================================
describe('Empty State', () => {
  it('shows empty state when no timeline events', () => {
    const wrapper = createWrapper({ timelineEvents: [] })
    expect(wrapper.find('.at-empty').exists()).toBe(true)
    expect(wrapper.find('.at-empty-text').text()).toBe('暂无时间线数据')
    expect(wrapper.find('.at-empty-hint').text()).toBe('请确认案件关联的事件是否存在')
  })

  it('does not show empty state when events exist', () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    expect(wrapper.find('.at-empty').exists()).toBe(false)
  })

  it('does not show stages when no events', () => {
    const wrapper = createWrapper({ timelineEvents: [] })
    expect(wrapper.find('.at-stages').exists()).toBe(false)
  })
})

// ======================================================================
// 阶段渲染
// ======================================================================
describe('Stage Rendering', () => {
  it('renders stages grouped by attack_stage', () => {
    const wrapper = createWrapper({ timelineEvents: sampleEvents })
    const stages = wrapper.findAll('.at-stage')
    // execution, persistence, command_and_control
    expect(stages.length).toBe(3)
    expect(stages[0].find('.at-stage-label').text()).toBe('执行')
    expect(stages[1].find('.at-stage-label').text()).toBe('持久化')
    expect(stages[2].find('.at-stage-label').text()).toBe('C2')
  })

  it('groups multiple events under the same stage', () => {
    const wrapper = createWrapper({
      timelineEvents: sampleEvents.slice(0, 2), // 2 execution events
    })
    const stages = wrapper.findAll('.at-stage')
    expect(stages.length).toBe(1)
    expect(stages[0].find('.at-stage-count').text()).toBe('2')
  })

  it('shows stage count with highlight class when count > 0', () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    const countEl = wrapper.find('.at-stage-count')
    expect(countEl.classes()).toContain('at-count-highlight')
  })

  it('highlights the current stage', () => {
    const wrapper = createWrapper({
      timelineEvents: sampleEvents,
      currentStage: 'persistence',
    })
    const stages = wrapper.findAll('.at-stage')
    expect(stages[0].classes()).not.toContain('at-stage-current') // execution
    expect(stages[1].classes()).toContain('at-stage-current')      // persistence (current)
    expect(stages[2].classes()).not.toContain('at-stage-current')  // C2
  })

  it('does not highlight any stage when currentStage is empty', () => {
    const wrapper = createWrapper({
      timelineEvents: sampleEvents,
      currentStage: '',
    })
    const currentStages = wrapper.findAll('.at-stage-current')
    expect(currentStages.length).toBe(0)
  })

  it('handles events with unknown attack_stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'u1', attack_stage: '', event_type: 'process_start', severity: 'high' },
      ],
    })
    const stages = wrapper.findAll('.at-stage')
    expect(stages.length).toBe(1)
    expect(stages[0].find('.at-stage-label').text()).toBe('未知')
  })

  it('renders stages in correct MITRE ATT&CK order', () => {
    const events = [
      { id: 'e1', attack_stage: 'impact', event_type: 'process_start', severity: 'high' },
      { id: 'e2', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      { id: 'e3', attack_stage: 'initial_access', event_type: 'process_start', severity: 'high' },
    ]
    const wrapper = createWrapper({ timelineEvents: events })
    const labels = wrapper.findAll('.at-stage-label')
    expect(labels.length).toBe(3)
    expect(labels[0].text()).toBe('初始访问')
    expect(labels[1].text()).toBe('执行')
    expect(labels[2].text()).toBe('影响')
  })
})

// ======================================================================
// 阶段严重度标记（P1）
// ======================================================================
describe('Stage Severity Badge (P1)', () => {
  it('shows severity badge on stage with high severity events', () => {
    const wrapper = createWrapper({ timelineEvents: sampleEvents.slice(0, 2) })
    const badge = wrapper.find('.at-stage-severity-badge')
    expect(badge.exists()).toBe(true)
    // execution stage has severity "high" (evt1) and "medium" (evt2) → max is "high"
    expect(badge.classes()).toContain('ssb-high')
  })

  it('does not show badge when max severity is low/info', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'low' },
      ],
    })
    expect(wrapper.find('.at-stage-severity-badge').exists()).toBe(false)
  })

  it('shows badge with correct severity class for critical', () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[3]] }) // file_create, critical
    const badge = wrapper.find('.at-stage-severity-badge')
    expect(badge.classes()).toContain('ssb-critical')
  })

  it('shows badge with correct severity class for medium', () => {
    const wrapper = createWrapper({
      timelineEvents: [sampleEvents[1]], // network_outbound, medium
    })
    const badge = wrapper.find('.at-stage-severity-badge')
    expect(badge.classes()).toContain('ssb-medium')
  })
})

// ======================================================================
// 折叠/展开
// ======================================================================
describe('Expand / Collapse', () => {
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
    expect(stages[0].classes()).toContain('at-stage-expanded')
    expect(stages[1].classes()).not.toContain('at-stage-expanded')
  })

  it('toggles stage expansion on header click', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()

    const header = wrapper.find('.at-stage-header')
    await header.trigger('click')
    expect(wrapper.find('.at-stage').classes()).toContain('at-stage-expanded')

    await header.trigger('click')
    expect(wrapper.find('.at-stage').classes()).not.toContain('at-stage-expanded')
  })

  it('emits toggle-stage event when stage header is clicked', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()

    await wrapper.find('.at-stage-header').trigger('click')
    expect(wrapper.emitted('toggle-stage')).toBeTruthy()
    expect(wrapper.emitted('toggle-stage')[0]).toEqual(['execution'])
  })

  it('shows chevron that rotates when expanded', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()

    const chevron = wrapper.find('.at-chevron')
    expect(chevron.classes()).not.toContain('at-chevron-open')

    await wrapper.find('.at-stage-header').trigger('click')
    expect(chevron.classes()).toContain('at-chevron-open')
  })

  it('shows event items when stage is expanded', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()

    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.at-event-list').exists()).toBe(true)
    expect(wrapper.findAll('.at-event-item').length).toBe(1)
  })
})

// ======================================================================
// 事件条目渲染
// ======================================================================
describe('Event Items', () => {
  it('emits select-event when an event item is clicked', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    await wrapper.find('.at-event-item').trigger('click')
    expect(wrapper.emitted('select-event')).toBeTruthy()
    expect(wrapper.emitted('select-event')[0]).toEqual(['evt1'])
  })

  it('shows severity label on event items', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    const sevEl = wrapper.find('.ae-severity')
    expect(sevEl.exists()).toBe(true)
    expect(sevEl.text()).toBe('高危')
    expect(sevEl.classes()).toContain('sev-high')
  })

  it('shows event type icon and label', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[3]] }) // file_create
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.ae-icon').exists()).toBe(true)
    expect(wrapper.find('.ae-type-label').text()).toBe('文件创建')
  })

  it('shows timestamp in HH:MM:SS format', async () => {
    // 使用 UTC 时间戳 06:32:15Z → CST (UTC+8) 本地时间 14:32:15
    const wrapper = createWrapper({
      timelineEvents: [{ id: 'e1', timestamp: '2026-07-24T06:32:15Z', attack_stage: 'execution', event_type: 'process_start', severity: 'high' }],
    })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    const ts = wrapper.find('.ae-timestamp')
    expect(ts.text()).toBe('14:32:15')
  })
})

// ======================================================================
// 时间戳格式化
// ======================================================================
describe('Timestamp Formatting', () => {
  it('formats ISO timestamp to HH:MM:SS', () => {
    // UTC 00:05:09Z → CST (UTC+8) 本地时间 08:05:09
    const wrapper = createWrapper({
      timelineEvents: [{ id: 'e1', timestamp: '2026-07-24T00:05:09Z', attack_stage: 'execution', event_type: 'process_start', severity: 'high' }],
    })
    expect(wrapper.find('.ae-timestamp').text()).toBe('08:05:09')
  })

  it('shows fallback for null timestamp', () => {
    const wrapper = createWrapper({
      timelineEvents: [{ id: 'e1', timestamp: null, attack_stage: 'execution', event_type: 'process_start', severity: 'high' }],
    })
    expect(wrapper.find('.ae-timestamp').text()).toBe('--:--:--')
  })

  it('shows fallback for undefined timestamp', () => {
    const wrapper = createWrapper({
      timelineEvents: [{ id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' }],
    })
    expect(wrapper.find('.ae-timestamp').text()).toBe('--:--:--')
  })

  it('shows fallback for invalid timestamp', () => {
    const wrapper = createWrapper({
      timelineEvents: [{ id: 'e1', timestamp: 'not-a-date', attack_stage: 'execution', event_type: 'process_start', severity: 'high' }],
    })
    expect(wrapper.find('.ae-timestamp').text()).toBe('--:--:--')
  })
})

// ======================================================================
// 字段提取
// ======================================================================
describe('Field Extraction', () => {
  it('extracts process_name and PID for process_start', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.ae-primary').text()).toBe('LsaIso.exe (PID 1088)')
  })

  it('extracts IP:port for network_outbound', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[1]] })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.ae-primary').text()).toBe('1.2.3.4:443')
    expect(wrapper.find('.ae-secondary').text()).toBe('← ToDesk.exe')
  })

  it('extracts registry key for registry_modify', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[2]] })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.ae-primary').text()).toContain('HKLM')
    expect(wrapper.find('.ae-primary').text()).toContain('MalService')
  })

  it('extracts file path for file_create', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[3]] })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.ae-primary').text()).toBe('C:\\Windows\\System32\\malicious.dll')
  })

  it('extracts domain for dns_query with process name', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[4]] })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.ae-primary').text()).toBe('evil.example.com')
    expect(wrapper.find('.ae-secondary').text()).toBe('← svchost.exe')
  })

  it('process_start shows fallback when no process_name', () => {
    const wrapper = createWrapper({
      timelineEvents: [{ id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high', timestamp: '2026-07-24T14:32:15Z' }],
    })
    expect(wrapper.find('.ae-primary').text()).toBeTruthy() // should not crash
  })

  it('handles null evidence gracefully', () => {
    const wrapper = createWrapper({
      timelineEvents: [{ id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high', timestamp: '2026-07-24T14:32:15Z', evidence: null }],
    })
    expect(wrapper.find('.ae-primary').exists()).toBe(true)
  })
})

// ======================================================================
// 当前事件高亮 + 自动滚动
// ======================================================================
describe('Current Event Highlight', () => {
  it('highlights current event with at-event-current class', () => {
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

  it('does not highlight any event when currentEventId is empty', () => {
    const wrapper = createWrapper({
      timelineEvents: [sampleEvents[0]],
      currentEventId: '',
      currentStage: 'execution',
    })
    expect(wrapper.find('.at-event-current').exists()).toBe(false)
  })

  it('auto-expands the stage when currentEventId changes after mount', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify', severity: 'medium' },
      ],
      // currentEventId 初始为空，稍后通过 setProps 触发变更
      currentEventId: '',
      currentStage: '',
    })
    await wrapper.vm.$nextTick()

    // 初始时所有 stage 折叠
    expect(wrapper.find('.at-stage-expanded').exists()).toBe(false)

    // 设置 currentEventId → 触发 watcher → 自动展开对应阶段
    await wrapper.setProps({ currentEventId: 'e2' })
    await wrapper.vm.$nextTick()

    // persistence（索引 1）应自动展开
    const stages = wrapper.findAll('.at-stage')
    expect(stages[1].classes()).toContain('at-stage-expanded')
  })
})

// ======================================================================
// 事件截断（>50 条）
// ======================================================================
describe('Event Truncation', () => {
  function generateEvents(count, stage = 'execution') {
    return Array.from({ length: count }, (_, i) => ({
      id: `evt_${i}`,
      timestamp: '2026-07-24T14:00:00Z',
      event_type: 'process_start',
      severity: 'high',
      attack_stage: stage,
    }))
  }

  it('shows all events when count <= 50', async () => {
    const events = generateEvents(3)
    const wrapper = createWrapper({ timelineEvents: events })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.at-event-item').length).toBe(3)
    expect(wrapper.find('.at-show-all').exists()).toBe(false)
  })

  it('shows only 50 events when count > 50', async () => {
    const events = generateEvents(60)
    const wrapper = createWrapper({ timelineEvents: events })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.at-event-item').length).toBe(50)
  })

  it('shows "显示全部" button when count > 50', async () => {
    const events = generateEvents(60)
    const wrapper = createWrapper({ timelineEvents: events })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    const showAll = wrapper.find('.at-show-all')
    expect(showAll.exists()).toBe(true)
    expect(showAll.text()).toContain('显示全部')
    expect(showAll.text()).toContain('60')
  })

  it('shows all events after clicking "显示全部"', async () => {
    const events = generateEvents(55)
    const wrapper = createWrapper({ timelineEvents: events })
    await wrapper.vm.$nextTick()
    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.at-event-item').length).toBe(50)

    await wrapper.find('.at-show-all').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.at-event-item').length).toBe(55)
  })
})

// ======================================================================
// 阶段间箭头（P1）
// ======================================================================
describe('Stage Arrows (P1)', () => {
  it('shows arrow between expanded stages', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify', severity: 'medium' },
      ],
      currentStage: 'execution', // execution auto-expands
    })
    await wrapper.vm.$nextTick()

    // Expand persistence too
    const headers = wrapper.findAll('.at-stage-header')
    await headers[1].trigger('click')
    await wrapper.vm.$nextTick()

    // Arrow should appear between execution and persistence (both expanded)
    const arrows = wrapper.findAll('.at-stage-arrow')
    expect(arrows.length).toBe(1)
    expect(arrows[0].find('.at-arrow-line').exists()).toBe(true)
    expect(arrows[0].find('.at-arrow-head').exists()).toBe(true)
  })

  it('does not show arrow when previous stage is collapsed', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify', severity: 'medium' },
      ],
      currentStage: '',
    })
    await wrapper.vm.$nextTick()

    // 展开第二个阶段（persistence），不展开第一个（execution）
    const headers = wrapper.findAll('.at-stage-header')
    await headers[1].trigger('click') // persistence 展开
    await wrapper.vm.$nextTick()

    // persistence(si=1) 前的箭头检查 expandedStages['execution'] → false → 无箭头
    const arrows = wrapper.findAll('.at-stage-arrow')
    expect(arrows.length).toBe(0)
  })

  it('shows arrow before a stage when the previous stage is expanded', async () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', attack_stage: 'persistence', event_type: 'registry_modify', severity: 'medium' },
        { id: 'e3', attack_stage: 'exfiltration', event_type: 'network_outbound', severity: 'high' },
      ],
      currentStage: '',
    })
    await wrapper.vm.$nextTick()

    // 展开第一个（execution）和第二个（persistence），折叠第三个（exfiltration）
    const headers = wrapper.findAll('.at-stage-header')
    await headers[0].trigger('click') // execution 展开
    await headers[1].trigger('click') // persistence 展开
    await wrapper.vm.$nextTick()

    // execution(展开) → 箭头 → persistence(展开) → 无箭头 → exfiltration(折叠)
    // 箭头检查前一个 stage 是否展开：persistence(si=1) 前 execution 展开 → 有箭头
    // exfiltration(si=2) 前 persistence 展开 → 也有箭头
    const arrows = wrapper.findAll('.at-stage-arrow')
    expect(arrows.length).toBe(2)
  })

  it('does not show arrow before the first stage', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
      ],
      currentStage: 'execution',
    })
    expect(wrapper.find('.at-stage-arrow').exists()).toBe(false)
  })
})

// ======================================================================
// 折叠摘要
// ======================================================================
describe('Collapsed Summary', () => {
  it('shows summary lines when stage is collapsed', () => {
    const wrapper = createWrapper({
      timelineEvents: [sampleEvents[0]],
      // no currentStage → stage is collapsed by default
    })
    expect(wrapper.find('.at-stage-summary').exists()).toBe(true)
    expect(wrapper.findAll('.at-summary-line').length).toBe(1)
  })

  it('hides summary when stage is expanded', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()

    await wrapper.find('.at-stage-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.at-stage-summary').exists()).toBe(false)
  })

  it('shows at most 3 summary lines for collapsed stage', () => {
    const events = Array.from({ length: 5 }, (_, i) => ({
      id: `e${i}`, attack_stage: 'execution', event_type: 'process_start', severity: 'high', timestamp: '2026-07-24T14:32:15Z',
    }))
    const wrapper = createWrapper({ timelineEvents: events })
    expect(wrapper.findAll('.at-summary-line').length).toBe(3)
  })

  it('applies severity color class to summary lines', () => {
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', attack_stage: 'execution', event_type: 'process_start', severity: 'high', timestamp: '2026-07-24T14:32:15Z' },
        { id: 'e2', attack_stage: 'execution', event_type: 'network_outbound', severity: 'medium', timestamp: '2026-07-24T14:32:18Z' },
      ],
    })
    const lines = wrapper.findAll('.at-summary-line')
    expect(lines[0].classes()).toContain('at-summary-danger')
    expect(lines[1].classes()).toContain('at-summary-warn')
  })
})

// ======================================================================
// 时间跨度统计
// ======================================================================
describe('Time Span Summary', () => {
  it('shows summary stats when events exist', () => {
    const wrapper = createWrapper({ timelineEvents: sampleEvents.slice(0, 2) })
    expect(wrapper.find('.at-summary').exists()).toBe(true)
    expect(wrapper.find('.at-summary-title').text()).toBe('时间跨度统计')
  })

  it('shows first and last event times', () => {
    // UTC 时间 00:00:00Z → CST (UTC+8) 本地 08:00
    // UTC 时间 02:30:00Z → CST (UTC+8) 本地 10:30
    const wrapper = createWrapper({
      timelineEvents: [
        { id: 'e1', timestamp: '2026-07-24T00:00:00Z', attack_stage: 'execution', event_type: 'process_start', severity: 'high' },
        { id: 'e2', timestamp: '2026-07-24T02:30:00Z', attack_stage: 'execution', event_type: 'process_terminate', severity: 'info' },
      ],
    })
    const cells = wrapper.findAll('.at-summary-cell')
    // Cell 1: first event time
    expect(cells[0].find('.asc-value').text()).toContain('08:00')
    // Cell 2: last event time
    expect(cells[1].find('.asc-value').text()).toContain('10:30')
  })

  it('shows stages count and total event count', () => {
    const wrapper = createWrapper({ timelineEvents: sampleEvents.slice(0, 3) })
    const cells = wrapper.findAll('.at-summary-cell')
    // Cell 3: stages with events / total stages
    expect(cells[2].find('.asc-value').text()).toBe('2 / 12')
    // Cell 4: total events
    expect(cells[3].find('.asc-value').text()).toBe('3')
  })

  it('does not show summary when no events', () => {
    const wrapper = createWrapper({ timelineEvents: [] })
    expect(wrapper.find('.at-summary').exists()).toBe(false)
  })
})

// ======================================================================
// Props reactivity
// ======================================================================
describe('Props Reactivity', () => {
  it('reacts to timelineEvents prop change', async () => {
    const wrapper = createWrapper({ timelineEvents: [] })
    expect(wrapper.find('.at-empty').exists()).toBe(true)

    await wrapper.setProps({ timelineEvents: [sampleEvents[0]] })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.at-empty').exists()).toBe(false)
    expect(wrapper.find('.at-stages').exists()).toBe(true)
  })

  it('reacts to error prop change', async () => {
    const wrapper = createWrapper({ timelineEvents: [sampleEvents[0]] })
    expect(wrapper.find('.at-error').exists()).toBe(false)

    await wrapper.setProps({ error: 'New error' })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.at-error').exists()).toBe(true)
  })

  it('reacts to loading prop change', async () => {
    const wrapper = createWrapper({ timelineEvents: [] })
    expect(wrapper.find('.at-loading').exists()).toBe(false)

    await wrapper.setProps({ loading: true })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.at-loading').exists()).toBe(true)
  })
})
