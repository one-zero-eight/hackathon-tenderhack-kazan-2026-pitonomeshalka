import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatusChip from './StatusChip.vue'

describe('StatusChip', () => {
  it('labels candidate verdicts in Russian', () => {
    const compatible = mount(StatusChip, { props: { status: 'compatible' } })
    expect(compatible.text()).toContain('Подходит')
    const uncertain = mount(StatusChip, { props: { status: 'uncertain' } })
    expect(uncertain.text()).toContain('Требует проверки')
    const rejected = mount(StatusChip, { props: { status: 'rejected' } })
    expect(rejected.text()).toContain('Отклонён')
  })

  it('labels analysis outcomes in Russian', () => {
    const ready = mount(StatusChip, { props: { status: 'ready_for_review' } })
    expect(ready.text()).toContain('Готов к проверке')
    const clarify = mount(StatusChip, { props: { status: 'needs_clarification' } })
    expect(clarify.text()).toContain('Нужны уточнения')
    const miss = mount(StatusChip, { props: { status: 'retrieval_miss' } })
    expect(miss.text()).toContain('Ничего не найдено')
  })

  it('uses color tones per verdict', () => {
    const compatible = mount(StatusChip, { props: { status: 'compatible' } })
    expect(compatible.find('[data-test="chip"]').classes().join(' ')).toContain('success')
    const rejected = mount(StatusChip, { props: { status: 'rejected' } })
    expect(rejected.find('[data-test="chip"]').classes().join(' ')).toContain('danger')
  })
})
