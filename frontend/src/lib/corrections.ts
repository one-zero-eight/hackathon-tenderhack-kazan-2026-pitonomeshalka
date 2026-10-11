/** One LanguageTool issue, with offsets counted in UTF-16 code units (JS-native). */
export interface SpellMatch {
  offset: number
  length: number
  errorText: string
  message: string
  shortMessage: string
  replacements: string[]
  ruleId: string
  category: string
  issueType: string
}

/** Applies the first replacement of every non-overlapping match, right to left. */
export function applyAllCorrections(text: string, matches: SpellMatch[]): string {
  let result = text
  let boundary = text.length
  const ordered = [...matches].sort((a, b) => b.offset - a.offset)
  for (const m of ordered) {
    const replacement = m.replacements[0]
    const end = m.offset + m.length
    if (!replacement || m.offset < 0 || end > boundary || end > text.length) continue
    result = result.slice(0, m.offset) + replacement + result.slice(end)
    boundary = m.offset
  }
  return result
}

/** Replaces a single match range with the chosen suggestion. */
export function applyReplacement(text: string, match: SpellMatch, replacement: string): string {
  const end = match.offset + match.length
  if (!replacement || match.offset < 0 || end > text.length) return text
  return text.slice(0, match.offset) + replacement + text.slice(end)
}
