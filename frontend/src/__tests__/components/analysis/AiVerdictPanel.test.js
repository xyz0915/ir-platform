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
    expect(wrapper.find('.verdict-badge').text()).toBe('AI 优先推荐')
    expect(wrapper.find('.vlabel-recommended').exists()).toBe(true)
  })

  it('renders suspicious verdict label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 65 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('可疑')
    expect(wrapper.find('.vlabel-suspicious').exists()).toBe(true)
  })

  it('renders false_positive verdict label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'false_positive', confidence: 90 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('误报')
    expect(wrapper.find('.vlabel-false_positive').exists()).toBe(true)
  })

  it('renders benign verdict label', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'benign', confidence: 95 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('良性')
    expect(wrapper.find('.vlabel-benign').exists()).toBe(true)
  })

  it('renders unknown verdict label when label is unrecognized', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'unknown', confidence: 0 },
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('未知/降级')
    expect(wrapper.find('.vlabel-unknown').exists()).toBe(true)
  })

  it('renders suspicious fallback label when no verdict data', () => {
    const wrapper = createWrapper({ aiVerdict: null })
    expect(wrapper.find('.verdict-badge').text()).toBe('可疑')
    expect(wrapper.find('.vlabel-suspicious').exists()).toBe(true)
  })

  it('applies correct class based on verdict', () => {
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
    expect(wrapper.find('.avp-confidence').text()).toContain('85%')
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
  it('shows MITRE technique tags when t_code is provided', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'recommended', confidence: 85, t_code: 'T1059.001,T1547' },
    })
    const tags = wrapper.findAll('.avp-mitre-tag')
    expect(tags.length).toBe(2)
    expect(tags[0].text()).toBe('T1059.001')
    expect(tags[1].text()).toBe('T1547')
  })

  it('shows fallback MITRE tags when no t_code', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70 },
    })
    const tags = wrapper.findAll('.avp-mitre-tag')
    expect(tags.length).toBe(0)
  })

  // ── Reason ──
  it('shows reason text when provided', () => {
    const wrapper = createWrapper({
      aiVerdict: { label: 'suspicious', confidence: 70, reason: 'Suspicious network behavior detected' },
    })
    expect(wrapper.find('.avp-val').text()).toBe('Suspicious network behavior detected')
  })

  it('shows fallback reason when no reason provided', () => {
    const wrapper = createWrapper({ aiVerdict: null })
    expect(wrapper.find('.avp-val').text()).toContain('AI 研判暂不可用')
  })

  // ── Verdict as JSON string ──
  it('parses aiVerdict when passed as JSON string', () => {
    const wrapper = createWrapper({
      aiVerdict: JSON.stringify({ label: 'recommended', confidence: 92 }),
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('AI 优先推荐')
    expect(wrapper.find('.vlabel-recommended').exists()).toBe(true)
    expect(wrapper.find('.high-c').exists()).toBe(true)
  })

  it('handles invalid JSON string gracefully', () => {
    const wrapper = createWrapper({
      aiVerdict: '{ broken json',
    })
    expect(wrapper.find('.verdict-badge').text()).toBe('可疑')
  })

  // ── Empty/null verdict ──
  it('renders full UI when aiVerdict is null (fallback mode)', () => {
    const wrapper = createWrapper({ aiVerdict: null })
    expect(wrapper.find('.ai-verdict-panel').exists()).toBe(true)
    expect(wrapper.find('.verdict-badge').text()).toBe('可疑')
    expect(wrapper.find('.avp-confidence').text()).toContain('85%')
  })
})
