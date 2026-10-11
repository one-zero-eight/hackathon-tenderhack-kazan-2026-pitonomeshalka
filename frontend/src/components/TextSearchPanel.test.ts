import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import { mountWithPrime } from '../test/mount'
import TextSearchPanel from './TextSearchPanel.vue'

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

const quietSpellcheck = {
  check: vi.fn(async (text: string) => ({ text, language: 'ru', matches: [] })),
}

describe('TextSearchPanel', () => {
  it('searches from the textarea and renders the result', async () => {
    const search = { analyze: vi.fn(async () => analysis) }
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
    const search = { analyze: vi.fn(async () => analysis) }
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

  it('stays usable when LanguageTool is down', async () => {
    const spell = {
      check: vi.fn(async () => {
        throw new Error('lt down')
      }),
    }
    const search = { analyze: vi.fn(async () => analysis) }
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
    const search = { analyze: vi.fn(async () => analysis) }
    const wrapper = mountWithPrime(TextSearchPanel, { props: { spellcheck: spell, search } })
    await wrapper.find('textarea').setValue('дрел')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-test="panel"]').exists()).toBe(true)
    })
    await wrapper.findAll('[data-test="replacement"]')[0].trigger('click')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('дрель')
  })
})
