const DELIMITERS = [';', ',', '\t'] as const
export type Delimiter = (typeof DELIMITERS)[number]

export interface CsvTable {
  headers: string[]
  rows: string[][]
}

function countOutsideQuotes(sample: string, delimiter: string): number {
  let count = 0
  let inQuotes = false
  for (const ch of sample) {
    if (ch === '"') inQuotes = !inQuotes
    else if (ch === delimiter && !inQuotes) count += 1
  }
  return count
}

/** Picks the delimiter that occurs most often outside quotes in the first lines. */
export function detectDelimiter(text: string): Delimiter {
  const sample = text.split(/\r?\n/).slice(0, 5).join('\n')
  let best: Delimiter = ';'
  let bestCount = -1
  for (const delimiter of DELIMITERS) {
    const count = countOutsideQuotes(sample, delimiter)
    if (count > bestCount) {
      best = delimiter
      bestCount = count
    }
  }
  return best
}

/** RFC 4180-style parser: quoted fields, escaped quotes, CRLF, BOM, empty lines. */
export function parseCsv(input: string): string[][] {
  const text = input.replace(/^\uFEFF/, '')
  const delimiter = detectDelimiter(text)
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false
  let i = 0
  while (i < text.length) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i += 2
        } else {
          inQuotes = false
          i += 1
        }
      } else {
        field += ch
        i += 1
      }
      continue
    }
    if (ch === '"') {
      inQuotes = true
      i += 1
    } else if (ch === delimiter) {
      row.push(field)
      field = ''
      i += 1
    } else if (ch === '\n' || ch === '\r') {
      i += ch === '\r' && text[i + 1] === '\n' ? 2 : 1
      row.push(field)
      field = ''
      pushRow(rows, row)
      row = []
    } else {
      field += ch
      i += 1
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    pushRow(rows, row)
  }
  return rows
}

function pushRow(rows: string[][], row: string[]): void {
  const blank = row.every((cell) => cell === '')
  if (!blank) rows.push(row)
}

export function parseTable(input: string): CsvTable {
  const rows = input
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => [line])
  return { headers: [], rows }
}
