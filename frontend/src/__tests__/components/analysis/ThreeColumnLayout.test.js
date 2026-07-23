import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ThreeColumnLayout from '@/components/analysis/ThreeColumnLayout.vue'

describe('ThreeColumnLayout.vue', () => {
  let wrapper

  beforeEach(() => {
    // Reset window.innerWidth to desktop size
    window.innerWidth = 1400
    window.dispatchEvent = vi.fn()
  })

  function createWrapper(props = {}, slots = {}) {
    return mount(ThreeColumnLayout, {
      props: {
        responsiveBreakpoint: 1200,
        ...props,
      },
      slots: {
        left: slots.left || '<div class="test-left">Left Content</div>',
        center: slots.center || '<div class="test-center">Center Content</div>',
        right: slots.right || '<div class="test-right">Right Content</div>',
        ...slots,
      },
      attachTo: document.body,
    })
  }

  it('renders three columns with slots content', () => {
    wrapper = createWrapper()
    expect(wrapper.find('.tcl-left').exists()).toBe(true)
    expect(wrapper.find('.tcl-center').exists()).toBe(true)
    expect(wrapper.find('.tcl-right').exists()).toBe(true)
    expect(wrapper.find('.test-left').exists()).toBe(true)
    expect(wrapper.find('.test-center').exists()).toBe(true)
    expect(wrapper.find('.test-right').exists()).toBe(true)
  })

  it('renders slot content when provided', () => {
    wrapper = createWrapper({}, {
      left: '<span class="custom-left">Custom Left</span>',
      center: '<span class="custom-center">Custom Center</span>',
    })
    expect(wrapper.find('.custom-left').text()).toBe('Custom Left')
    expect(wrapper.find('.custom-center').text()).toBe('Custom Center')
  })

  it('shows mobile toolbar when isNarrow is true', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    // Wait for onMounted to check width
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.tcl-mobile-bar').exists()).toBe(true)
    expect(wrapper.find('.tcl-mobile-bar').isVisible()).toBe(true)
  })

  it('hides mobile toolbar when isNarrow is false (wide screen)', async () => {
    window.innerWidth = 1400
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()
    // Mobile bar uses v-if="isNarrow", so it's removed from DOM when wide
    expect(wrapper.find('.tcl-mobile-bar').exists()).toBe(false)
    expect(wrapper.vm.isNarrow).toBe(false)
  })

  it('opens left overlay on mobile when left button is clicked', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    const leftBtn = wrapper.findAll('.tcl-mobile-btn').at(0)
    await leftBtn.trigger('click')

    expect(wrapper.vm.showLeftOverlay).toBe(true)
    expect(wrapper.find('.tcl-left.tcl-overlay-visible').exists()).toBe(true)
  })

  it('opens right overlay on mobile when right button is clicked', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    const rightBtn = wrapper.findAll('.tcl-mobile-btn').at(-1)
    await rightBtn.trigger('click')

    expect(wrapper.vm.showRightOverlay).toBe(true)
    expect(wrapper.find('.tcl-right.tcl-overlay-visible').exists()).toBe(true)
  })

  it('closes left overlay when close button is clicked', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    wrapper.vm.openLeft()
    await wrapper.vm.$nextTick()

    const closeBtn = wrapper.find('.tcl-toggle-left')
    expect(closeBtn.exists()).toBe(true)

    await closeBtn.trigger('click')
    expect(wrapper.vm.showLeftOverlay).toBe(false)
  })

  it('closes right overlay when close button is clicked', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    wrapper.vm.openRight()
    await wrapper.vm.$nextTick()

    const closeBtn = wrapper.find('.tcl-toggle-right')
    expect(closeBtn.exists()).toBe(true)

    await closeBtn.trigger('click')
    expect(wrapper.vm.showRightOverlay).toBe(false)
  })

  it('closes left overlay when overlay mask is clicked', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    wrapper.vm.openLeft()
    await wrapper.vm.$nextTick()

    const overlay = wrapper.findAll('.tcl-overlay').at(0)
    await overlay.trigger('click')

    expect(wrapper.vm.showLeftOverlay).toBe(false)
  })

  it('closes right overlay when overlay mask is clicked', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    wrapper.vm.openRight()
    await wrapper.vm.$nextTick()

    // There are two overlays; get the last one (right overlay)
    const overlays = wrapper.findAll('.tcl-overlay')
    await overlays[overlays.length - 1].trigger('click')

    expect(wrapper.vm.showRightOverlay).toBe(false)
  })

  it('resets overlays when window is resized to wide', async () => {
    window.innerWidth = 800
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    wrapper.vm.showLeftOverlay = true
    wrapper.vm.showRightOverlay = true
    await wrapper.vm.$nextTick()

    // Simulate resize to wide
    window.innerWidth = 1400
    wrapper.vm.checkWidth()
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.isNarrow).toBe(false)
    expect(wrapper.vm.showLeftOverlay).toBe(false)
    expect(wrapper.vm.showRightOverlay).toBe(false)
  })

  it('does not show close buttons when overlay is not visible', async () => {
    window.innerWidth = 1400
    wrapper = createWrapper()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.tcl-toggle-btn').exists()).toBe(false)
  })

  it('responds to responsiveBreakpoint prop', async () => {
    window.innerWidth = 1100
    wrapper = createWrapper({ responsiveBreakpoint: 1050 })
    await wrapper.vm.$nextTick()

    // 1100 > 1050, so not narrow
    expect(wrapper.vm.isNarrow).toBe(false)
  })

  it('accepts custom responsiveBreakpoint', async () => {
    window.innerWidth = 1100
    wrapper = createWrapper({ responsiveBreakpoint: 1200 })
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.isNarrow).toBe(true)
  })
})
