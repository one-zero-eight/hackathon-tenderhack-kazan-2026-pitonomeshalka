import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RobotSearching from './RobotSearching.vue'

const eyesTransform = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.find('.robot-eyes').element as SVGElement).style.transform

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

  it('turns the eyes toward the cursor', async () => {
    const wrapper = mount(RobotSearching, { props: { phrases: ['Раз'] } })
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 200, clientY: 0 }))
    await vi.advanceTimersByTimeAsync(600)
    expect(eyesTransform(wrapper)).toBe('translate(5.00px, 0.00px)')
    wrapper.unmount()
  })

  it('returns the eyes to center when the cursor leaves the window', async () => {
    const wrapper = mount(RobotSearching, { props: { phrases: ['Раз'] } })
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 200, clientY: 0 }))
    await vi.advanceTimersByTimeAsync(600)
    document.documentElement.dispatchEvent(new MouseEvent('mouseleave'))
    await vi.advanceTimersByTimeAsync(600)
    expect(eyesTransform(wrapper)).toBe('translate(0.00px, 0.00px)')
    wrapper.unmount()
  })

  it('ignores the cursor when reduced motion is preferred', async () => {
    const matchMediaSpy = vi.spyOn(window, 'matchMedia').mockReturnValue({
      matches: true,
    } as MediaQueryList)
    const wrapper = mount(RobotSearching, { props: { phrases: ['Раз'] } })
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 200, clientY: 0 }))
    await vi.advanceTimersByTimeAsync(600)
    expect(eyesTransform(wrapper)).toBe('')
    wrapper.unmount()
    matchMediaSpy.mockRestore()
  })
})
