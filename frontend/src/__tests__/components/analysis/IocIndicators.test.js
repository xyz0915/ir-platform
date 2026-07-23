import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import IocIndicators from '@/components/analysis/IocIndicators.vue'

describe('IocIndicators.vue', () => {
  // Mock clipboard - use defineProperty since clipboard is read-only
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

  // ── Empty State ──
  it('does not render when totalCount is 0', () => {
    const wrapper = createWrapper({ iocs: {} })
    expect(wrapper.find('.ioc-indicators').exists()).toBe(false)
  })

  it('does not render when iocs is empty object', () => {
    const wrapper = createWrapper({ iocs: {} })
    expect(wrapper.find('.ioc-indicators').exists()).toBe(false)
  })

  it('renders when iocs have data', () => {
    const wrapper = createWrapper({
      iocs: { ips: ['192.168.1.1'] },
    })
    expect(wrapper.find('.ioc-indicators').exists()).toBe(true)
  })

  // ── Title with Count ──
  it('shows title with total IOC count', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['192.168.1.1', '10.0.0.1'],
        domains: ['malicious.com'],
      },
    })
    expect(wrapper.find('.ioc-title').text()).toBe('威胁指标 (3)')
  })

  // ── IP Indicators ──
  it('renders IP group with correct count', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['192.168.1.1', '10.0.0.1'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('🌐 IP 地址 (2)')
    expect(wrapper.findAll('.ioc-ip').length).toBe(2)
  })

  it('renders each IP chip with correct text', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['192.168.1.1', '10.0.0.1'],
      },
    })
    const chips = wrapper.findAll('.ioc-ip')
    expect(chips[0].text()).toBe('192.168.1.1')
    expect(chips[1].text()).toBe('10.0.0.1')
  })

  it('copies IP text to clipboard on click', async () => {
    const wrapper = createWrapper({
      iocs: { ips: ['192.168.1.1'] },
    })
    await wrapper.find('.ioc-ip').trigger('click')
    expect(mockWriteText).toHaveBeenCalledWith('192.168.1.1')
  })

  // ── SHA256 Indicators ──
  it('renders SHA256 group with truncated hash and VT link', () => {
    const wrapper = createWrapper({
      iocs: {
        sha256: ['abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('🔑 SHA256 (1)')
    const hashChip = wrapper.find('.ioc-hash')
    expect(hashChip.text()).toContain('abcdef1234567890...')
    expect(hashChip.find('.ioc-vt-link').exists()).toBe(true)
  })

  it('opens VT link when VT button is clicked', async () => {
    const hash = 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'
    const wrapper = createWrapper({
      iocs: { sha256: [hash] },
    })
    const vtLink = wrapper.find('.ioc-vt-link')
    await vtLink.trigger('click')
    expect(mockOpen).toHaveBeenCalledWith(
      `https://www.virustotal.com/gui/file/${hash}`,
      '_blank'
    )
  })

  it('copies full hash to clipboard on chip click', async () => {
    const hash = 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890'
    const wrapper = createWrapper({
      iocs: { sha256: [hash] },
    })
    await wrapper.find('.ioc-hash').trigger('click')
    expect(mockWriteText).toHaveBeenCalledWith(hash)
  })

  // ── Domain Indicators ──
  it('renders domain group', () => {
    const wrapper = createWrapper({
      iocs: {
        domains: ['evil.example.com', 'phishing.net'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('🌐 域名 (2)')
    expect(wrapper.findAll('.ioc-domain').length).toBe(2)
    expect(wrapper.find('.ioc-domain').text()).toBe('evil.example.com')
  })

  // ── MD5 Indicators ──
  it('renders MD5 group with truncated hash', () => {
    const wrapper = createWrapper({
      iocs: {
        md5: ['abc123def456abc123def456abc12345'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('🔏 MD5 (1)')
    expect(wrapper.find('.ioc-hash').text()).toContain('abc123def456abc1')
  })

  // ── File Paths ──
  it('renders file paths group', () => {
    const wrapper = createWrapper({
      iocs: {
        file_paths: ['C:\\Windows\\system32\\malware.exe', '/tmp/evil.sh'],
      },
    })
    expect(wrapper.find('.ioc-group-label').text()).toBe('📁 文件路径 (2)')
    expect(wrapper.findAll('.ioc-fp').length).toBe(2)
  })

  it('limits file paths to 5 and shows "+N more"', () => {
    const paths = Array.from({ length: 8 }, (_, i) => `/path/file${i}.exe`)
    const wrapper = createWrapper({
      iocs: { file_paths: paths },
    })
    expect(wrapper.findAll('.ioc-fp').length).toBe(5)
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

  // ── Computed totalCount ──
  it('calculates total count including all IOC types', () => {
    const wrapper = createWrapper({
      iocs: {
        ips: ['1.1.1.1', '2.2.2.2'],
        domains: ['evil.com'],
        md5: ['abc123'],
        sha1: ['def456'],
        sha256: ['ghi789'],
        file_paths: ['/a', '/b', '/c'],
      },
    })
    // 2 + 1 + 1 + 1 + 1 + 3 = 9
    expect(wrapper.find('.ioc-title').text()).toBe('威胁指标 (9)')
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
