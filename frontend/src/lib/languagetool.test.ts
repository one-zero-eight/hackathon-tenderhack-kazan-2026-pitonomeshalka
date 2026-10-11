import { describe, expect, it, vi } from 'vitest'
import type { FetchLike } from './fetch-like'
import { LanguageToolClient, LanguageToolError } from './languagetool'

const fixture = {
  matches: [
    {
      message: 'Возможно, опечатка.',
      shortMessage: 'Опечатка',
      offset: 2,
      length: 5,
      replacements: [{ value: 'пошёл' }, { value: 'пошла' }],
      rule: {
        id: 'RU_MORFO',
        description: 'Морфология',
        issueType: 'misspelling',
        category: { id: 'TYPOS', name: 'Опечатки' },
      },
      sentence: 'Я пошол в парк.',
    },
  ],
  language: { code: 'ru-RU', detectedLanguage: { code: 'ru' } },
}

function stubFetch(body: unknown, status = 200): FetchLike & { mock: { calls: unknown[][] } } {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  return fn as unknown as FetchLike & { mock: { calls: unknown[][] } }
}

describe('LanguageToolClient.check', () => {
  it('posts form-encoded parameters to /v2/check', async () => {
    const fetchFn = stubFetch(fixture)
    const client = new LanguageToolClient({ baseUrl: '/lt', fetch: fetchFn })
    await client.check('Я пошол')
    expect(fetchFn.mock.calls).toHaveLength(1)
    const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/lt/v2/check')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe(
      'application/x-www-form-urlencoded',
    )
    const params = new URLSearchParams(init.body as string)
    expect(params.get('text')).toBe('Я пошол')
    expect(params.get('language')).toBe('ru-RU')
    expect(params.get('level')).toBe('default')
  })

  it('maps the raw response into spell matches', async () => {
    const client = new LanguageToolClient({ baseUrl: '/lt', fetch: stubFetch(fixture) })
    const outcome = await client.check('Я пошол')
    expect(outcome.language).toBe('ru-RU')
    expect(outcome.matches).toHaveLength(1)
    const m = outcome.matches[0]
    expect(m.offset).toBe(2)
    expect(m.length).toBe(5)
    expect(m.errorText).toBe('пошол')
    expect(m.replacements).toEqual(['пошёл', 'пошла'])
    expect(m.shortMessage).toBe('Опечатка')
    expect(m.ruleId).toBe('RU_MORFO')
  })

  it('does not call the server for blank text', async () => {
    const fetchFn = stubFetch(fixture)
    const client = new LanguageToolClient({ baseUrl: '/lt', fetch: fetchFn })
    const outcome = await client.check('   ')
    expect(fetchFn.mock.calls).toHaveLength(0)
    expect(outcome.matches).toEqual([])
  })

  it('wraps network failures into LanguageToolError', async () => {
    const fetchFn = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as FetchLike
    const client = new LanguageToolClient({ baseUrl: '/lt', fetch: fetchFn })
    await expect(client.check('текст')).rejects.toBeInstanceOf(LanguageToolError)
  })

  it('raises LanguageToolError on HTTP error responses', async () => {
    const client = new LanguageToolClient({
      baseUrl: '/lt',
      fetch: stubFetch({ reason: 'x' }, 400),
    })
    await expect(client.check('текст')).rejects.toBeInstanceOf(LanguageToolError)
  })
})
