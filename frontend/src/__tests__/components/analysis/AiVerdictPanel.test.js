import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AiVerdictPanel from '@/components/analysis/AiVerdictPanel.vue'

describe('AiVerdictPanel.vue', () => {
  function createWrapper(props = {}) {
    return mount(AiVerdictPanel, {
      props: {
        aiVerdict: null,
        aiAnalysis: '',
        ...props,
      },
    })
  }

  // ── Verdict Label Rendering ──
  it('renders recommended verdict label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('🤖 AI 优先推荐')
    expect(wrapper.find('.vlabel-recommended').exists()).toBe(true)
  })

  it('renders suspicious verdict label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 65 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('🟡 可疑·待复核')
    expect(wrapper.find('.vlabel-suspicious').exists()).toBe(true)
  })

  it('renders false_positive verdict label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'false_positive', confidence: 90 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('⚪ 误报')
    expect(wrapper.find('.vlabel-false_positive').exists()).toBe(true)
  })

  it('renders benign verdict label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'benign', confidence: 95 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('🟢 良性')
    expect(wrapper.find('.vlabel-benign').exists()).toBe(true)
  })

  it('renders unknown verdict label when label is unrecognized', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'unknown', confidence: 0 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('⚫ 未知/降级')
    expect(wrapper.find('.vlabel-unknown').exists()).toBe(true)
  })

  it('renders fallback label when no verdict data', () => {
    const wrapper = createWrapper({ aiVerdict: null })
    expect(wrapper.find('.verdict-badge').text()).toBe('🤖 AI 研判')
    expect(wrapper.find('.vlabel-unknown').exists()).toBe(true)
  })

  it('applies correct border-left class based on verdict', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
    })
    expect(wrapper.find('.vl-suspicious').exists()).toBe(true)
  })

  // ── Confidence Display ──
  it('shows confidence percentage', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85 },
    })
    expect(wrapper.find('.avp-val').text()).toBe('85%')
  })

  it('applies high confidence class (>= 80)', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85 },
    })
    expect(wrapper.find('.high-c').exists()).toBe(true)
    expect(wrapper.find('.mid-c').exists()).toBe(false)
  })

  it('applies mid confidence class (60-79)', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 65 },
    })
    expect(wrapper.find('.mid-c').exists()).toBe(true)
    expect(wrapper.find('.high-c').exists()).toBe(false)
  })

  it('does not apply special confidence class for low confidence', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 30 },
    })
    expect(wrapper.find('.high-c').exists()).toBe(false)
    expect(wrapper.find('.mid-c').exists()).toBe(false)
  })

  // ── MITRE Technique ──
  it('shows MITRE technique code when provided', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85, t_code: 'T1059.001' },
    })
    expect(wrapper.find('.avp-tcode').exists()).toBe(true)
    expect(wrapper.find('.avp-tcode').text()).toBe('T1059.001')
  })

  it('hides MITRE technique when not provided', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85 },
    })
    expect(wrapper.find('.avp-tcode').exists()).toBe(false)
  })

  // ── Attack Type ──
  it('shows attack type when provided', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70, attack_type: 'powershell_exec' },
    })
    const rows = wrapper.findAll('.avp-row')
    const attackTypeRow = rows.filter(r => r.find('.avp-label').text() === '攻击类型')
    expect(attackTypeRow.length).toBe(1)
    expect(attackTypeRow[0].find('.avp-val').text()).toBe('powershell_exec')
  })

  // ── Action Tag ──
  it('shows action tag with correct label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85, action: 'isolate' },
    })
    expect(wrapper.find('.avp-action-tag').exists()).toBe(true)
    expect(wrapper.find('.avp-action-tag').text()).toBe('隔离主机')
    expect(wrapper.find('.act-isolate').exists()).toBe(true)
  })

  it('shows kill_process action with correct class', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85, action: 'kill_process' },
    })
    expect(wrapper.find('.act-kill_process').exists()).toBe(true)
    expect(wrapper.find('.avp-action-tag').text()).toBe('结束进程')
  })

  it('shows review action with correct class', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70, action: 'review' },
    })
    expect(wrapper.find('.act-review').exists()).toBe(true)
    expect(wrapper.find('.avp-action-tag').text()).toBe('人工复核')
  })

  // ── Reason ──
  it('shows reason text when provided', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70, reason: 'Suspicious network behavior detected' },
    })
    const rows = wrapper.findAll('.avp-row')
    const reasonRow = rows.filter(r => r.find('.avp-label').text() === '研判理由')
    expect(reasonRow.length).toBe(1)
    expect(reasonRow[0].find('.avp-val').text()).toBe('Suspicious network behavior detected')
  })

  // ── AI Analysis Expand/Collapse ──
  it('shows AI analysis header when analysis text is provided', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
      aiAnalysis: 'This is a detailed analysis of the suspicious event...',
    })
    expect(wrapper.find('.avp-analysis-header').exists()).toBe(true)
    expect(wrapper.find('.avp-analysis-header').text()).toContain('AI 分析原文')
  })

  it('hides AI analysis section when no analysis text', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
      aiAnalysis: '',
    })
    expect(wrapper.find('.avp-analysis').exists()).toBe(false)
  })

  it('collapses analysis body by default', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
      aiAnalysis: 'Detailed analysis text...',
    })
    expect(wrapper.find('.avp-analysis-body').exists()).toBe(false)
  })

  it('expands analysis body when header is clicked', async () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
      aiAnalysis: 'Detailed analysis text...',
    })
    await wrapper.find('.avp-analysis-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.avp-analysis-body').exists()).toBe(true)
    expect(wrapper.find('.avp-analysis-body').text()).toBe('Detailed analysis text...')
  })

  it('chevron rotates when analysis is expanded', async () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
      aiAnalysis: 'Detailed analysis text...',
    })
    expect(wrapper.find('.avp-chevron-open').exists()).toBe(false)

    await wrapper.find('.avp-analysis-header').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.avp-chevron-open').exists()).toBe(true)
  })

  it('collapses analysis body when header is clicked again', async () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
      aiAnalysis: 'Detailed analysis text...',
    })
    // Click to expand
    await wrapper.find('.avp-analysis-header').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.avp-analysis-body').exists()).toBe(true)

    // Click to collapse
    await wrapper.find('.avp-analysis-header').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.avp-analysis-body').exists()).toBe(false)
  })

  // ── Verdict as JSON string ──
  it('parses aiVerdict when passed as JSON string', () => {
    const wrapper = createWrapper({
      aiVerdict: JSON.stringify({ label: 'recommended', confidence: 92 }),
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('🤖 AI 优先推荐')
    expect(wrapper.find('.vlabel-recommended').exists()).toBe(true)
    expect(wrapper.find('.high-c').exists()).toBe(true)
  })

  it('handles invalid JSON string gracefully', () => {
    const wrapper = createWrapper({
      aiVerdict: '{ broken json',
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('🤖 AI 研判')
  })

  // ── Empty/null verdict ──
  it('renders minimal UI when aiVerdict is null', () => {
    const wrapper = createWrapper({ aiVerdict: null })
    expect(wrapper.find('.ai-verdict-panel').exists()).toBe(true)
    expect(wrapper.find('.verdict-badge').text()).toBe('🤖 AI 研判')
    expect(wrapper.find('.avp-val').text()).toBe('0%')
  })
})
