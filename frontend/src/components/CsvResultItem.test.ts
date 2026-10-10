import { describe, expect, it } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import type { BatchItem } from '../composables/useCsvBatch'
import { mountWithPrime } from '../test/mount'
import CsvResultItem from './CsvResultItem.vue'

const analysis: AnalysisResponse = {
  run_id: 'run-1',
  status: 'ready_for_review',
  complete_inference: true,
  recommended_candidate: '26.02.10.110@9c8a',
  properties: [],
  candidates: [],
  clarifying_question: null,
  warnings: [],
}

const item = (overrides: Partial<BatchItem> = {}): BatchItem => ({
  id: 7,
  query: 'аккумуляторная дрель',
  corrected: null,
  spellFixed: false,
  status: 'pending',
  result: null,
  error: null,
  ...overrides,
})

describe('CsvResultItem', () => {
  it('labels pending and searching rows', () => {
    const wrapper = mountWithPrime(CsvResultItem, { props: { item: item(), index: 0 } })
    expect(wrapper.text()).toContain('В очереди')
    const searching = mountWithPrime(CsvResultItem, {
      props: { item: item({ status: 'searching' }), index: 1 },
    })
    expect(searching.text()).toContain('Ищу…')
  })

  it('opens to show the analysis and the correction note', async () => {
    const done = item({
      status: 'done',
      spellFixed: true,
      corrected: 'аккумуляторная дрель 18 В',
      result: analysis,
    })
    const wrapper = mountWithPrime(CsvResultItem, { props: { item: done, index: 3 } })
    await wrapper.find('button').trigger('click')
    expect(wrapper.text()).toContain('аккумуляторная дрель 18 В')
    expect(wrapper.text()).toContain('26.02.10.110')
  })

  it('shows the row error message', () => {
    const failed = item({ status: 'error', error: 'boom' })
    const wrapper = mountWithPrime(CsvResultItem, { props: { item: failed, index: 2 } })
    expect(wrapper.text()).toContain('Ошибка')
    expect(wrapper.text()).toContain('boom')
  })
})
