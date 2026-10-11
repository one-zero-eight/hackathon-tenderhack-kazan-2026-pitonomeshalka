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

describe('useTextSearch.clarify', () => {
  it('moves from searching to done and stores the clarified result', async () => {
    const api = {
      analyze: vi.fn(async () => needsClarification),
      clarify: vi.fn(async () => clarified),
    }
    const search = useTextSearch(api)
    await search.search('отвёртка аккумуляторная')
    expect(search.result.value?.clarification?.question_id).toBe('q1')
    const running = search.clarify('opt-1')
    expect(search.phase.value).toBe('searching')
    await running
    expect(search.phase.value).toBe('done')
    expect(api.clarify).toHaveBeenCalledWith({
      run_id: 'r1',
      question_id: 'q1',
      option_id: 'opt-1',
    })
    expect(search.result.value?.final_card?.code).toBe('26.20.10.000-00000001')
  })

  it('keeps the partial result delivered with a failed clarify', async () => {
    const partial = { ...needsClarification, run_id: 'partial' }
    const api = {
      analyze: vi.fn(async () => needsClarification),
      clarify: vi.fn(async () => {
        throw Object.assign(new Error('Вопрос устарел'), { status: 409, partialResult: partial })
      }),
    }
    const search = useTextSearch(api)
    await search.search('отвёртка аккумуляторная')
    await search.clarify('opt-1')
    expect(search.phase.value).toBe('done')
    expect(search.error.value).toBeNull()
    expect(search.clarifyError.value).toBe('Вопрос устарел')
    expect(search.result.value?.run_id).toBe('partial')
  })

  it('sends free text to the LLM-backed clarify and keeps the result on failure', async () => {
    const api = {
      analyze: vi.fn(async () => needsClarification),
      clarify: vi.fn(async () => clarified),
    }
    const search = useTextSearch(api)
    await search.search('отвёртка аккумуляторная')
    await search.clarifyText('  такая отвёртка, но на батарейках  ')
    expect(api.clarify).toHaveBeenCalledWith({
      run_id: needsClarification.run_id,
      question_id: needsClarification.clarification?.question_id,
      text: 'такая отвёртка, но на батарейках',
    })
    expect(search.result.value?.final_card?.code).toBe('26.20.10.000-00000001')

    const failing = {
      analyze: vi.fn(async () => needsClarification),
      clarify: vi.fn(async () => {
        throw new Error('LLM-роутер не настроен')
      }),
    }
    const guarded = useTextSearch(failing)
    await guarded.search('отвёртка')
    await guarded.clarifyText('что-то своё')
    expect(guarded.phase.value).toBe('done')
    expect(guarded.clarifyError.value).toBe('LLM-роутер не настроен')
    expect(guarded.result.value?.run_id).toBe(needsClarification.run_id)
  })

  it('refuses to clarify when the current result has no question', async () => {
    const api = {
      analyze: vi.fn(async () => analysis),
      clarify: vi.fn(async () => clarified),
    }
    const search = useTextSearch(api)
    await search.search('дрель')
    await search.clarify('opt-1')
    expect(search.phase.value).toBe('error')
    expect(api.clarify).not.toHaveBeenCalled()
  })

  it('refuses to clarify before any search', async () => {
    const api = {
      analyze: vi.fn(async () => analysis),
      clarify: vi.fn(async () => clarified),
    }
    const search = useTextSearch(api)
    await search.clarify('opt-1')
    expect(search.phase.value).toBe('error')
    expect(api.clarify).not.toHaveBeenCalled()
    expect(api.analyze).not.toHaveBeenCalled()
  })
})

describe('useTextSearch', () => {
  it('moves from searching to done and stores the result', async () => {
    const api = { analyze: vi.fn(async () => analysis), clarify: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    const running = search.search('дрель 18 В')
    expect(search.phase.value).toBe('searching')
    await running
    expect(search.phase.value).toBe('done')
    expect(search.result.value?.run_id).toBe('r1')
    expect(api.analyze).toHaveBeenCalledWith({ text: 'дрель 18 В', scope: 'all' })
  })

  it('passes the chosen scope to the backend', async () => {
    const api = { analyze: vi.fn(async () => analysis), clarify: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    await search.search('дрель', 'tools')
    expect(api.analyze).toHaveBeenCalledWith({ text: 'дрель', scope: 'tools' })
  })

  it('sends an explicit top_k only when the caller asks for an expanded search', async () => {
    const api = { analyze: vi.fn(async () => analysis), clarify: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    await search.search('дрель', 'all', 12)
    expect(api.analyze).toHaveBeenCalledWith({ text: 'дрель', scope: 'all', top_k: 12 })
    expect(api.analyze).toHaveBeenCalledTimes(1)
  })

  it('rejects an empty query without calling the backend', async () => {
    const api = { analyze: vi.fn(async () => analysis), clarify: vi.fn(async () => analysis) }
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
      clarify: vi.fn(async () => analysis),
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
      clarify: vi.fn(async () => analysis),
    }
    const search = useTextSearch(api)
    await search.search('дрель')
    expect(search.phase.value).toBe('error')
    expect(search.result.value?.run_id).toBe('partial')
  })

  it('reset returns the state to idle', async () => {
    const api = { analyze: vi.fn(async () => analysis), clarify: vi.fn(async () => analysis) }
    const search = useTextSearch(api)
    await search.search('дрель')
    search.reset()
    expect(search.phase.value).toBe('idle')
    expect(search.result.value).toBeNull()
  })
})
