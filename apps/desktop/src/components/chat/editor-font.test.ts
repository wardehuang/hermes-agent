import { describe, expect, it } from 'vitest'

import {
  DEFAULT_EDITOR_FONT_FAMILY,
  DEFAULT_EDITOR_FONT_WEIGHT,
  resolveEditorFont,
  resolveEditorFontFamily
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
      family: `'Operator Mono Light', 'Operator Mono', ${DEFAULT_EDITOR_FONT_FAMILY}`,
      weight: '300'
    })
  })

  it('quotes a family with no face suffix at regular weight', () => {
    expect(resolveEditorFontFamily('JetBrains Mono')).toBe(`'JetBrains Mono', ${DEFAULT_EDITOR_FONT_FAMILY}`)
    expect(resolveEditorFont('JetBrains Mono').weight).toBe('400')
  })

  it('preserves an authored CSS stack before the theme fallback', () => {
    expect(resolveEditorFontFamily("'Hack Nerd Font', monospace")).toBe(
      `'Hack Nerd Font', monospace, ${DEFAULT_EDITOR_FONT_FAMILY}`
    )
  })
})
