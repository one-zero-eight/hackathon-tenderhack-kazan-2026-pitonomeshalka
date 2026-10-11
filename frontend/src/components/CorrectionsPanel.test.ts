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

  it('hides the fix-all button when no match has suggestions', () => {
    const wrapper = mountWithPrime(CorrectionsPanel, {
      props: { matches: [match({ replacements: [] })] },
    })
    expect(wrapper.find('[data-test="panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="apply-all"]').exists()).toBe(false)
  })

  it('hides the fix-all button when the only suggestion is an empty deletion', () => {
    // applyAllCorrections skips a falsy first replacement, so the button would be a no-op.
    const wrapper = mountWithPrime(CorrectionsPanel, {
      props: { matches: [match({ replacements: [''] })] },
    })
    expect(wrapper.find('[data-test="apply-all"]').exists()).toBe(false)
  })

  it('shows the fix-all button when at least one match has suggestions', () => {
    const wrapper = mountWithPrime(CorrectionsPanel, {
      props: {
        matches: [
          match({ replacements: [] }),
          match({ offset: 8, errorText: 'магазен', replacements: ['магазин'] }),
        ],
      },
    })
    expect(wrapper.find('[data-test="apply-all"]').exists()).toBe(true)
  })

  it('reveals the fix-all tooltip on hover', async () => {
    const wrapper = mountWithPrime(CorrectionsPanel, { props: { matches: [match()] } })
    await wrapper.find('[data-test="apply-all"]').trigger('mouseenter')
    // The directive shows the tooltip on a showDelay timer, then Teleports it to body.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(document.body.textContent).toContain(
      'Применяет первое предложенное исправление для каждой опечатки',
    )
    wrapper.unmount()
  })

  it('collapses and expands the issue list from the header toggle', async () => {
    const wrapper = mountWithPrime(CorrectionsPanel, { props: { matches: [match()] } })
    const toggle = () => wrapper.find('[data-test="toggle"]')
    expect(toggle().attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-test="issues"]').classes().join(' ')).toContain('grid-rows-[1fr]')
    await toggle().trigger('click')
    expect(toggle().attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-test="issues"]').classes().join(' ')).toContain('grid-rows-[0fr]')
    await toggle().trigger('click')
    expect(toggle().attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-test="issues"]').classes().join(' ')).toContain('grid-rows-[1fr]')
  })

  it('keeps the fix-all button working while the list is collapsed', async () => {
    const wrapper = mountWithPrime(CorrectionsPanel, { props: { matches: [match()] } })
    await wrapper.find('[data-test="toggle"]').trigger('click')
    expect(wrapper.find('[data-test="apply-all"]').exists()).toBe(true)
    await wrapper.find('[data-test="apply-all"]').trigger('click')
    expect(wrapper.emitted('applyAll')).toHaveLength(1)
  })
})
