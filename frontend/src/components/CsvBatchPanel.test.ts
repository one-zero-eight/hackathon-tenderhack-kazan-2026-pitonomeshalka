import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import { mountWithPrime } from '../test/mount'
import CsvBatchPanel from './CsvBatchPanel.vue'

const csv = 'аккумуляторная дрель;18 В;реверс\nсадовый насос;500 Вт\n   \n'

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
  it('previews complete physical lines without a column selector', async () => {
    const wrapper = mountWithPrime(CsvBatchPanel, {
      props: {
        analyze: async (text: string) => analysisFor(text),
        correct: async () => null,
      },
    })
    await pickFile(wrapper)
    expect(wrapper.text()).toContain('rows.csv')
    expect(wrapper.text()).toContain('аккумуляторная дрель;18 В;реверс')
    expect(wrapper.find('[data-test="column"]').exists()).toBe(false)
  })

  it('previews every parsed row, not just the first two', async () => {
    const wrapper = mountWithPrime(CsvBatchPanel, {
      props: { analyze: async (text: string) => analysisFor(text), correct: async () => null },
    })
    await pickFile(wrapper, 'первая\nвторая\nтретья\nчетвёртая')
    expect(wrapper.text()).toContain('строк: 4')
    expect(wrapper.findAll('[data-test="preview-row"]')).toHaveLength(4)
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
    expect(wrapper.text()).toContain('аккумуляторная дрель;18 В;реверс@v')
    expect(wrapper.text()).toContain('садовый насос;500 Вт@v')
    expect(wrapper.text()).toContain('Проверено 2 из 2')
  })

  it('runs spell correction before the search', async () => {
    const analyze = vi.fn(async (text: string) => analysisFor(text))
    const correct = vi.fn(async (text: string) => `${text};уточнено`)
    const wrapper = mountWithPrime(CsvBatchPanel, { props: { analyze, correct } })
    await pickFile(wrapper)
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(analyze).toHaveBeenCalledWith(
      'аккумуляторная дрель;18 В;реверс;уточнено',
      expect.anything(),
    )
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

  it('with the default wiring posts every data row to /api/analyze', async () => {
    const fetchMock = vi.fn(async (...args: [string, RequestInit]) =>
      args[0].includes('/api/analyze')
        ? new Response(JSON.stringify(analysisFor('x')), { status: 200 })
        : new Response('{}', { status: 500 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    try {
      const wrapper = mountWithPrime(CsvBatchPanel)
      await pickFile(wrapper)
      await wrapper.find('[data-test="start"]').trigger('click')
      await flushPromises()
      await flushPromises()
      await flushPromises()
      const analyzeCalls = fetchMock.mock.calls.filter(([url]) => url.includes('/api/analyze'))
      expect(analyzeCalls).toHaveLength(2)
      const texts = analyzeCalls.map(([, init]) => JSON.parse(init.body as string).text)
      expect(texts).toEqual(['аккумуляторная дрель;18 В;реверс', 'садовый насос;500 Вт'])
      expect(wrapper.text()).toContain('Проверено 2 из 2')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('shows a visible error when the CSV is empty', async () => {
    const wrapper = mountWithPrime(CsvBatchPanel, {
      props: { analyze: async (text: string) => analysisFor(text), correct: async () => null },
    })
    await pickFile(wrapper, '')
    expect(wrapper.find('[data-test="file-error"]').text()).toContain('нет строк с описаниями')
    expect(wrapper.find('[data-test="start"]').exists()).toBe(false)
  })

  it('shows a visible error when the file cannot be read', async () => {
    const wrapper = mountWithPrime(CsvBatchPanel, {
      props: { analyze: async (text: string) => analysisFor(text), correct: async () => null },
    })
    const file = new File(['x'], 'broken.csv', { type: 'text/csv' })
    file.text = () => Promise.reject(new Error('unreadable'))
    const input = wrapper.find('[data-test="file-input"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    await wrapper.find('[data-test="file-input"]').trigger('change')
    await flushPromises()
    expect(wrapper.find('[data-test="file-error"]').text()).toContain('Не удалось прочитать')
  })

  it('sends the complete test.csv-style line as one description', async () => {
    const analyze = vi.fn(async (text: string) => analysisFor(text))
    const wrapper = mountWithPrime(CsvBatchPanel, { props: { analyze, correct: async () => null } })
    const line =
      'Отвертка аккумуляторная Bort BAS-48N-Lt,КИТАЙ,' +
      'Вес 900 г | Высота упаковки 200 мм | Глубина упаковки 240 мм | Цвет синий'
    await pickFile(wrapper, line)
    expect(wrapper.text()).toContain('строк: 1')
    await wrapper.find('[data-test="start"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(analyze).toHaveBeenCalledWith(line, expect.anything())
  })
})
