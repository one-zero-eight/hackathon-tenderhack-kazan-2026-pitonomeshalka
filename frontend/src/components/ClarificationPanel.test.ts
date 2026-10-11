import { describe, expect, it } from 'vitest'
import type { Clarification } from '../api/types'
import { mountWithPrime } from '../test/mount'
import ClarificationPanel from './ClarificationPanel.vue'

const question: Clarification = {
  question_id: 'clarification_1',
  kind: 'characteristic',
  question: 'Укажите «Тип питания».',
  manual_choice: false,
  options: [
    {
      id: 'option_a',
      text: 'От аккумулятора',
      candidate_codes: ['25.73.011.111-00000001'],
      suggest_expand: false,
    },
    {
      id: 'option_none',
      text: 'Ничего из перечисленного',
      candidate_codes: [],
      suggest_expand: true,
    },
  ],
}

describe('ClarificationPanel', () => {
  it('renders the question and every option as a choice chip', () => {
    const wrapper = mountWithPrime(ClarificationPanel, { props: { clarification: question } })
    expect(wrapper.find('[data-test="clarification"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Укажите «Тип питания».')
    const options = wrapper.findAll('[data-test="option"]')
    expect(options).toHaveLength(2)
    expect(options[0].text()).toContain('От аккумулятора')
    expect(options[1].text()).toContain('Ничего из перечисленного')
  })

  it('emits the chosen option id on click', async () => {
    const wrapper = mountWithPrime(ClarificationPanel, { props: { clarification: question } })
    await wrapper.findAll('[data-test="option"]')[0].trigger('click')
    expect(wrapper.emitted('select')).toEqual([['option_a']])
  })

  it('still emits select for the expand-suggesting option; /clarify decides', async () => {
    const wrapper = mountWithPrime(ClarificationPanel, { props: { clarification: question } })
    await wrapper.findAll('[data-test="option"]')[1].trigger('click')
    expect(wrapper.emitted('select')).toEqual([['option_none']])
  })

  it('marks the option that suggests a wider search', () => {
    const wrapper = mountWithPrime(ClarificationPanel, { props: { clarification: question } })
    const expandOption = wrapper.findAll('[data-test="option"]')[1]
    expect(expandOption.text()).toContain('показать ещё варианты')
    const plainOption = wrapper.findAll('[data-test="option"]')[0]
    expect(plainOption.text()).not.toContain('показать ещё варианты')
  })

  it('headlines a manual choice differently from a splitting question', () => {
    const manual = mountWithPrime(ClarificationPanel, {
      props: { clarification: { ...question, manual_choice: true } },
    })
    expect(manual.text()).toContain('Уточните вручную')
    const plain = mountWithPrime(ClarificationPanel, { props: { clarification: question } })
    expect(plain.text()).not.toContain('Уточните вручную')
  })

  it('disables every option while an answer is in flight', async () => {
    const wrapper = mountWithPrime(ClarificationPanel, {
      props: { clarification: question, pending: true },
    })
    const options = wrapper.findAll('[data-test="option"]')
    expect(options.length).toBeGreaterThan(0)
    expect(options.every((option) => (option.element as HTMLButtonElement).disabled)).toBe(true)
    await options[0].trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('offers the expanded search when the run offers no fitting option', async () => {
    const wrapper = mountWithPrime(ClarificationPanel, {
      props: { clarification: question, suggestExpand: true },
    })
    expect(wrapper.text()).toContain('расширенный поиск')
    await wrapper.find('[data-test="expand"]').trigger('click')
    expect(wrapper.emitted('expand')).toHaveLength(1)
  })
})
