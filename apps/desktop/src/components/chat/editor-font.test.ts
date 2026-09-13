import { describe, expect, it } from 'vitest'

import {
  DEFAULT_EDITOR_FONT_FAMILY,
  DEFAULT_EDITOR_FONT_SIZE_CSS,
  DEFAULT_EDITOR_FONT_WEIGHT,
  DEFAULT_EDITOR_LINE_HEIGHT_CSS,
  DEFAULT_EDITOR_LINE_PX,
  normalizeEditorFontSizePx,
  resolveEditorFont,
  resolveEditorFontFamily,
  resolveEditorFontSize
} from './editor-font'

describe('editor font resolution', () => {
  it('keeps the theme mono stack when no preference is configured', () => {
    expect(resolveEditorFont('')).toEqual({
      family: DEFAULT_EDITOR_FONT_FAMILY,
      weight: DEFAULT_EDITOR_FONT_WEIGHT
    })
    expect(resolveEditorFont(undefined)).toEqual({
      family: DEFAULT_EDITOR_FONT_FAMILY,
      weight: DEFAULT_EDITOR_FONT_WEIGHT
    })
  })

  it('maps Operator Mono Light to the typographic family plus weight 300', () => {
    expect(resolveEditorFont('  Operator Mono Light  ')).toEqual({
      family: `${JSON.stringify('Operator Mono Light')}, ${JSON.stringify('Operator Mono')}, ${DEFAULT_EDITOR_FONT_FAMILY}`,
      weight: '300'
    })
  })

  it('quotes a family with no face suffix at regular weight', () => {
    expect(resolveEditorFontFamily('JetBrains Mono')).toBe(`${JSON.stringify('JetBrains Mono')}, ${DEFAULT_EDITOR_FONT_FAMILY}`)
    expect(resolveEditorFont('JetBrains Mono').weight).toBe('400')
  })

  it('preserves an authored CSS stack before the theme fallback', () => {
    expect(resolveEditorFontFamily("'Hack Nerd Font', monospace")).toBe(
      `'Hack Nerd Font', monospace, ${DEFAULT_EDITOR_FONT_FAMILY}`
    )
  })
})

describe('editor font size', () => {
  it('treats empty and 0 as the default rem size', () => {
    expect(normalizeEditorFontSizePx('')).toBe(0)
    expect(normalizeEditorFontSizePx(0)).toBe(0)
    expect(resolveEditorFontSize(undefined)).toEqual({
      line: DEFAULT_EDITOR_LINE_HEIGHT_CSS,
      linePx: DEFAULT_EDITOR_LINE_PX,
      size: DEFAULT_EDITOR_FONT_SIZE_CSS
    })
  })

  it('clamps and rounds px, keeping the 0.7rem:1.25rem row ratio', () => {
    expect(normalizeEditorFontSizePx(12)).toBe(12)
    expect(normalizeEditorFontSizePx('14px')).toBe(14)
    expect(normalizeEditorFontSizePx(7)).toBe(8)
    expect(normalizeEditorFontSizePx(99)).toBe(48)
    expect(resolveEditorFontSize(14)).toEqual({ line: '25px', linePx: 25, size: '14px' })
  })
})
