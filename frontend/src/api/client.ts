import type { FetchLike } from '../lib/fetch-like'
import { normalizeAnalysis } from './normalize'
import type {
  AnalysisRequest,
  AnalysisResponse,
  HealthPayload,
  HistoryResponse,
  PreviewResponse,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly partialResult: AnalysisResponse | null

  constructor(message: string, status: number, partialResult: AnalysisResponse | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.partialResult = partialResult
  }
}

export interface ApiClientOptions {
  baseUrl?: string
  fetch?: FetchLike
}

interface AnalysisJob {
  run_id: string
  status: 'running' | 'completed' | 'failed'
  result: AnalysisResponse | null
  error: string | null
}

function waitForPoll(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted()
    const abort = () => {
      clearTimeout(timer)
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, 2000)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

function defaultBaseUrl(): string {
  return import.meta.env.VITE_API_BASE ?? '/api'
}

function extractMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : ''))
      .filter(Boolean)
    return messages.length > 0 ? messages.join('; ') : null
  }
  if (detail && typeof detail === 'object' && 'error' in detail) {
    return String((detail as { error: unknown }).error)
  }
  return null
}

function extractPartial(detail: unknown): AnalysisResponse | null {
  if (detail && typeof detail === 'object' && 'result' in detail) {
    const result = (detail as { result: unknown }).result
    if (result && typeof result === 'object') {
      return normalizeAnalysis(result as AnalysisResponse)
    }
  }
  return null
}

async function toApiError(response: Response): Promise<ApiError> {
  const text = await response.text().catch(() => '')
  const detail = parseDetail(text)
  const message = extractMessage(detail) ?? `HTTP ${response.status}`
  return new ApiError(message, response.status, extractPartial(detail))
}

function parseDetail(text: string): unknown {
  try {
    const payload = text ? JSON.parse(text) : null
    return (payload as { detail?: unknown } | null)?.detail
  } catch {
    return null
  }
}

/** Typed browser client for the KTRU backend; dev calls go through the /api proxy. */
export class KtruApiClient {
  private readonly baseUrl: string
  private readonly fetchImpl: FetchLike

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? defaultBaseUrl()).replace(/\/+$/, '')
    this.fetchImpl = options.fetch ?? ((url, init) => fetch(url, init))
  }

  async analyze(request: AnalysisRequest, signal?: AbortSignal): Promise<AnalysisResponse> {
    const job = await this.request<AnalysisJob>('analyses', request, signal)
    return this.waitForAnalysis(job.run_id, signal)
  }

  /** Resume polling an accepted run; never submit duplicate GPU work on a fetch failure. */
  async waitForAnalysis(runId: string, signal?: AbortSignal): Promise<AnalysisResponse> {
    let failures = 0
    for (;;) {
      signal?.throwIfAborted()
      let job: AnalysisJob
      try {
        const response = await this.fetchImpl(
          `${this.baseUrl}/analyses/${encodeURIComponent(runId)}`,
          { method: 'GET', signal, cache: 'no-store' },
        )
        if (!response.ok) throw await toApiError(response)
        job = (await response.json()) as AnalysisJob
        failures = 0
      } catch (error) {
        signal?.throwIfAborted()
        if (error instanceof ApiError && error.status < 500) throw error
        if (++failures >= 3) {
          throw new ApiError(
            `Connection lost while checking analysis ${runId}. Resume polling this run to recover its result.`,
            0,
          )
        }
        await waitForPoll(signal)
        continue
      }
      const result = job.result ? normalizeAnalysis(job.result) : null
      if (job.status === 'failed') {
        throw new ApiError(job.error ?? 'Analysis failed', 502, result)
      }
      if (job.status === 'completed') {
        if (!result) throw new ApiError(`Analysis ${runId} completed without a saved result`, 502)
        return result
      }
      await waitForPoll(signal)
    }
  }

  preview(request: AnalysisRequest, signal?: AbortSignal): Promise<PreviewResponse> {
    return this.request('preview', request, signal)
  }

  async health(signal?: AbortSignal): Promise<HealthPayload> {
    const response = await this.fetchImpl(`${this.baseUrl}/health`, { method: 'GET', signal })
    if (!response.ok) throw await toApiError(response)
    return (await response.json()) as HealthPayload
  }

  async getHistory(sessionId: string, signal?: AbortSignal): Promise<HistoryResponse> {
    const response = await this.fetchImpl(
      `${this.baseUrl}/history/${encodeURIComponent(sessionId)}`,
      { method: 'GET', signal },
    )
    if (!response.ok) throw await toApiError(response)
    return (await response.json()) as HistoryResponse
  }

  async addHistory(sessionId: string, query: string, signal?: AbortSignal): Promise<void> {
    await this.fetchImpl(`${this.baseUrl}/history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, query }),
      signal,
    })
  }

  private async request<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
    if (!response.ok) throw await toApiError(response)
    return (await response.json()) as T
  }
}
