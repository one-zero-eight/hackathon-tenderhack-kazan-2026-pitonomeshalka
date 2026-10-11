import { afterEach, describe, expect, it, vi } from 'vitest'
import { mountWithPrime } from '../test/mount'
import SearchHistory from './SearchHistory.vue'

const LONG_QUERY = 'Аккумуляторная дрель 18 В с реверсом и двумя батареями для монтажных работ'
const TOOLTIP_DELAY_MS = 700

afterEach(() => {
  vi.useRealTimers()
  document.querySelectorAll('.p-tooltip').forEach((tooltip) => tooltip.remove())
})

describe('SearchHistory', () => {
  it('renders nothing without previous queries', () => {
    const wrapper = mountWithPrime(SearchHistory, { props: { queries: [] } })
    expect(wrapper.text()).toBe('')
  })

  it('emits the full query when a truncated history button is selected', async () => {
    const wrapper = mountWithPrime(SearchHistory, { props: { queries: [LONG_QUERY] } })
    const button = wrapper.get('button')

    expect(button.text()).toBe(`${LONG_QUERY.slice(0, 50)}…`)
    await button.trigger('click')

    expect(wrapper.emitted('select')?.[0]).toEqual([LONG_QUERY])
  })

  it('shows a long-query tooltip only after the hover delay', async () => {
    vi.useFakeTimers()
    const wrapper = mountWithPrime(SearchHistory, { props: { queries: [LONG_QUERY] } })

    await wrapper.get('button').trigger('mouseenter')
    await vi.advanceTimersByTimeAsync(TOOLTIP_DELAY_MS - 1)
    expect(document.body.querySelector('.p-tooltip-text')).toBeNull()

    await vi.advanceTimersByTimeAsync(1)
    expect(document.body.querySelector('.p-tooltip-text')?.textContent).toBe(LONG_QUERY)
    wrapper.unmount()
  })

  it('does not create a tooltip for a query that fits in the button', async () => {
    vi.useFakeTimers()
    const wrapper = mountWithPrime(SearchHistory, { props: { queries: ['Дрель 18 В'] } })

    await wrapper.get('button').trigger('mouseenter')
    await vi.advanceTimersByTimeAsync(TOOLTIP_DELAY_MS)

    expect(document.body.querySelector('.p-tooltip-text')).toBeNull()
    wrapper.unmount()
  })
})
