import { describe, expect, it, vi } from 'vitest'
import type { AnalysisResponse } from '../api/types'
import { useTextSearch } from './useTextSearch'

const analysis: AnalysisResponse = {
  run_id: 'r1',
  status: 'ready_for_review',
  complete_inference: true,
  recommended_candidate: 'code@ver',
  properties: [],
  candidates: [],
  clarifying_question: null,
  warnings: [],
}

describe('useTextSearch', () => {
  it('moves from searching to done and stores the result', async () => {
    const api = { analyze: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    const running = search.search('дрель 18 В')
    expect(search.phase.value).toBe('searching')
    await running
    expect(search.phase.value).toBe('done')
    expect(search.result.value?.run_id).toBe('r1')
    expect(api.analyze).toHaveBeenCalledWith({ text: 'дрель 18 В', scope: 'all' })
  })

  it('passes the chosen scope to the backend', async () => {
    const api = { analyze: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    await search.search('дрель', 'tools')
    expect(api.analyze).toHaveBeenCalledWith({ text: 'дрель', scope: 'tools' })
  })

  it('rejects an empty query without calling the backend', async () => {
    const api = { analyze: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    await search.search('   ')
    expect(search.phase.value).toBe('error')
    expect(api.analyze).not.toHaveBeenCalled()
  })

  it('stores the readable error message on failure', async () => {
    const api = {
      analyze: vi.fn(async () => {
        throw Object.assign(new Error('Another model request is running'), { status: 503 })
      }),
    }
    const search = useTextSearch(api)
    await search.search('дрель')
    expect(search.phase.value).toBe('error')
    expect(search.error.value).toBe('Another model request is running')
  })

  it('keeps the partial result delivered with a 502', async () => {
    const partial = { ...analysis, run_id: 'partial', recommended_candidate: null }
    const api = {
      analyze: vi.fn(async () => {
        throw Object.assign(new Error('Nimble failed'), { status: 502, partialResult: partial })
      }),
    }
    const search = useTextSearch(api)
    await search.search('дрель')
    expect(search.phase.value).toBe('error')
    expect(search.result.value?.run_id).toBe('partial')
  })

  it('reset returns the state to idle', async () => {
    const api = { analyze: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    await search.search('дрель')
    search.reset()
    expect(search.phase.value).toBe('idle')
    expect(search.result.value).toBeNull()
  })
})
