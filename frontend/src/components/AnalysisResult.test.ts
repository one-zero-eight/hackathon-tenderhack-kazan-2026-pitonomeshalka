import { describe, expect, it } from 'vitest'
import type { AnalysisResponse, Candidate } from '../api/types'
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
})
