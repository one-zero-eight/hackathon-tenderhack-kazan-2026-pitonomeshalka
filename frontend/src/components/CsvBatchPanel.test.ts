import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import { mountWithPrime } from '../test/mount'
import CsvBatchPanel from './CsvBatchPanel.vue'

const csv = 'id;наименование\n1;аккумуляторная дрель\n2;садовый насос\n3;   \n'

const analysisFor = (text: string): AnalysisResponse => ({
  run_id: `run-${text}`,
  status: 'ready_for_review',
  complete_inference: true,
  recommended_candidate: `${text}@v`,
  properties: [],
  candidates: [],
  clarifying_question: null,
  warnings: [],
})

async function pickFile(wrapper: Awaited<ReturnType<typeof mountWithPrime>>, content = csv) {
  const file = new File([content], 'rows.csv', { type: 'text/csv' })
  const input = wrapper.find('[data-test="file-input"]').element as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await wrapper.find('[data-test="file-input"]').trigger('change')
  await flushPromises()
}

describe('CsvBatchPanel', () => {
  it('previews the parsed table with the guessed query column', async () => {
    const wrapper = mountWithPrime(CsvBatchPanel, {
      props: {
        analyze: async (text: string) => analysisFor(text),
        correct: async () => null,
      },
    })
    await pickFile(wrapper)
    expect(wrapper.text()).toContain('rows.csv')
    expect(wrapper.text()).toContain('наименование')
    expect(wrapper.text()).toContain('аккумуляторная дрель')
    const select = wrapper.find('[data-test="column"]').element as HTMLSelectElement
    expect(select.value).toBe('1')
  })

  it('streams finished rows into the accordion list', async () => {
    const analyze = vi.fn(async (text: string) => analysisFor(text))
    const wrapper = mountWithPrime(CsvBatchPanel, {
      props: { analyze, correct: async () => null },
    })
    await pickFile(wrapper)
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(analyze).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('аккумуляторная дрель@v')
    expect(wrapper.text()).toContain('садовый насос@v')
    expect(wrapper.text()).toContain('Проверено 2 из 2')
  })

  it('runs spell correction before the search', async () => {
    const analyze = vi.fn(async (text: string) => analysisFor(text))
    const correct = vi.fn(async (text: string) => `${text} 18 В`)
    const wrapper = mountWithPrime(CsvBatchPanel, { props: { analyze, correct } })
    await pickFile(wrapper)
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(analyze).toHaveBeenCalledWith('аккумуляторная дрель 18 В', expect.anything())
    expect(wrapper.text()).toContain('Исправлено')
  })

  it('cancel stops the batch before the remaining rows', async () => {
    let resolve!: (value: AnalysisResponse) => void
    const analyze = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<AnalysisResponse>((res) => {
            resolve = res
          }),
      )
      .mockImplementationOnce(async (text: string) => analysisFor(text))
    const wrapper = mountWithPrime(CsvBatchPanel, {
      props: { analyze, correct: async () => null },
    })
    await pickFile(wrapper)
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="cancel"]').trigger('click')
    resolve(analysisFor('аккумуляторная дрель'))
    await flushPromises()
    await flushPromises()
    expect(analyze).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Проверено 1 из 2')
  })
})
