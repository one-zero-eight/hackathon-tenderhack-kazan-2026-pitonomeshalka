import type { SpellMatch } from './corrections'
import type { FetchLike } from './fetch-like'

export interface CheckOutcome {
  text: string
  language: string
  matches: SpellMatch[]
}

export class LanguageToolError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LanguageToolError'
  }
}

interface RawMatch {
  message?: string
  shortMessage?: string
  offset?: number
  length?: number
  replacements?: { value: string }[]
  rule?: { id?: string; issueType?: string; category?: { id?: string } }
}

interface RawResponse {
  matches?: RawMatch[]
  language?: { code?: string }
}

export interface LanguageToolOptions {
  baseUrl?: string
  language?: string
  level?: string
  timeoutMs?: number
  fetch?: FetchLike
}

function defaultBaseUrl(): string {
  return import.meta.env.VITE_LANGUAGETOOL_BASE ?? '/lt'
}

/** HTTP client for a LanguageTool server (POST /v2/check, form-encoded). */
export class LanguageToolClient {
  private readonly baseUrl: string
  private readonly language: string
  private readonly level: string
  private readonly timeoutMs: number
  private readonly fetchImpl: FetchLike

  constructor(options: LanguageToolOptions = {}) {
    this.baseUrl = (options.baseUrl ?? defaultBaseUrl()).replace(/\/+$/, '')
    this.language = options.language ?? 'ru-RU'
    this.level = options.level ?? 'default'
    this.timeoutMs = options.timeoutMs ?? 15000
    this.fetchImpl = options.fetch ?? ((url, init) => fetch(url, init))
  }

  async check(text: string): Promise<CheckOutcome> {
    if (!text.trim()) return { text, language: this.language, matches: [] }
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/v2/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ text, language: this.language, level: this.level }).toString(),
        signal: controller.signal,
      })
      if (!response.ok) throw new LanguageToolError(`LanguageTool HTTP ${response.status}`)
      const payload = (await response.json()) as RawResponse
      return {
        text,
        language: payload.language?.code ?? this.language,
        matches: (payload.matches ?? []).map((raw) => toMatch(raw, text)),
      }
    } catch (cause) {
      if (cause instanceof LanguageToolError) throw cause
      const reason = cause instanceof Error ? cause.message : String(cause)
      throw new LanguageToolError(`LanguageTool недоступен: ${reason}`)
    } finally {
      clearTimeout(timer)
    }
  }
}

function toMatch(raw: RawMatch, text: string): SpellMatch {
  const offset = raw.offset ?? 0
  const length = raw.length ?? 0
  return {
    offset,
    length,
    errorText: text.slice(offset, offset + length),
    message: raw.message ?? '',
    shortMessage: raw.shortMessage ?? '',
    replacements: (raw.replacements ?? []).map((r) => r.value),
    ruleId: raw.rule?.id ?? '',
    category: raw.rule?.category?.id ?? '',
    issueType: raw.rule?.issueType ?? '',
  }
}
