import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DecisionBar from '@/components/analysis/DecisionBar.vue'

describe('DecisionBar.vue', () => {
  function createWrapper(props = {}) {
    return mount(DecisionBar, {
      props: {
        event: {},
        riskScore: 0,
        ...props,
      },
    })
  }

  // ── Severity Badge ──
  it('renders severity badge with correct class for critical', () => {
    const wrapper = createWrapper({ event: { severity: 'critical' } })
    const badge = wrapper.find('.severity-badge')
    expect(badge.classes()).toContain('badge-critical')
    expect(badge.text()).toBe('critical')
  })

  it('renders severity badge with correct class for high', () => {
    const wrapper = createWrapper({ event: { severity: 'high' } })
    expect(wrapper.find('.badge-high').exists()).toBe(true)
  })

  it('renders severity badge with correct class for medium', () => {
    const wrapper = createWrapper({ event: { severity: 'medium' } })
    expect(wrapper.find('.badge-medium').exists()).toBe(true)
  })

  it('renders severity badge with correct class for low', () => {
    const wrapper = createWrapper({ event: { severity: 'low' } })
    expect(wrapper.find('.badge-low').exists()).toBe(true)
  })

  it('renders severity badge with info class by default', () => {
    const wrapper = createWrapper({ event: { severity: 'info' } })
    expect(wrapper.find('.badge-info').exists()).toBe(true)
  })

  it('renders severity badge with info class for unknown severity', () => {
    const wrapper = createWrapper({ event: {} })
    expect(wrapper.find('.badge-info').exists()).toBe(true)
    // severity is undefined so the badge text is empty; the CSS class gets 'info' as default
    expect(wrapper.find('.severity-badge').text()).toBe('')
  })

  // ── Risk Score Color ──
  it('shows risk score with correct value', () => {
    const wrapper = createWrapper({ event: {}, riskScore: 75 })
    expect(wrapper.find('.db-risk-score').text()).toBe('75')
  })

  it('applies red color for risk score >= 70', () => {
    const wrapper = createWrapper({ event: {}, riskScore: 85 })
    expect(wrapper.find('.db-risk-score').attributes('style')).toContain('color: #dc2626')
  })

  it('applies amber color for risk score >= 50 and < 70', () => {
    const wrapper = createWrapper({ event: {}, riskScore: 60 })
    expect(wrapper.find('.db-risk-score').attributes('style')).toContain('color: #d97706')
  })

  it('applies blue color for risk score >= 30 and < 50', () => {
    const wrapper = createWrapper({ event: {}, riskScore: 40 })
    expect(wrapper.find('.db-risk-score').attributes('style')).toContain('color: #2563eb')
  })

  it('applies gray color for risk score < 30', () => {
    const wrapper = createWrapper({ event: {}, riskScore: 20 })
    expect(wrapper.find('.db-risk-score').attributes('style')).toContain('color: #a3a3a3')
  })

  it('shows 0 for default risk score', () => {
    const wrapper = createWrapper({ event: {} })
    expect(wrapper.find('.db-risk-score').text()).toBe('0')
  })

  // ── Category Label ──
  it('shows category label when event has category', () => {
    const wrapper = createWrapper({ event: { category: 'process' } })
    expect(wrapper.find('.db-cat-tag').text()).toBe('进程')
  })

  it('shows raw category when not in label map', () => {
    const wrapper = createWrapper({ event: { category: 'custom_cat' } })
    expect(wrapper.find('.db-cat-tag').text()).toBe('custom_cat')
  })

  // ── ATT&CK Stage ──
  it('shows attack stage label when present', () => {
    const wrapper = createWrapper({ event: { attack_stage: 'initial_access' } })
    expect(wrapper.find('.db-stage-tag').text()).toBe('初始访问')
  })

  it('shows raw attack stage when not in label map', () => {
    const wrapper = createWrapper({ event: { attack_stage: 'custom_stage' } })
    expect(wrapper.find('.db-stage-tag').text()).toBe('custom_stage')
  })

  // ── Status Label ──
  it('shows status label with correct class for pending', () => {
    const wrapper = createWrapper({ event: { status: 'pending' } })
    const tag = wrapper.find('.db-status-tag')
    expect(tag.classes()).toContain('st-pending')
    expect(tag.text()).toBe('待处理')
  })

  it('shows status label for triaging', () => {
    const wrapper = createWrapper({ event: { status: 'triaging' } })
    expect(wrapper.find('.st-triaging').exists()).toBe(true)
    expect(wrapper.find('.db-status-tag').text()).toBe('分诊中')
  })

  it('shows status label for investigating', () => {
    const wrapper = createWrapper({ event: { status: 'investigating' } })
    expect(wrapper.find('.st-investigating').exists()).toBe(true)
    expect(wrapper.find('.db-status-tag').text()).toBe('调查中')
  })

  it('shows status label for resolved', () => {
    const wrapper = createWrapper({ event: { status: 'resolved' } })
    expect(wrapper.find('.st-resolved').exists()).toBe(true)
    expect(wrapper.find('.db-status-tag').text()).toBe('已解决')
  })

  it('shows status label for rejected', () => {
    const wrapper = createWrapper({ event: { status: 'rejected' } })
    expect(wrapper.find('.st-rejected').exists()).toBe(true)
    expect(wrapper.find('.db-status-tag').text()).toBe('已误报')
  })

  // ── Status Flow Buttons ──
  it('shows "分诊" button when status is pending', () => {
    const wrapper = createWrapper({ event: { status: 'pending' } })
    const btn = wrapper.find('.db-right-group .btn-primary')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('分诊')
  })

  it('shows "调查" button when status is triaging', () => {
    const wrapper = createWrapper({ event: { status: 'triaging' } })
    const btn = wrapper.find('.db-right-group .btn-warning')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('调查')
  })

  it('shows "解决" button when status is investigating', () => {
    const wrapper = createWrapper({ event: { status: 'investigating' } })
    const btn = wrapper.find('.db-right-group .btn-success')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('解决')
  })

  it('shows "重开" button when status is resolved', () => {
    const wrapper = createWrapper({ event: { status: 'resolved' } })
    const btn = wrapper.find('.db-right-group .btn-warning')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('重开')
  })

  it('shows "误报" button for non-rejected, non-resolved statuses', () => {
    const statuses = ['pending', 'triaging', 'investigating']
    for (const status of statuses) {
      const wrapper = createWrapper({ event: { status } })
      const btn = wrapper.findAll('.db-right-group .btn-danger')
      const rejectBtn = btn.filter(b => b.text().includes('误报'))
      expect(rejectBtn.length).toBe(1)
    }
  })

  it('hides "误报" button when status is rejected', () => {
    const wrapper = createWrapper({ event: { status: 'rejected' } })
    const btns = wrapper.findAll('.db-right-group .btn-danger')
    const rejectBtn = btns.filter(b => b.text().includes('误报'))
    expect(rejectBtn.length).toBe(0)
  })

  it('hides "误报" button when status is resolved', () => {
    const wrapper = createWrapper({ event: { status: 'resolved' } })
    const btns = wrapper.findAll('.db-right-group .btn-danger')
    const rejectBtn = btns.filter(b => b.text().includes('误报'))
    expect(rejectBtn.length).toBe(0)
  })

  // ── Status Change Emit ──
  it('emits update-status with correct status on button click', async () => {
    const wrapper = createWrapper({ event: { status: 'pending' } })
    await wrapper.find('.db-right-group .btn-primary').trigger('click')
    expect(wrapper.emitted('update-status')).toBeTruthy()
    expect(wrapper.emitted('update-status')[0]).toEqual(['triaging'])
  })

  it('emits update-status with triaging when pending->triaging', async () => {
    const wrapper = createWrapper({ event: { status: 'pending' } })
    await wrapper.find('.db-right-group .btn-primary').trigger('click')
    expect(wrapper.emitted('update-status')[0]).toEqual(['triaging'])
  })

  it('emits update-status with investigating when triaging->investigating', async () => {
    const wrapper = createWrapper({ event: { status: 'triaging' } })
    await wrapper.find('.db-right-group .btn-warning').trigger('click')
    expect(wrapper.emitted('update-status')[0]).toEqual(['investigating'])
  })

  it('emits update-status with resolved when investigating->resolved', async () => {
    const wrapper = createWrapper({ event: { status: 'investigating' } })
    await wrapper.find('.db-right-group .btn-success').trigger('click')
    expect(wrapper.emitted('update-status')[0]).toEqual(['resolved'])
  })

  it('emits update-status with rejected when clicking "误报"', async () => {
    const wrapper = createWrapper({ event: { status: 'investigating' } })
    const dangerBtn = wrapper.findAll('.db-right-group .btn-danger')
    const rejectBtn = dangerBtn.filter(b => b.text().includes('误报'))
    await rejectBtn[0].trigger('click')
    expect(wrapper.emitted('update-status')[0]).toEqual(['rejected'])
  })

  // ── Deep Investigation Button ──
  it('shows deep investigation button', () => {
    const wrapper = createWrapper({ event: { status: 'pending' } })
    const buttons = wrapper.findAll('.db-right-group .btn')
    const deepBtn = buttons.filter(b => b.text().includes('深度调查'))
    expect(deepBtn.length).toBe(1)
  })

  it('emits deep-investigation when deep investigation button is clicked', async () => {
    const wrapper = createWrapper({ event: { status: 'pending' } })
    const buttons = wrapper.findAll('.db-right-group .btn')
    const deepBtn = buttons.filter(b => b.text().includes('深度调查'))
    await deepBtn[0].trigger('click')
    expect(wrapper.emitted('deep-investigation')).toBeTruthy()
  })
})
