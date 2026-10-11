import { describe, expect, it } from 'vitest'
import type { FinalCard, FinalCardCharacteristic } from '../api/types'
import { mountWithPrime } from '../test/mount'
import FinalKtruCard from './FinalKtruCard.vue'

const textCharacteristic: FinalCardCharacteristic = {
  code: '080',
  name: 'Тип питания',
  required: true,
  choice: 'one_of',
  choice_type: 1,
  is_numeric: false,
  units: ['168'],
  values: [
    {
      id: 11,
      ordinal: 0,
      text: 'От аккумулятора',
      okei: '168',
      issue: null,
      value_format: null,
      spans: [],
    },
  ],
}

const rangeCharacteristic: FinalCardCharacteristic = {
  code: '090',
  name: 'Ёмкость батареи, А·ч',
  required: false,
  choice: 'one_of',
  choice_type: 1,
  is_numeric: true,
  units: ['112'],
  values: [
    {
      id: 12,
      ordinal: 1,
      text: null,
      okei: '112',
      issue: null,
      value_format: 'N',
      spans: [{ lower: '3', upper: '6', bounds: '[)', empty: false }],
    },
  ],
}

const card: FinalCard = {
  code: '25.73.011.111-00000001',
  version: '3',
  name: 'Отвёртка аккумуляторная',
  status: 'ACTIVE',
  units: ['шт'],
  characteristics: [textCharacteristic, rangeCharacteristic],
  rationale:
    'Пользователь выбрал вопрос clarification_1, вариант option_a и тем самым сузил множество кандидатов до кода 25.73.011.111-00000001.',
  requires_review: true,
}

describe('FinalKtruCard', () => {
  it('shows the code, name, version, units and status of the position', () => {
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card } })
    expect(wrapper.find('[data-test="card-code"]').text()).toBe('25.73.011.111-00000001')
    expect(wrapper.text()).toContain('Отвёртка аккумуляторная')
    expect(wrapper.text()).toContain('Версия 3')
    expect(wrapper.text()).toContain('ACTIVE')
    expect(wrapper.text()).toContain('шт')
  })

  it('renders each characteristic with its values', () => {
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card } })
    expect(wrapper.text()).toContain('Тип питания')
    expect(wrapper.text()).toContain('От аккумулятора')
    expect(wrapper.text()).toContain('Ёмкость батареи, А·ч')
  })

  it('formats numeric ranges from spans', () => {
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card } })
    expect(wrapper.text()).toContain('от 3 (включительно) до 6 (не включая)')
  })

  it('folds long value lists into details', () => {
    const long: FinalCard = {
      ...card,
      characteristics: [
        {
          ...textCharacteristic,
          name: 'Назначение',
          values: Array.from({ length: 8 }, (_, index) => ({
            id: index,
            ordinal: index,
            text: `Значение ${index}`,
            okei: null,
            issue: null,
            value_format: null,
            spans: [],
          })),
        },
      ],
    }
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card: long } })
    const details = wrapper.find('details')
    expect(details.exists()).toBe(true)
    expect(details.text()).toContain('Значение 7')
    const short = mountWithPrime(FinalKtruCard, { props: { card } })
    expect(short.find('details').exists()).toBe(false)
  })

  it('explains the choice with the deterministic rationale', () => {
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card } })
    expect(wrapper.text()).toContain('сузил множество кандидатов')
    expect(wrapper.text()).toContain('clarification_1')
  })

  it('badges the card as requiring a specialist review', () => {
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card } })
    expect(wrapper.find('[data-test="review-badge"]').text()).toContain(
      'Требует финальной проверки специалистом',
    )
  })

  it('omits the confirmed block when the card has no confirmed values', () => {
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card } })
    expect(wrapper.find('[data-test="confirmed"]').exists()).toBe(false)
  })

  it('renders the confirmed block with the values confirmed in clarifications', () => {
    const withConfirmed: FinalCard = {
      ...card,
      confirmed: [{ name: 'Питание', value: 'От сети' }],
    }
    const wrapper = mountWithPrime(FinalKtruCard, { props: { card: withConfirmed } })
    const block = wrapper.find('[data-test="confirmed"]')
    expect(block.exists()).toBe(true)
    expect(block.text()).toContain('Подтверждённые характеристики')
    expect(block.text()).toContain('Питание')
    expect(block.text()).toContain('От сети')
  })
})
