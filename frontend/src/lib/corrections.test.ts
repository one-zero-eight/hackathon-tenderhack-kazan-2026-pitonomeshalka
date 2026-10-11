import { describe, expect, it } from 'vitest'
import { applyAllCorrections, applyReplacement, type SpellMatch } from './corrections'

function match(overrides: Partial<SpellMatch>): SpellMatch {
  return {
    offset: 0,
    length: 0,
    errorText: '',
    message: '',
    shortMessage: '',
    replacements: [],
    ruleId: 'TEST_RULE',
    category: 'TYPOS',
    issueType: 'misspelling',
    ...overrides,
  }
}

describe('applyAllCorrections', () => {
  it('applies the first replacement of every match', () => {
    const text = 'Я пошол в магазен'
    const matches = [
      match({ offset: 2, length: 5, replacements: ['пошёл'] }),
      match({ offset: 10, length: 7, replacements: ['магазин', 'магазинчик'] }),
    ]
    expect(applyAllCorrections(text, matches)).toBe('Я пошёл в магазин')
  })

  it('skips matches that have no replacements', () => {
    const text = 'Я пошол'
    const matches = [match({ offset: 2, length: 5, replacements: [] })]
    expect(applyAllCorrections(text, matches)).toBe(text)
  })

  it('does not apply overlapping matches twice', () => {
    const text = 'abcdefgh'
    const matches = [
      match({ offset: 3, length: 3, replacements: ['XY'] }),
      match({ offset: 1, length: 4, replacements: ['ZZ'] }),
    ]
    expect(applyAllCorrections(text, matches)).toBe('abcXYgh')
  })

  it('keeps UTF-16 offsets intact around surrogate pairs', () => {
    const text = '😀 пошол'
    const matches = [match({ offset: 3, length: 5, replacements: ['пошёл'] })]
    expect(applyAllCorrections(text, matches)).toBe('😀 пошёл')
  })
})

describe('applyReplacement', () => {
  it('replaces the exact range with the chosen value', () => {
    const text = 'Я пошол в парк'
    const m = match({ offset: 2, length: 5, replacements: ['пошёл', 'пришёл'] })
    expect(applyReplacement(text, m, 'пришёл')).toBe('Я пришёл в парк')
  })

  it('returns the original text when the replacement is empty', () => {
    const text = 'Я пошол в парк'
    const m = match({ offset: 2, length: 5, replacements: ['пошёл'] })
    expect(applyReplacement(text, m, '')).toBe(text)
  })
})
