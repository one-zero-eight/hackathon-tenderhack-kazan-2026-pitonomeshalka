import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import { api } from '../services'
import { mountWithPrime } from '../test/mount'
import TextSearchPanel from './TextSearchPanel.vue'

vi.mock('../services', () => ({
  api: {
    addHistory: vi.fn(async () => undefined),
    getHistory: vi.fn(async () => ({ queries: [] })),
  },
  lt: {
    check: vi.fn(async (text: string) => ({ text, language: 'ru', matches: [] })),
  },
}))

const analysis: AnalysisResponse = {
  run_id: 'r1',
  status: 'ready_for_review',
  complete_inference: true,
  recommended_candidate: '26.02.10.110@9c8a',
  properties: [],
  candidates: [],
  clarifying_question: null,
  warnings: [],
}

const clarificationResult: AnalysisResponse = {
  ...analysis,
  status: 'needs_clarification',
  recommended_candidate: null,
  clarification: {
    question_id: 'q1',
    kind: 'product',
    question: 'Выберите вид товара.',
    manual_choice: false,
    options: [
      {
        id: 'option_a',
        text: 'Дрель аккумуляторная',
        candidate_codes: ['26.02.10.110-00000001'],
        suggest_expand: false,
      },
    ],
  },
}

function fakeSearch(impl: () => Promise<AnalysisResponse>) {
  return { analyze: vi.fn(impl), clarify: vi.fn(async () => analysis) }
}

const quietSpellcheck = {
  check: vi.fn(async (text: string) => ({ text, language: 'ru', matches: [] })),
}

describe('TextSearchPanel', () => {
  it('searches from the textarea and renders the result', async () => {
    const search = fakeSearch(async () => analysis)
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    await wrapper.find('textarea').setValue('аккумуляторная дрель 18 В')
    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    expect(search.analyze).toHaveBeenCalledWith({ text: 'аккумуляторная дрель 18 В', scope: 'all' })
    expect(wrapper.find('[data-test="result"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('26.02.10.110')
  })

  it('no longer exposes a section dropdown', () => {
    const search = { analyze: vi.fn(async () => analysis) }
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    expect(wrapper.find('[data-test="scope"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Раздел')
  })

  it('disables search while the query is empty', async () => {
    const search = fakeSearch(async () => analysis)
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    const searchButton = wrapper.find('[data-test="search"]')
    expect(searchButton.attributes('disabled')).toBeDefined()
    await searchButton.trigger('click')
    await flushPromises()
    expect(search.analyze).not.toHaveBeenCalled()
  })

  it('shows the robot animation while searching', async () => {
    let resolve!: (value: AnalysisResponse) => void
    const search = {
      analyze: vi.fn(
        () =>
          new Promise<AnalysisResponse>((res) => {
            resolve = res
          }),
      ),
      clarify: vi.fn(async () => analysis),
    }
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    await wrapper.find('textarea').setValue('дрель')
    const click = wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="robot"]').exists()).toBe(true)
    resolve(analysis)
    await click
    await flushPromises()
    expect(wrapper.find('[data-test="robot"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="result"]').exists()).toBe(true)
  })

  it('writes history once per analysis run, not per clarification round', async () => {
    const addHistory = vi.mocked(api.addHistory)
    addHistory.mockClear()
    let runs = 0
    const search = {
      analyze: vi.fn(async () => {
        runs += 1
        return runs === 1 ? clarificationResult : { ...analysis, run_id: 'r2' }
      }),
      clarify: vi.fn(async () => analysis),
    }
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    await wrapper.find('textarea').setValue('дрель')

    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    expect(addHistory).toHaveBeenCalledTimes(1)
    expect(addHistory).toHaveBeenCalledWith(expect.any(String), 'дрель')

    // The clarification answer keeps the same run_id, so history is not written again.
    await wrapper.find('[data-test="option"]').trigger('click')
    await flushPromises()
    expect(addHistory).toHaveBeenCalledTimes(1)

    // A repeated analysis produces a new run_id and is written once more.
    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    expect(addHistory).toHaveBeenCalledTimes(2)
  })

  it('sends the chosen clarification option to the backend', async () => {
    const search = fakeSearch(async () => clarificationResult)
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    await wrapper.find('textarea').setValue('дрель')
    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="option"]').trigger('click')
    await flushPromises()
    expect(search.clarify).toHaveBeenCalledWith({
      run_id: 'r1',
      question_id: 'q1',
      option_id: 'option_a',
    })
    expect(wrapper.find('[data-test="result"]').exists()).toBe(true)
  })

  it('shows the robot while the clarification answer is in flight', async () => {
    let resolve!: (value: AnalysisResponse) => void
    const search = {
      analyze: vi.fn(async () => clarificationResult),
      clarify: vi.fn(
        () =>
          new Promise<AnalysisResponse>((res) => {
            resolve = res
          }),
      ),
    }
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    await wrapper.find('textarea').setValue('дрель')
    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="option"]').exists()).toBe(true)
    await wrapper.find('[data-test="option"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="robot"]').exists()).toBe(true)
    resolve(analysis)
    await flushPromises()
    expect(wrapper.find('[data-test="result"]').exists()).toBe(true)
  })

  it('repeats the search with a larger top_k when the user asks for more options', async () => {
    const search = fakeSearch(async () => ({ ...analysis, suggest_expand: true }))
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    await wrapper.find('textarea').setValue('дрель')
    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-test="expand"]').trigger('click')
    await flushPromises()
    expect(search.analyze).toHaveBeenLastCalledWith({ text: 'дрель', scope: 'all', top_k: 12 })
  })

  it('caps the expanded top_k at the backend limit', async () => {
    const search = fakeSearch(async () => ({ ...analysis, suggest_expand: true }))
    const wrapper = mountWithPrime(TextSearchPanel, {
      props: { spellcheck: quietSpellcheck, search },
    })
    await wrapper.find('textarea').setValue('дрель')
    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    for (let round = 0; round < 7; round += 1) {
      await wrapper.find('[data-test="expand"]').trigger('click')
      await flushPromises()
    }
    const calls = search.analyze.mock.calls as { top_k?: number }[][]
    expect(calls.at(-1)?.[0]?.top_k).toBe(32)
    expect(calls.at(-2)?.[0]?.top_k).toBe(32)
  })

  it('stays usable when LanguageTool is down', async () => {
    const spell = {
      check: vi.fn(async () => {
        throw new Error('lt down')
      }),
    }
    const search = fakeSearch(async () => analysis)
    const wrapper = mountWithPrime(TextSearchPanel, { props: { spellcheck: spell, search } })
    await wrapper.find('textarea').setValue('дрел с трещотой')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="lt-warning"]').exists()).toBe(true)
    })
    await wrapper.find('[data-test="search"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="result"]').exists()).toBe(true)
  })

  it('offers corrections when the spellcheck finds issues', async () => {
    const spell = {
      check: vi.fn(async (text: string) => ({
        text,
        language: 'ru',
        matches: [
          {
            offset: 0,
            length: 4,
            errorText: 'дрел',
            message: 'Опечатка',
            shortMessage: 'Опечатка',
            replacements: ['дрель'],
            ruleId: 'R',
            category: 'C',
            issueType: 'misspelling',
          },
        ],
      })),
    }
    const search = fakeSearch(async () => analysis)
    const wrapper = mountWithPrime(TextSearchPanel, { props: { spellcheck: spell, search } })
    await wrapper.find('textarea').setValue('дрел')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="panel"]').exists()).toBe(true)
    })
    await wrapper.findAll('[data-test="replacement"]')[0].trigger('click')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('дрель')
  })
})
