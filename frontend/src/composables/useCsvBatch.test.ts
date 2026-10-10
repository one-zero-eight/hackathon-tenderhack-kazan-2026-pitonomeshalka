import { describe, expect, it, vi } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import { useCsvBatch } from './useCsvBatch'

const analysis = (code: string): AnalysisResponse => ({
  run_id: `run-${code}`,
  status: 'ready_for_review',
  complete_inference: true,
  recommended_candidate: code,
  properties: [],
  candidates: [],
  clarifying_question: null,
  warnings: [],
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

function buildDeps(analyze: unknown, correct?: (text: string) => Promise<string | null>) {
  return {
    analyze: analyze as (text: string, signal: AbortSignal) => Promise<AnalysisResponse>,
    correct: correct ?? (async () => null),
  }
}

describe('useCsvBatch', () => {
  it('processes every row in order and stores results', async () => {
    const calls: string[] = []
    const analyze = async (text: string) => {
      calls.push(text)
      return analysis(text)
    }
    const batch = useCsvBatch(buildDeps(analyze))
    batch.start([
      { id: 1, query: 'дрель' },
      { id: 2, query: 'молоток' },
    ])
    await batch.done
    expect(calls).toEqual(['дрель', 'молоток'])
    expect(batch.items.value.map((item) => item.status)).toEqual(['done', 'done'])
    expect(batch.items.value[0].result?.recommended_candidate).toBe('дрель')
  })

  it('streams the first result while the second row is still pending', async () => {
    const first = deferred<AnalysisResponse>()
    const analyze = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(async (text: string) => analysis(text))
    const batch = useCsvBatch(buildDeps(analyze))
    batch.start([
      { id: 1, query: 'A' },
      { id: 2, query: 'B' },
    ])
    await flush()
    expect(batch.items.value[0].status).toBe('searching')
    expect(batch.items.value[1].status).toBe('pending')
    first.resolve(analysis('A'))
    await batch.done
    expect(batch.items.value[0].status).toBe('done')
    expect(batch.items.value[1].status).toBe('done')
  })

  it('runs spell correction first and flags fixed rows', async () => {
    const correct = vi.fn(async (text: string) => `${text} исправлено`)
    const analyze = vi.fn(async (text: string) => analysis(text))
    const batch = useCsvBatch(buildDeps(analyze, correct))
    batch.start([{ id: 1, query: 'дрел' }])
    await batch.done
    expect(analyze).toHaveBeenCalledWith('дрел исправлено', expect.anything())
    expect(batch.items.value[0].corrected).toBe('дрел исправлено')
    expect(batch.items.value[0].spellFixed).toBe(true)
  })

  it('falls back to the raw query when correction fails', async () => {
    const correct = vi.fn(async () => {
      throw new Error('lt down')
    })
    const analyze = vi.fn(async (text: string) => analysis(text))
    const batch = useCsvBatch(buildDeps(analyze, correct))
    batch.start([{ id: 1, query: 'дрел' }])
    await batch.done
    expect(analyze).toHaveBeenCalledWith('дрел', expect.anything())
    expect(batch.items.value[0].status).toBe('done')
  })

  it('keeps processing the remaining rows after a failed row', async () => {
    const analyze = vi
      .fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockImplementationOnce(async (text: string) => analysis(text))
    const batch = useCsvBatch(buildDeps(analyze))
    batch.start([
      { id: 1, query: 'A' },
      { id: 2, query: 'B' },
    ])
    await batch.done
    expect(batch.items.value.map((item) => item.status)).toEqual(['error', 'done'])
    expect(batch.items.value[0].error).toBe('boom')
  })

  it('retries a 503 busy error once before succeeding', async () => {
    const analyze = vi
      .fn()
      .mockRejectedValueOnce(Object.assign(new Error('busy'), { status: 503 }))
      .mockImplementationOnce(async (text: string) => analysis(text))
    const batch = useCsvBatch(buildDeps(analyze), { retryCount: 1, retryDelayMs: 1 })
    batch.start([{ id: 1, query: 'A' }])
    await batch.done
    expect(analyze).toHaveBeenCalledTimes(2)
    expect(batch.items.value[0].status).toBe('done')
  })

  it('cancel aborts the current request and stops scheduling', async () => {
    const first = deferred<AnalysisResponse>()
    const analyze = vi.fn(() => first.promise)
    const batch = useCsvBatch(buildDeps(analyze))
    batch.start([
      { id: 1, query: 'A' },
      { id: 2, query: 'B' },
      { id: 3, query: 'C' },
    ])
    await flush()
    batch.cancel()
    const calls = analyze.mock.calls as unknown as Array<[string, AbortSignal]>
    expect(calls[0][1].aborted).toBe(true)
    first.resolve(analysis('A'))
    await batch.done
    expect(batch.items.value.map((item) => item.status)).toEqual(['done', 'pending', 'pending'])
    expect(analyze).toHaveBeenCalledTimes(1)
  })

  it('counts finished items in progress', async () => {
    const analyze = async (text: string) => analysis(text)
    const batch = useCsvBatch(buildDeps(analyze))
    batch.start([
      { id: 1, query: 'A' },
      { id: 2, query: 'B' },
    ])
    expect(batch.progress.value).toEqual({ done: 0, total: 2 })
    await batch.done
    expect(batch.progress.value).toEqual({ done: 2, total: 2 })
  })
})
