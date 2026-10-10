import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HealthPayload } from '../api/types'
import HealthBadge from './HealthBadge.vue'

const ok: HealthPayload = { status: 'ok', model_busy: false }

describe('HealthBadge', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reports the healthy backend', async () => {
    const client = { health: vi.fn(async () => ok) }
    const wrapper = mount(HealthBadge, { props: { client } })
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.text()).toContain('Сервис доступен')
  })

  it('warns when the model is busy', async () => {
    const client = { health: vi.fn(async () => ({ status: 'ok', model_busy: true })) }
    const wrapper = mount(HealthBadge, { props: { client } })
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.text()).toContain('Модель занята')
  })

  it('reports connection loss and retries on the interval', async () => {
    const client = {
      health: vi
        .fn<() => Promise<HealthPayload>>()
        .mockRejectedValueOnce(new Error('down'))
        .mockResolvedValueOnce(ok),
    }
    const wrapper = mount(HealthBadge, { props: { client } })
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.text()).toContain('Нет связи')
    await vi.advanceTimersByTimeAsync(30000)
    expect(client.health).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Сервис доступен')
  })
})
