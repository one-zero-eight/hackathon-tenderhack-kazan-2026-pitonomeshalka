import { computed, ref } from 'vue'
import type { AnalysisResponse } from '../api/types'

export interface BatchRow {
  id: number
  query: string
}

export type BatchItemStatus = 'pending' | 'searching' | 'done' | 'error'

export interface BatchItem {
  id: number
  query: string
  corrected: string | null
  spellFixed: boolean
  status: BatchItemStatus
  result: AnalysisResponse | null
  error: string | null
}

export interface BatchDeps {
  analyze: (text: string, signal: AbortSignal) => Promise<AnalysisResponse>
  correct: (text: string) => Promise<string | null>
}

export interface BatchOptions {
  retryCount?: number
  retryDelayMs?: number
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

function isBusyError(error: unknown): boolean {
  return (error as { status?: number } | null)?.status === 503
}

/**
 * Sequential batch runner for CSV rows: correct spelling, then analyze.
 * Finished rows land in `items` as soon as they are ready (streaming output).
 */
export function useCsvBatch(deps: BatchDeps, options: BatchOptions = {}) {
  const retryCount = options.retryCount ?? 1
  const retryDelayMs = options.retryDelayMs ?? 1000
  const items = ref<BatchItem[]>([])
  const running = ref(false)
  let stopped = false
  let controller: AbortController | null = null
  let finish: (() => void) | null = null
  let finished = Promise.resolve()

  const progress = computed(() => {
    const done = items.value.filter(
      (item) => item.status === 'done' || item.status === 'error',
    ).length
    return { done, total: items.value.length }
  })

  function start(rows: BatchRow[]): void {
    if (running.value) return
    items.value = rows.map((row) => ({
      id: row.id,
      query: row.query,
      corrected: null,
      spellFixed: false,
      status: 'pending',
      result: null,
      error: null,
    }))
    stopped = false
    controller = new AbortController()
    finished = new Promise<void>((resolve) => {
      finish = resolve
    })
    void run()
  }

  function cancel(): void {
    stopped = true
    controller?.abort()
  }

  async function run(): Promise<void> {
    running.value = true
    for (const item of items.value) {
      if (stopped) break
      if (item.status !== 'pending') continue
      await processItem(item)
    }
    running.value = false
    finish?.()
  }

  async function processItem(item: BatchItem): Promise<void> {
    item.status = 'searching'
    let text = item.query
    try {
      const corrected = await deps.correct(text)
      if (corrected) {
        text = corrected
        item.corrected = corrected
        item.spellFixed = corrected !== item.query
      }
    } catch {
      item.corrected = null
      item.spellFixed = false
    }
    let attempts = 0
    for (;;) {
      try {
        const signal = controller?.signal ?? new AbortController().signal
        item.result = await deps.analyze(text, signal)
        item.status = 'done'
        return
      } catch (cause) {
        attempts += 1
        if (stopped || attempts > retryCount || !isBusyError(cause)) {
          item.status = 'error'
          item.error = cause instanceof Error ? cause.message : String(cause)
          return
        }
        await sleep(retryDelayMs)
      }
    }
  }

  return {
    items,
    running,
    progress,
    start,
    cancel,
    get done() {
      return finished
    },
  }
}
