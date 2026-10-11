import { describe, expect, it } from 'vitest'
import type { AnalysisResponse, Candidate, Clarification, FinalCard } from '../api/types'
import { mountWithPrime } from '../test/mount'
import AnalysisResult from './AnalysisResult.vue'

const candidate: Candidate = {
  code: '26.02.10.110-00000001',
  version: '9c8a',
  name: 'Дрели аккумуляторные',
  status: 'compatible',
  reasons: ['Совпадение по описанию'],
  missing_required: ['Напряжение батареи'],
  unmatched_properties: ['Цвет: красный'],
  extra_characteristics: [],
}

const result: AnalysisResponse = {
  run_id: 'r1',
  status: 'ready_for_review',
  complete_inference: true,
  recommended_candidate: '26.02.10.110-00000001@9c8a',
  properties: [{ name: 'Тип питания', value: 'аккумулятор' }],
  candidates: [candidate],
  clarifying_question: 'Какое напряжение батареи требуется?',
  warnings: ['Порог принятия не откалиброван'],
}

const clarification: Clarification = {
  question_id: 'clarification_q1',
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
}

const finalCard: FinalCard = {
  code: '25.73.011.111-00000001',
  version: '3',
  name: 'Отвёртка аккумуляторная',
  status: 'ACTIVE',
  units: ['шт'],
  characteristics: [],
  rationale: 'Пользователь выбрал вариант option_a и тем самым сузил множество кандидатов.',
  requires_review: true,
}

describe('AnalysisResult', () => {
  it('renders the recommended position, properties and clarifying question', () => {
    const wrapper = mountWithPrime(AnalysisResult, { props: { result } })
    expect(wrapper.text()).toContain('26.02.10.110-00000001')
    expect(wrapper.text()).toContain('Дрели аккумуляторные')
    expect(wrapper.text()).toContain('Тип питания')
    expect(wrapper.text()).toContain('аккумулятор')
    expect(wrapper.text()).toContain('Какое напряжение батареи требуется?')
  })

  it('flags missing required characteristics as absent from the query', () => {
    const wrapper = mountWithPrime(AnalysisResult, { props: { result } })
    expect(wrapper.text()).toContain('Напряжение батареи')
    expect(wrapper.text()).toContain('Нет в запросе')
  })

  it('shows warnings', () => {
    const wrapper = mountWithPrime(AnalysisResult, { props: { result } })
    expect(wrapper.text()).toContain('Порог принятия не откалиброван')
  })

  it('renders candidates even without a recommendation', () => {
    const wrapper = mountWithPrime(AnalysisResult, {
      props: { result: { ...result, recommended_candidate: null, status: 'needs_clarification' } },
    })
    expect(wrapper.find('[data-test="recommended"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Дрели аккумуляторные')
    expect(wrapper.text()).toContain('Нужны уточнения')
  })

  it('renders candidates whose empty arrays the backend omits from the payload', () => {
    const sparseCandidate = {
      code: '32.99.53.130-00000001',
      version: '4',
      name: 'Доска магнитно-маркерная',
      status: 'uncertain',
      reasons: ['Вид товара не подтверждён описанием.'],
    } as unknown as Candidate
    const wrapper = mountWithPrime(AnalysisResult, {
      props: {
        result: {
          ...result,
          recommended_candidate: null,
          status: 'needs_clarification',
          candidates: [sparseCandidate],
        },
      },
    })
    expect(wrapper.text()).toContain('Доска магнитно-маркерная')
    expect(wrapper.text()).toContain('Вид товара не подтверждён описанием.')
    expect(wrapper.text()).toContain('32.99.53.130-00000001')
  })

  it('renders the final card with its code when the run is resolved', () => {
    const wrapper = mountWithPrime(AnalysisResult, {
      props: { result: { ...result, final_card: finalCard } },
    })
    expect(wrapper.find('[data-test="final-card"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('25.73.011.111-00000001')
    expect(wrapper.text()).toContain('Требует финальной проверки специалистом')
  })

  it('renders the clarification question and proxies the chosen option up', async () => {
    const wrapper = mountWithPrime(AnalysisResult, {
      props: {
        result: {
          ...result,
          recommended_candidate: null,
          status: 'needs_clarification',
          clarification,
        },
      },
    })
    expect(wrapper.find('[data-test="clarification"]').exists()).toBe(true)
    await wrapper.findAll('[data-test="option"]')[0].trigger('click')
    expect(wrapper.emitted('select')).toEqual([['option_a']])
  })

  it('offers the expanded search when nothing matched and there is no question', async () => {
    const wrapper = mountWithPrime(AnalysisResult, {
      props: {
        result: {
          ...result,
          recommended_candidate: null,
          status: 'needs_clarification',
          suggest_expand: true,
          clarification: undefined,
        },
      },
    })
    expect(wrapper.text()).toContain('расширенный поиск')
    await wrapper.find('[data-test="expand"]').trigger('click')
    expect(wrapper.emitted('expand')).toHaveLength(1)
  })
})
