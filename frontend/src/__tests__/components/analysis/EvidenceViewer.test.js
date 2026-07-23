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

  // ── Fallback Data (when no evidence) ──
  it('renders fallback normalized data when no evidenceViews', () => {
    const wrapper = createWrapper()
    expect(wrapper.find('.ev-normalized-content').exists()).toBe(true)
    expect(wrapper.find('.ev-norm-key').exists()).toBe(true)
  })

  // ── Title ──
  it('renders title', () => {
    const wrapper = createWrapper({
      evidenceViews: { normalized: { key: 'value' }, raw: { key: 'value' }, raw_source: 'sysmon' },
    })
    expect(wrapper.find('.ev-title').text()).toBe('证据详情')
  })

  // ── Normalized View ──
  it('shows normalized view by default with real data', () => {
    const wrapper = createWrapper({
      evidenceViews: { normalized: { event_id: '123', process: 'explorer.exe' } },
    })
    expect(wrapper.find('.ev-normalized-content').exists()).toBe(true)
    expect(wrapper.find('.ev-norm-key').exists()).toBe(true)
  })

  it('displays normalized fields from evidenceViews', () => {
    const wrapper = createWrapper({
      evidenceViews: { normalized: { event_id: '123' } },
    })
    expect(wrapper.find('.ev-normalized-content').text()).toContain('event_id')
    expect(wrapper.find('.ev-normalized-content').text()).toContain('123')
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

    expect(wrapper.vm.mode).toBe('normalized')

    await wrapper.find('.ev-toggle').trigger('click')
    expect(wrapper.vm.mode).toBe('raw')

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
  it('shows process subject section when processSubject prop is provided', () => {
    const wrapper = createWrapper({
      eventType: 'process_start',
      processSubject: { name: 'powershell.exe', pid: '1234' },
    })
    expect(wrapper.find('.ev-sub-title').text()).toBe('进程主体')
  })

  it('shows process subject regardless of eventType', () => {
    const wrapper = createWrapper({
      eventType: 'network_outbound',
      processSubject: { name: 'powershell.exe', pid: '1234' },
    })
    expect(wrapper.find('.ev-adaptive').exists()).toBe(true)
  })

  // ── Network Subject ──
  it('shows network subject section when networkSubject prop is provided', () => {
    const wrapper = createWrapper({
      eventType: 'network_outbound',
      networkSubject: { src_ip: '10.0.0.1', dst_ip: '1.2.3.4', dst_port: '443' },
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

  // ── Combined: evidence views + adaptive subjects ──
  it('renders both evidence views and adaptive subjects together', () => {
    const wrapper = createWrapper({
      evidenceViews: { normalized: { cmdline: 'powershell -enc ...' } },
      eventType: 'process_start',
      processSubject: { name: 'powershell.exe', pid: '1234' },
    })
    expect(wrapper.find('.ev-normalized-content').exists()).toBe(true)
    expect(wrapper.find('.ev-sub-title').exists()).toBe(true)
  })
})
