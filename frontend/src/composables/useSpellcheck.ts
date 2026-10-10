import { ref } from 'vue'
import { applyAllCorrections, applyReplacement, type SpellMatch } from '../lib/corrections'

export interface CheckOutcome {
  text: string
  language: string
  matches: SpellMatch[]
}

/** Structural type satisfied by LanguageToolClient; kept injectable for tests. */
export interface SpellcheckClient {
  check(text: string): Promise<CheckOutcome>
}

export interface SpellcheckOptions {
  debounceMs?: number
  minLength?: number
}

/** Debounced spellcheck state for live text input, with correction helpers. */
export function useSpellcheck(client: SpellcheckClient, options: SpellcheckOptions = {}) {
  const debounceMs = options.debounceMs ?? 300
  const minLength = options.minLength ?? 3
  const matches = ref<SpellMatch[]>([])
  const checkedText = ref('')
  const checking = ref(false)
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | undefined
  let token = 0

  function scheduleCheck(text: string): void {
    clearTimeout(timer)
    if (text.trim().length < minLength) {
      token += 1
      matches.value = []
      checkedText.value = ''
      checking.value = false
      return
    }
    timer = setTimeout(() => {
      void runCheck(text)
    }, debounceMs)
  }

  async function runCheck(text: string): Promise<void> {
    checking.value = true
    error.value = null
    const current = ++token
    try {
      const outcome = await client.check(text)
      if (current !== token) return
      matches.value = outcome.matches
      checkedText.value = text
    } catch (cause) {
      if (current !== token) return
      matches.value = []
      checkedText.value = ''
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      if (current === token) checking.value = false
    }
  }

  function applyAll(): string {
    return applyAllCorrections(checkedText.value, matches.value)
  }

  function applyOne(index: number, replacement: string): string {
    const target = matches.value[index]
    if (!target) return checkedText.value
    return applyReplacement(checkedText.value, target, replacement)
  }

  return { matches, checkedText, checking, error, scheduleCheck, applyAll, applyOne }
}
