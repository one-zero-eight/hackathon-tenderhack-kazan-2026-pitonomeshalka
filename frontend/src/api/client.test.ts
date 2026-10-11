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

const needsClarification: AnalysisResponse = {
  ...analysis,
  status: 'needs_clarification',
  recommended_candidate: null,
  clarification: {
    question_id: 'q1',
    kind: 'product',
    question: 'Какой вид отвёртки нужен?',
    manual_choice: false,
    options: [
      {
        id: 'opt-1',
        text: 'Отвёртка аккумуляторная',
        candidate_codes: ['26.20.10.000-00000001'],
        suggest_expand: false,
      },
    ],
  },
}

const clarified: AnalysisResponse = {
  ...analysis,
  status: 'ready_for_review',
  final_card: {
    code: '26.20.10.000-00000001',
    version: '4',
    name: 'Отвёртка аккумуляторная',
    status: 'Действует',
    units: ['796'],
    characteristics: [
      {
        code: 'THE000001',
        name: 'Тип питания',
        required: true,
        choice: 'выбор из значений',
        choice_type: 1,
        is_numeric: false,
        units: [],
        values: [{ value: 'аккумулятор' }],
      },
    ],
    rationale: 'Вариант уточнения сузил множество кандидатов до одного кода.',
    requires_review: true,
  },
  suggest_expand: false,
  manual_choice: false,
}

describe('KtruApiClient.clarify', () => {
  it('posts the run, question and chosen option to /clarify', async () => {
    const fetchFn = stubFetch(clarified)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const result = await client.clarify({
      run_id: 'r1',
      question_id: 'q1',
      option_id: 'opt-1',
    })
    const [url, init] = fetchFn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/clarify')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body as string)).toEqual({
      run_id: 'r1',
      question_id: 'q1',
      option_id: 'opt-1',
    })
    expect(result.final_card?.code).toBe('26.20.10.000-00000001')
    expect(result.final_card?.requires_review).toBe(true)
  })

  it('fills the clarification arrays the backend omits when empty', async () => {
    const sparse = {
      run_id: 'r3',
      status: 'needs_clarification',
      complete_inference: true,
      recommended_candidate: null,
      properties: [],
      candidates: [],
      clarifying_question: null,
      warnings: [],
      clarification: {
        question_id: 'product:r3',
        kind: 'product',
        question: 'Какой вид отвёртки нужен?',
        manual_choice: false,
        options: [
          { id: 'opt-1', text: 'Отвёртка аккумуляторная' },
          {
            id: 'opt-2',
            text: 'Ничего из перечисленного',
            candidate_codes: [],
            suggest_expand: true,
          },
        ],
      },
    }
    const fetchFn = stubFetch(sparse)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const result = await client.clarify({
      run_id: 'r3',
      question_id: 'product:r3',
      option_id: 'opt-1',
    })
    expect(result.clarification?.options[0].candidate_codes).toEqual([])
    expect(result.clarification?.options[1].candidate_codes).toEqual([])
    expect(result.suggest_expand).toBe(false)
    expect(result.manual_choice).toBe(false)
  })

  it('exposes the backend error detail as the message', async () => {
    const fetchFn = stubFetch({ detail: { error: 'Run is unknown' } }, 404)
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const error = await client
      .clarify({ run_id: 'nope', question_id: 'q1', option_id: 'opt-1' })
      .catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).message).toBe('Run is unknown')
  })

  it('keeps the partial result delivered with a failed clarify', async () => {
    const fetchFn = stubFetch(
      { detail: { error: 'Database is unavailable', result: needsClarification } },
      503,
    )
    const client = new KtruApiClient({ baseUrl: '/api', fetch: fetchFn })
    const error = await client
      .clarify({ run_id: 'r1', question_id: 'q1', option_id: 'opt-1' })
      .catch((e: unknown) => e)
    expect((error as ApiError).status).toBe(503)
    expect((error as ApiError).partialResult?.clarification?.question_id).toBe('q1')
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
