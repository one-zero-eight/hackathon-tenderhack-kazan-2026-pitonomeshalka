import { KtruApiClient } from './api/client'
import { applyAllCorrections } from './lib/corrections'
import { LanguageToolClient } from './lib/languagetool'

/** Shared singletons wired to the dev proxies (/api, /lt); tests inject fakes instead. */
export const api = new KtruApiClient()
export const lt = new LanguageToolClient()

/** Auto-applies LanguageTool corrections; throws when the service is unreachable. */
export async function spellCorrect(text: string): Promise<string> {
  const outcome = await lt.check(text)
  return applyAllCorrections(text, outcome.matches)
}
