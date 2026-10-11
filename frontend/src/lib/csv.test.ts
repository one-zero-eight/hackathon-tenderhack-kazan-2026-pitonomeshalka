import { describe, expect, it } from 'vitest'
import { parseCsv, parseTable } from './csv'

describe('parseCsv', () => {
  it('auto-detects the semicolon delimiter', () => {
    expect(parseCsv('a;b\nc;d')).toEqual([
      ['a', 'b'],
      ['c', 'd'],
    ])
  })

  it('auto-detects the comma delimiter', () => {
    expect(parseCsv('a,b\nc,d')).toEqual([
      ['a', 'b'],
      ['c', 'd'],
    ])
  })

  it('prefers the delimiter that occurs more often', () => {
    expect(parseCsv('a,b,c;d\ne,f,g;h')).toEqual([
      ['a', 'b', 'c;d'],
      ['e', 'f', 'g;h'],
    ])
  })

  it('keeps quoted delimiters and newlines inside a field', () => {
    expect(parseCsv('"a;b";"line1\nline2"')).toEqual([['a;b', 'line1\nline2']])
  })

  it('unescapes doubled quotes', () => {
    expect(parseCsv('"he said ""hi"""')).toEqual([['he said "hi"']])
  })

  it('strips the BOM and handles CRLF line endings', () => {
    expect(parseCsv('\ufeffname;qty\r\nболт;10\r\n')).toEqual([
      ['name', 'qty'],
      ['болт', '10'],
    ])
  })

  it('skips empty lines between records', () => {
    expect(parseCsv('a;b\n\nc;d\n')).toEqual([
      ['a', 'b'],
      ['c', 'd'],
    ])
  })

  it('returns an empty list for blank input', () => {
    expect(parseCsv('')).toEqual([])
  })
})

describe('parseTable', () => {
  it('treats every non-empty physical line as a complete description', () => {
    const table = parseTable('дрель,КИТАЙ,Вес 900 г\nнасос,РОССИЯ,Мощность 500 Вт\n')
    expect(table.rows).toEqual([['дрель,КИТАЙ,Вес 900 г'], ['насос,РОССИЯ,Мощность 500 Вт']])
  })

  it('keeps a single physical line intact', () => {
    const table = parseTable('болт М10 оцинкованный,10,шт')
    expect(table.rows).toEqual([['болт М10 оцинкованный,10,шт']])
  })

  it('trims lines and skips blank ones', () => {
    const table = parseTable('  первая строка  \n\n  вторая строка\r\n')
    expect(table.rows).toEqual([['первая строка'], ['вторая строка']])
  })
})
