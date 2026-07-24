import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MatchedRulesList from '@/components/analysis/MatchedRulesList.vue'

describe('MatchedRulesList.vue', () => {
  function createWrapper(props = {}) {
    return mount(MatchedRulesList, {
      props: {
        rules: [],
        ...props,
      },
    })
  }

  // ── Empty State (shows fallback rules) ──
  it('shows fallback rules when rules is empty', () => {
    const wrapper = createWrapper({ rules: [] })
    expect(wrapper.find('.mrc-empty-hint').exists()).toBe(true)
  })

  // ── Title ──
  it('shows title with rule count when rules exist', () => {
    const wrapper = createWrapper({
      rules: [
        { rule_name: 'Rule 1', severity: 'high' },
        { rule_name: 'Rule 2', severity: 'medium' },
      ],
    })
    expect(wrapper.find('.mrc-title').text()).toBe('命中规则 (2)')
  })

  it('shows title without count when rules is empty', () => {
    const wrapper = createWrapper({ rules: [] })
    expect(wrapper.find('.mrc-title').text()).toBe('命中规则')
  })

  // ── Rule Items ──
  it('renders rule items', () => {
    const rules = [
      { rule_name: 'PowerShell Detection', severity: 'high' },
      { rule_name: 'Network Beaconing', severity: 'medium' },
    ]
    const wrapper = createWrapper({ rules })
    expect(wrapper.findAll('.mrc-rule-item').length).toBe(2)
  })

  it('renders rule name', () => {
    const wrapper = createWrapper({
      rules: [{ rule_name: 'PowerShell Detection', severity: 'high' }],
    })
    expect(wrapper.find('.mrc-rule-name').text()).toBe('PowerShell Detection')
  })

  it('falls back to rule_id when rule_name is missing', () => {
    const wrapper = createWrapper({
      rules: [{ rule_id: 'rule-001', severity: 'high' }],
    })
    expect(wrapper.find('.mrc-rule-name').text()).toBe('rule-001')
  })

  it('falls back to rule number when both rule_name and rule_id are missing', () => {
    const wrapper = createWrapper({
      rules: [{ severity: 'high' }],
    })
    expect(wrapper.find('.mrc-rule-name').text()).toBe('规则#1')
  })

  it('renders severity badge for each rule', () => {
    const wrapper = createWrapper({
      rules: [
        { rule_name: 'R1', severity: 'high' },
        { rule_name: 'R2', severity: 'medium' },
      ],
    })
    const sevs = wrapper.findAll('.mrc-rule-sev')
    expect(sevs[0].text()).toBe('high')
    expect(sevs[0].classes()).toContain('sev-high')
    expect(sevs[1].text()).toBe('medium')
    expect(sevs[1].classes()).toContain('sev-medium')
  })

  it('renders description and confidence when present', () => {
    const wrapper = createWrapper({
      rules: [{
        rule_name: 'R1', severity: 'high',
        description: 'Detects suspicious PowerShell execution',
        confidence: '0.85',
      }],
    })
    expect(wrapper.find('.mrc-rule-desc').exists()).toBe(true)
    expect(wrapper.find('.mrc-rule-desc').text()).toContain('Detects suspicious PowerShell execution')
    expect(wrapper.find('.mrc-rule-desc').text()).toContain('0.85')
  })

  // ── Show More / Less ──
  it('shows all rules when <= 3', () => {
    const rules = [
      { rule_name: 'R1', severity: 'high' },
      { rule_name: 'R2', severity: 'medium' },
    ]
    const wrapper = createWrapper({ rules })
    expect(wrapper.findAll('.mrc-rule-item').length).toBe(2)
    expect(wrapper.find('.mrc-more').exists()).toBe(false)
  })

  it('shows only 3 rules when > 3 and showAll is false', () => {
    const rules = Array.from({ length: 5 }, (_, i) => ({
      rule_name: `Rule ${i + 1}`,
      severity: 'high',
    }))
    const wrapper = createWrapper({ rules })
    expect(wrapper.findAll('.mrc-rule-item').length).toBe(3)
    expect(wrapper.find('.mrc-more').exists()).toBe(true)
    expect(wrapper.find('.mrc-more').text()).toContain('查看更多')
  })

  it('shows all rules after clicking "查看更多"', async () => {
    const rules = Array.from({ length: 5 }, (_, i) => ({
      rule_name: `Rule ${i + 1}`,
      severity: 'high',
    }))
    const wrapper = createWrapper({ rules })

    await wrapper.find('.mrc-more').trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.mrc-rule-item').length).toBe(5)
    expect(wrapper.find('.mrc-more').text()).toContain('收起')
  })

  it('toggles back to 3 rules when clicking "收起"', async () => {
    const rules = Array.from({ length: 5 }, (_, i) => ({
      rule_name: `Rule ${i + 1}`,
      severity: 'high',
    }))
    const wrapper = createWrapper({ rules })

    await wrapper.find('.mrc-more').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.mrc-rule-item').length).toBe(5)

    await wrapper.find('.mrc-more').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.mrc-rule-item').length).toBe(3)
  })
})
