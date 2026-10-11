import { describe, expect, it, vi } from 'vitest'
import type { FetchLike } from '../lib/fetch-like'
import { ApiError, KtruApiClient } from './client'
import type { AnalysisResponse } from './types'

const analysis: AnalysisResponse = {
  run_id: 'r1',
  status: 'ready_for_review',
  complete_inference: true,
  recommended_candidate: '2620100000@9c8a1a1bba',
  properties: [{ name: 'Тип питания', value: 'аккумулятор' }],
  candidates: [],
  clarifying_question: null,
  warnings: [],
}

function stubFetch(body: unknown, status = 200): FetchLike & { mock: { calls: unknown[][] } } {
  const fn = vi.fn(async (url: string) => {
    if (status === 200 && body && typeof body === 'object' && 'run_id' in body) {
      const result = body as AnalysisResponse
      const job = url.endsWith('/analyses')
        ? { run_id: result.run_id, status: 'running', result: null, error: null }
        : { run_id: result.run_id, status: 'completed', result, error: null }
      return new Response(JSON.stringify(job), { status: url.endsWith('/analyses') ? 202 : 200 })
    }
    return new Response(JSON.stringify(body), { status })
  })
  return fn as unknown as FetchLike & { mock: { calls: unknown[][] } }
}

describe('KtruApiClient.analyze', () => {
  it('starts an analysis and polls the accepted run without resubmitting', async () => {
    const fetchFn = stubFetch(analysis)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const result = await client.analyze({ text: 'дрель 18 В' })
    const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/analyses')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body as string)).toEqual({ text: 'дрель 18 В' })
    expect(result.recommended_candidate).toBe('2620100000@9c8a1a1bba')
    expect(fetchFn.mock.calls[1]).toEqual([
      '/api/analyses/r1',
      { method: 'GET', signal: undefined, cache: 'no-store' },
    ])
  })

  it('survives an aborted request by rethrowing the abort', async () => {
    const fetchFn = vi.fn(async () => {
      throw new DOMException('Aborted', 'AbortError')
    }) as unknown as FetchLike
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    await expect(client.analyze({ text: 'x' })).rejects.toThrow()
  })

  it('retries a disconnected poll and running status without starting another run', async () => {
    vi.useFakeTimers()
    try {
      const fn = vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ run_id: 'r1', status: 'running' }), { status: 202 }),
        )
        .mockRejectedValueOnce(new TypeError('NetworkError when attempting to fetch resource'))
        .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'r1', status: 'running' })))
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ run_id: 'r1', status: 'completed', result: analysis })),
        )
      const client = new KtruApiClient({ baseUrl: '/api', fetch: fn })
      const pending = client.analyze({ text: 'дрель' })
      await vi.advanceTimersByTimeAsync(4000)
      expect(await pending).toEqual(analysis)
      expect(fn.mock.calls.map(([url]) => url)).toEqual([
        '/api/analyses',
        '/api/analyses/r1',
        '/api/analyses/r1',
        '/api/analyses/r1',
      ])
    } finally {
      vi.useRealTimers()
    }
  })

  it('reports a failed background run with its saved partial result', async () => {
    const fn = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            run_id: 'r1',
            status: 'failed',
            error: 'Classifier timed out',
            result: analysis,
          }),
        ),
    )
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fn })
    const error = (await client.waitForAnalysis('r1').catch((e: unknown) => e)) as ApiError
    expect(error.status).toBe(502)
    expect(error.message).toBe('Classifier timed out')
    expect(error.partialResult?.run_id).toBe('r1')
  })

  it('stops polling promptly on cancellation while the server keeps the run', async () => {
    vi.useFakeTimers()
    try {
      const controller = new AbortController()
      const fn = vi.fn(
        async () => new Response(JSON.stringify({ run_id: 'r1', status: 'running' })),
      )
      const client = new KtruApiClient({ baseUrl: '/api', fetch: fn })
      const pending = client.waitForAnalysis('r1', controller.signal)
      const assertion = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
      await vi.advanceTimersByTimeAsync(0)
      controller.abort()
      await assertion
      await vi.advanceTimersByTimeAsync(4000)
      expect(fn).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('KtruApiClient error handling', () => {
  it('exposes the backend error detail as the message', async () => {
    const fetchFn = stubFetch({ detail: { error: 'Another model request is running' } }, 503)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const error = await client.analyze({ text: 'x' }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(503)
    expect((error as ApiError).message).toBe('Another model request is running')
  })

  it('keeps the partial result delivered with a 502', async () => {
    const fetchFn = stubFetch({ detail: { error: 'Nimble failed', result: analysis } }, 502)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const error = await client.analyze({ text: 'x' }).catch((e: unknown) => e)
    expect((error as ApiError).status).toBe(502)
    expect((error as ApiError).partialResult?.run_id).toBe('r1')
  })

  it('joins validation failures into one readable message', async () => {
    const detail = [{ msg: 'text must contain a product description' }]
    const fetchFn = stubFetch({ detail }, 422)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const error = await client.analyze({ text: '   ' }).catch((e: unknown) => e)
    expect((error as ApiError).message).toContain('text must contain a product description')
  })

  it('falls back to the HTTP status when the body is unreadable', async () => {
    const fn = vi.fn(async () => new Response('gateway timeout', { status: 504 }))
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fn as unknown as FetchLike })
    const error = await client.analyze({ text: 'x' }).catch((e: unknown) => e)
    expect((error as ApiError).status).toBe(504)
  })

  it('fills in the candidate arrays the backend omits when empty', async () => {
    const sparse = {
      run_id: 'r2',
      status: 'needs_clarification',
      complete_inference: true,
      recommended_candidate: null,
      properties: [],
      candidates: [
        {
          code: '32.99.53.130-00000001',
          version: '4',
          name: 'Доска магнитно-маркерная',
          status: 'uncertain',
          reasons: ['Вид товара не подтверждён описанием.'],
        },
      ],
      clarifying_question: 'Уточните вид самого товара.',
      warnings: [],
    }
    const fetchFn = stubFetch(sparse)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const result = await client.analyze({ text: 'доска' })
    expect(result.candidates[0].missing_required).toEqual([])
    expect(result.candidates[0].unmatched_properties).toEqual([])
    expect(result.candidates[0].extra_characteristics).toEqual([])
    expect(result.warnings).toEqual([])
  })
})

describe('KtruApiClient.preview and health', () => {
  it('posts to /preview and returns the plan', async () => {
    const payload = { planned_requests: 2, planned_questions: 8, candidates: [] }
    const fetchFn = stubFetch(payload)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const result = await client.preview({ text: 'дрель' })
    const [url] = fetchFn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/preview')
    expect(result.planned_requests).toBe(2)
  })

  it('reads the health payload', async () => {
    const fetchFn = stubFetch({ status: 'ok', model_busy: false })
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const result = await client.health()
    const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/health')
    expect(init.method).toBe('GET')
    expect(result.status).toBe('ok')
  })
})
