import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RobotSearching from './RobotSearching.vue'

describe('RobotSearching', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the first phrase immediately', () => {
    const wrapper = mount(RobotSearching, {
      props: { phrases: ['Раз', 'Два', 'Три'] },
    })
    expect(wrapper.find('[data-test="phrase"]').text()).toBe('Раз')
  })

  it('cycles through the phrases over time', async () => {
    const wrapper = mount(RobotSearching, {
      props: { phrases: ['Раз', 'Два', 'Три'] },
    })
    await vi.advanceTimersByTimeAsync(2300)
    expect(wrapper.find('[data-test="phrase"]').text()).toBe('Два')
    await vi.advanceTimersByTimeAsync(2300)
    expect(wrapper.find('[data-test="phrase"]').text()).toBe('Три')
  })

  it('wraps back to the first phrase after the last one', async () => {
    const wrapper = mount(RobotSearching, {
      props: { phrases: ['Раз', 'Два'] },
    })
    await vi.advanceTimersByTimeAsync(4600)
    expect(wrapper.find('[data-test="phrase"]').text()).toBe('Раз')
  })

  it('clears the rotation timer on unmount', () => {
    const clearSpy = vi.spyOn(globalThis, 'clearInterval')
    const wrapper = mount(RobotSearching, { props: { phrases: ['Раз', 'Два'] } })
    wrapper.unmount()
    expect(clearSpy).toHaveBeenCalled()
    clearSpy.mockRestore()
  })
})
