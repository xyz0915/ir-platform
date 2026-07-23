import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import IocIndicators from '@/components/analysis/IocIndicators.vue'

describe('IocIndicators.vue', () => {
  // Mock clipboard
  const mockWriteText = vi.fn(() => Promise.resolve())
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: mockWriteText },
    writable: true,
    configurable: true,
  })

  // Mock window.open
  const mockOpen = vi.fn()
  window.open = mockOpen

  function createWrapper(props = {}) {
    return mount(IocIndicators, {
      props: {
        iocs: {},
        ...props,
      },
    })
  }

  // ── Fallback State ──
  it('renders fallback IOC items when iocs is empty', () => {
    const wrapper = createWrapper({ iocs: {} })
    expect(wrapper.find('.ioc-indicators').exists()).toBe(true)
    expect(wrapper.findAll('.ioc-item').length).toBe(4) // 4 fallback items
  })

  it('renders real IOC data when available', () => {
    const wrapper = createWrapper({
      iocs: { ips: ['192.168.1.1'] },
    })
    expect(wrapper.find('.ioc-indicators').exists()).toBe(true)
    expect(wrapper.findAll('.ioc-group').length).toBe(1)
  })

  // ── Title ──
  it('shows title', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['192.168.1.1', '10.0.0.1'],
        domains: ['malicious.com'],
      },
    })
    expect(wrapper.find('.ioc-title').text()).toBe('威胁指标 (IOC)')
  })

  // ── IP Indicators ──
  it('renders IP group with correct count', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['192.168.1.1', '10.0.0.1'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('IP 地址 (2)')
    expect(wrapper.findAll('.ioc-item').length).toBe(2)
  })

  it('copies IP text to clipboard on copy button click', async () => {
    const wrapper = createWrapper({
      iocs: { ips: ['192.168.1.1'] },
    })
    const copyBtn = wrapper.find('.ioc-action-btn')
    await copyBtn.trigger('click')
    expect(mockWriteText).toHaveBeenCalledWith('192.168.1.1')
  })

  // ── SHA256 Indicators ──
  it('renders SHA256 group with truncated hash and VT button', () => {
    const hash = 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'
    const wrapper = createWrapper({
      iocs: {
        sha256: [hash],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('文件哈希 (1)')
    expect(wrapper.find('.ioc-vt-btn').exists()).toBe(true)
  })

  it('opens VT link when VT button is clicked', async () => {
    const hash = 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'
    const wrapper = createWrapper({
      iocs: { sha256: [hash] },
    })
    const vtBtn = wrapper.find('.ioc-vt-btn')
    await vtBtn.trigger('click')
    expect(mockOpen).toHaveBeenCalledWith(
      `https://www.virustotal.com/gui/file/${hash}`,
      '_blank'
    )
  })

  it('copies full hash to clipboard on copy button click', async () => {
    const hash = 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'
    const wrapper = createWrapper({
      iocs: { sha256: [hash] },
    })
    const copyBtn = wrapper.find('.ioc-action-btn')
    await copyBtn.trigger('click')
    expect(mockWriteText).toHaveBeenCalledWith(hash)
  })

  // ── Domain Indicators ──
  it('renders domain group', () => {
    const wrapper = createWrapper({
      iocs: {
        domains: ['evil.example.com', 'phishing.net'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('域名 (2)')
    expect(wrapper.findAll('.ioc-item').length).toBe(2)
  })

  // ── File Paths ──
  it('renders file paths group', () => {
    const wrapper = createWrapper({
      iocs: {
        file_paths: ['C:\\Windows\\system32\\malware.exe', '/tmp/evil.sh'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('文件路径 (2)')
  })

  it('limits file paths to 5 and shows "+N more"', () => {
    const paths = Array.from({ length: 8 }, (_, i) => `/path/file${i}.exe`)
    const wrapper = createWrapper({
      iocs: { file_paths: paths },
    })
    expect(wrapper.findAll('.ioc-item').length).toBe(5)
    expect(wrapper.find('.ioc-more').text()).toBe('+3 更多')
  })

  it('does not show "+N more" when file paths <= 5', () => {
    const paths = Array.from({ length: 3 }, (_, i) => `/path/file${i}.exe`)
    const wrapper = createWrapper({
      iocs: { file_paths: paths },
    })
    expect(wrapper.find('.ioc-more').exists()).toBe(false)
  })

  // ── Multiple Groups ──
  it('renders multiple IOC groups simultaneously', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['192.168.1.1'],
        domains: ['evil.com'],
        sha256: ['abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'],
      },
    })
    expect(wrapper.findAll('.ioc-group').length).toBe(3)
  })

  // ── Empty Sub-groups ──
  it('does not render group sections for empty arrays', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['1.1.1.1'],
        domains: [],
        sha256: [],
        md5: [],
        file_paths: [],
      },
    })
    expect(wrapper.findAll('.ioc-group').length).toBe(1) // only IP group
  })
})
