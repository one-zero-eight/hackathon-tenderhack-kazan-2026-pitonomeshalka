import { ref } from 'vue'
import type { AnalysisRequest, AnalysisResponse, AnalysisScope, ClarifyRequest } from '../api/types'

export interface TextSearchClient {
  analyze(request: AnalysisRequest): Promise<AnalysisResponse>
  clarify(request: ClarifyRequest): Promise<AnalysisResponse>
}

export type SearchPhase = 'idle' | 'searching' | 'done' | 'error'

const NO_CLARIFICATION_MESSAGE = 'Нет вопроса для уточнения'

/** Single-query search state: idle → searching → done/error. */
export function useTextSearch(client: TextSearchClient) {
  const phase = ref<SearchPhase>('idle')
  const result = ref<AnalysisResponse | null>(null)
  const error = ref<string | null>(null)

  async function search(text: string, scope: AnalysisScope = 'all', topK?: number): Promise<void> {
    if (!text.trim()) {
      phase.value = 'error'
      error.value = 'Введите описание товара'
      return
    }
    phase.value = 'searching'
    error.value = null
    const request: AnalysisRequest = { text, scope }
    if (topK !== undefined) request.top_k = topK
    try {
      result.value = await client.analyze(request)
      phase.value = 'done'
    } catch (cause) {
      const partial = (cause as { partialResult?: AnalysisResponse } | null)?.partialResult
      result.value = partial ?? null
      error.value = cause instanceof Error ? cause.message : String(cause)
      phase.value = 'error'
    }
  }

  /** Answers the current clarification question; keeps the same state machine as search. */
  async function clarify(optionId: string): Promise<void> {
    const current = result.value
    if (!current?.clarification) {
      phase.value = 'error'
      error.value = NO_CLARIFICATION_MESSAGE
      return
    }
    phase.value = 'searching'
    error.value = null
    try {
      result.value = await client.clarify({
        run_id: current.run_id,
        question_id: current.clarification.question_id,
        option_id: optionId,
      })
      phase.value = 'done'
    } catch (cause) {
      const partial = (cause as { partialResult?: AnalysisResponse } | null)?.partialResult
      result.value = partial ?? null
      error.value = cause instanceof Error ? cause.message : String(cause)
      phase.value = 'error'
    }
  }

  function reset(): void {
    phase.value = 'idle'
    result.value = null
    error.value = null
  }

  return { phase, result, error, search, clarify, reset }
}
