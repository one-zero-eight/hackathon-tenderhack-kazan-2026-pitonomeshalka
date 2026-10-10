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
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  return fn as unknown as FetchLike & { mock: { calls: unknown[][] } }
}

describe('KtruApiClient.analyze', () => {
  it('posts the request body as JSON to /analyze', async () => {
    const fetchFn = stubFetch(analysis)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const result = await client.analyze({ text: 'дрель 18 В' })
    const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/analyze')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body as string)).toEqual({ text: 'дрель 18 В' })
    expect(result.recommended_candidate).toBe('2620100000@9c8a1a1bba')
  })

  it('survives an aborted request by rethrowing the abort', async () => {
    const fetchFn = vi.fn(async () => {
      throw new DOMException('Aborted', 'AbortError')
    }) as unknown as FetchLike
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    await expect(client.analyze({ text: 'x' })).rejects.toThrow()
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
