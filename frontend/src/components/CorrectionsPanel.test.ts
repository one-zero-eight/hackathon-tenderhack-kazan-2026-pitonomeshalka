import { describe, expect, it } from 'vitest'
import type { SpellMatch } from '../lib/corrections'
import { mountWithPrime } from '../test/mount'
import CorrectionsPanel from './CorrectionsPanel.vue'

function match(overrides: Partial<SpellMatch> = {}): SpellMatch {
  return {
    offset: 0,
    length: 5,
    errorText: 'пошол',
    message: 'Возможно, опечатка',
    shortMessage: 'Опечатка',
    replacements: ['пошёл', 'пришёл'],
    ruleId: 'R',
    category: 'C',
    issueType: 'misspelling',
    ...overrides,
  }
}

describe('CorrectionsPanel', () => {
  it('renders nothing without matches', () => {
    const wrapper = mountWithPrime(CorrectionsPanel, { props: { matches: [] } })
    expect(wrapper.find('[data-test="panel"]').exists()).toBe(false)
  })

  it('lists matches with at most three replacement buttons', () => {
    const wrapper = mountWithPrime(CorrectionsPanel, {
      props: { matches: [match({ replacements: ['a', 'b', 'c', 'd'] })] },
    })
    expect(wrapper.findAll('[data-test="replacement"]')).toHaveLength(3)
    expect(wrapper.text()).toContain('пошол')
  })

  it('emits apply with the match index and chosen replacement', async () => {
    const wrapper = mountWithPrime(CorrectionsPanel, { props: { matches: [match()] } })
    await wrapper.findAll('[data-test="replacement"]')[1].trigger('click')
    expect(wrapper.emitted('apply')?.[0]).toEqual([0, 'пришёл'])
  })

  it('emits applyAll once for the fix-all button', async () => {
    const wrapper = mountWithPrime(CorrectionsPanel, {
      props: { matches: [match(), match({ offset: 8, errorText: 'магазен' })] },
    })
    await wrapper.find('[data-test="apply-all"]').trigger('click')
    expect(wrapper.emitted('applyAll')).toHaveLength(1)
  })
})
