import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import EvidenceViewer from '@/components/analysis/EvidenceViewer.vue'

describe('EvidenceViewer.vue', () => {
  function createWrapper(props = {}) {
    return mount(EvidenceViewer, {
      props: {
        evidenceViews: null,
        eventType: '',
        processSubject: null,
        networkSubject: null,
        persistenceTarget: '',
        ...props,
      },
    })
  }

  // ── Empty State ──
  it('shows empty state when no evidence data', () => {
    const wrapper = createWrapper()
    expect(wrapper.find('.ev-empty').exists()).toBe(true)
    expect(wrapper.find('.ev-empty').text()).toBe('暂无证据数据')
  })

  // ── Title ──
  it('renders title', () => {
    const wrapper = createWrapper({
      evidenceViews: { normalized: { key: 'value' }, raw: { key: 'value' }, raw_source: 'sysmon' },
    })
    expect(wrapper.find('.ev-title').text()).toBe('证据详情')
  })

  // ── Normalized View ──
  it('shows normalized view by default', () => {
    const wrapper = createWrapper({
      evidenceViews: { normalized: { event_id: '123', process: 'explorer.exe' } },
    })
    expect(wrapper.find('.ev-json').exists()).toBe(true)
    expect(wrapper.find('.ev-json').text()).toContain('explorer.exe')
  })

  it('displays formatted JSON for normalized view', () => {
    const data = { event_id: '123', process: 'explorer.exe' }
    const wrapper = createWrapper({
      evidenceViews: { normalized: data },
    })
    const jsonText = wrapper.find('.ev-json').text()
    expect(jsonText).toContain('"event_id"')
    expect(jsonText).toContain('"explorer.exe"')
  })

  // ── Raw View Toggle ──
  it('switches to raw view when toggle button is clicked', async () => {
    const wrapper = createWrapper({
      evidenceViews: {
        normalized: { key: 'normalized' },
        raw: { raw_data: 'raw_value' },
        raw_source: 'sysmon',
      },
    })
    const toggleBtn = wrapper.find('.ev-toggle')
    await toggleBtn.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.ev-raw-src').exists()).toBe(true)
    expect(wrapper.find('.ev-raw-src').text()).toBe('来源: sysmon')
    expect(wrapper.find('.ev-json').text()).toContain('raw_value')
  })

  it('toggles between normalized and raw modes', async () => {
    const wrapper = createWrapper({
      evidenceViews: {
        normalized: { view: 'normalized' },
        raw: { view: 'raw' },
        raw_source: 'sysmon',
      },
    })

    // Initially normalized
    expect(wrapper.vm.mode).toBe('normalized')

    // Click to switch to raw
    await wrapper.find('.ev-toggle').trigger('click')
    expect(wrapper.vm.mode).toBe('raw')

    // Click to switch back to normalized
    await wrapper.find('.ev-toggle').trigger('click')
    expect(wrapper.vm.mode).toBe('normalized')
  })

  it('toggle button text changes based on mode', async () => {
    const wrapper = createWrapper({
      evidenceViews: {
        normalized: { key: 'val' },
        raw: { key: 'val' },
        raw_source: 'sysmon',
      },
    })

    expect(wrapper.find('.ev-toggle').text()).toContain('切换原始数据')
    await wrapper.find('.ev-toggle').trigger('click')
    expect(wrapper.find('.ev-toggle').text()).toContain('切换范式化视图')
  })

  // ── Process Subject ──
  // NOTE: EventType filtering happens in EventDetailView, not in EvidenceViewer.
  // EvidenceViewer renders processSubject if the prop is truthy.
  it('shows process subject section when processSubject prop is provided', () => {
    const wrapper = createWrapper({
      eventType: 'process_start',
      processSubject: { name: 'powershell.exe', pid: '1234' },
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('进程主体')
  })

  it('shows process subject regardless of eventType (filtering is at view level)', () => {
    const wrapper = createWrapper({
      eventType: 'network_outbound',
      processSubject: { name: 'powershell.exe', pid: '1234' },
    })
    // EvidenceViewer renders the adaptive section when prop is truthy
    expect(wrapper.find('.ev-adaptive').exists()).toBe(true)
  })

  it('shows process subject for ioc_match events', () => {
    const wrapper = createWrapper({
      eventType: 'ioc_match',
      processSubject: { name: 'malware.exe', pid: '5678' },
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('进程主体')
  })

  // ── Network Subject ──
  it('shows network subject section when networkSubject prop is provided', () => {
    const wrapper = createWrapper({
      eventType: 'network_outbound',
      networkSubject: { src_ip: '10.0.0.1', dst_ip: '1.2.3.4', dst_port: '443' },
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('网络主体')
  })

  it('shows network subject for dns_query events', () => {
    const wrapper = createWrapper({
      eventType: 'dns_query',
      networkSubject: { query: 'evil.com', src_ip: '10.0.0.1' },
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('网络主体')
  })

  // ── Persistence Target ──
  it('shows persistence target section when persistenceTarget prop is provided', () => {
    const wrapper = createWrapper({
      eventType: 'registry_modify',
      persistenceTarget: 'HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('持久化落点')
  })

  it('shows persistence target for persistence_register events', () => {
    const wrapper = createWrapper({
      eventType: 'persistence_register',
      persistenceTarget: 'Scheduled task: UpdateCheck',
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('持久化落点')
  })

  it('shows persistence target for scheduled_task events', () => {
    const wrapper = createWrapper({
      eventType: 'scheduled_task',
      persistenceTarget: '\\Microsoft\\Windows\\Update',
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('持久化落点')
  })

  // ── Combined: evidence views + adaptive subjects ──
  it('renders both evidence views and adaptive subjects together', () => {
    const wrapper = createWrapper({
      evidenceViews: { normalized: { cmdline: 'powershell -enc ...' } },
      eventType: 'process_start',
      processSubject: { name: 'powershell.exe', pid: '1234' },
    })
    expect(wrapper.find('.ev-json').exists()).toBe(true)
    expect(wrapper.find('.ev-sub-title').exists()).toBe(true)
  })
})
