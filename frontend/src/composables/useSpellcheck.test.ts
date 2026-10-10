import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SpellMatch } from '../lib/corrections'
import { useSpellcheck } from './useSpellcheck'

function match(overrides: Partial<SpellMatch> = {}): SpellMatch {
  return {
    offset: 0,
    length: 5,
    errorText: 'пошол',
    message: 'Опечатка',
    shortMessage: 'Опечатка',
    replacements: ['fix'],
    ruleId: 'R',
    category: 'C',
    issueType: 'misspelling',
    ...overrides,
  }
}

function fakeClient() {
  return {
    check: vi.fn(async (text: string) => ({ text, language: 'ru-RU', matches: [match()] })),
  }
}

describe('useSpellcheck', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('debounces rapid input into a single check', async () => {
    const client = fakeClient()
    const spell = useSpellcheck(client, { debounceMs: 200 })
    spell.scheduleCheck('Я по')
    spell.scheduleCheck('Я пош')
    spell.scheduleCheck('Я пошол')
    await vi.advanceTimersByTimeAsync(250)
    expect(client.check).toHaveBeenCalledTimes(1)
    expect(client.check).toHaveBeenCalledWith('Я пошол')
    expect(spell.matches.value).toHaveLength(1)
    expect(spell.checkedText.value).toBe('Я пошол')
  })

  it('ignores a stale response that lands after a newer one', async () => {
    let resolveFirst: (value: unknown) => void = () => {}
    const client = {
      check: vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveFirst = resolve
            }),
        )
        .mockResolvedValueOnce({ text: 'bbbbb', language: 'ru', matches: [match()] }),
    }
    const spell = useSpellcheck(client, { debounceMs: 10 })
    spell.scheduleCheck('aaaaa')
    await vi.advanceTimersByTimeAsync(20)
    spell.scheduleCheck('bbbbb')
    await vi.advanceTimersByTimeAsync(20)
    resolveFirst({ text: 'aaaaa', language: 'ru', matches: [match({ errorText: 'aaaaa' })] })
    await vi.advanceTimersByTimeAsync(0)
    expect(spell.checkedText.value).toBe('bbbbb')
  })

  it('skips checking short or blank text', async () => {
    const client = fakeClient()
    const spell = useSpellcheck(client, { debounceMs: 10 })
    spell.scheduleCheck('   ')
    await vi.advanceTimersByTimeAsync(50)
    expect(client.check).not.toHaveBeenCalled()
    expect(spell.matches.value).toEqual([])
  })

  it('applyAll returns the corrected snapshot text', async () => {
    const client = {
      check: vi.fn(async () => ({
        text: 'Я пошол',
        language: 'ru',
        matches: [match({ offset: 2, replacements: ['пошёл'] })],
      })),
    }
    const spell = useSpellcheck(client, { debounceMs: 0 })
    spell.scheduleCheck('Я пошол')
    await vi.advanceTimersByTimeAsync(10)
    expect(spell.applyAll()).toBe('Я пошёл')
  })

  it('applyOne replaces only the chosen suggestion', async () => {
    const client = {
      check: vi.fn(async () => ({
        text: 'Я пошол',
        language: 'ru',
        matches: [match({ offset: 2, replacements: ['пошёл', 'пришёл'] })],
      })),
    }
    const spell = useSpellcheck(client, { debounceMs: 0 })
    spell.scheduleCheck('Я пошол')
    await vi.advanceTimersByTimeAsync(10)
    expect(spell.applyOne(0, 'пришёл')).toBe('Я пришёл')
  })

  it('survives a failing server and exposes the error', async () => {
    const client = {
      check: vi.fn(async () => {
        throw new Error('lt down')
      }),
    }
    const spell = useSpellcheck(client, { debounceMs: 0 })
    spell.scheduleCheck('текст')
    await vi.advanceTimersByTimeAsync(10)
    expect(spell.error.value).toBe('lt down')
    expect(spell.checking.value).toBe(false)
    expect(spell.matches.value).toEqual([])
  })
})
