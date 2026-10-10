import { ref } from 'vue'
import type { AnalysisRequest, AnalysisResponse, AnalysisScope } from '../api/types'

export interface TextSearchClient {
  analyze(request: AnalysisRequest): Promise<AnalysisResponse>
}

export type SearchPhase = 'idle' | 'searching' | 'done' | 'error'

/** Single-query search state: idle → searching → done/error. */
export function useTextSearch(client: TextSearchClient) {
  const phase = ref<SearchPhase>('idle')
  const result = ref<AnalysisResponse | null>(null)
  const error = ref<string | null>(null)

  async function search(text: string, scope: AnalysisScope = 'all'): Promise<void> {
    if (!text.trim()) {
      phase.value = 'error'
      error.value = 'Введите описание товара'
      return
    }
    phase.value = 'searching'
    error.value = null
    try {
      result.value = await client.analyze({ text, scope })
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

  return { phase, result, error, search, reset }
}
