import { atom } from 'nanostores'

/** Empty config means the active theme's `--font-mono`. */
export const DEFAULT_EDITOR_FONT_FAMILY = 'var(--font-mono)'
export const DEFAULT_EDITOR_FONT_WEIGHT = '400'

export const EDITOR_FONT_SUGGESTIONS = [
  'Operator Mono Light',
  'Operator Mono',
  'JetBrains Mono',
  'SF Mono',
  'Cascadia Code',
  'Fira Code',
  'IBM Plex Mono',
  'Source Code Pro',
  'Menlo',
  'Consolas'
] as const

export interface ResolvedEditorFont {
  family: string
  weight: string
}

/** Profile-backed value as written in config.yaml. Empty means theme mono. */
export const $editorFontFamily = atom('')

export function normalizeEditorFontFamily(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function quoteSingleFamily(value: string): string {
  return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}

/**
 * Windows GDI registers each Operator Mono face as its own family
 * (`Operator Mono Light`) while Chromium/DirectWrite matches the typographic
 * family (`Operator Mono`) plus weight. Keep both names in the stack.
 */
const FACE_WEIGHTS: Array<{ pattern: RegExp; weight: string }> = [
  { pattern: /\s+(?:extra[\s-]*light|ultra[\s-]*light|x[\s-]*light)$/i, weight: '200' },
  { pattern: /\s+thin$/i, weight: '100' },
  { pattern: /\s+light$/i, weight: '300' },
  { pattern: /\s+book$/i, weight: '400' },
  { pattern: /\s+(?:regular|roman)$/i, weight: '400' },
  { pattern: /\s+medium$/i, weight: '500' },
  { pattern: /\s+(?:semi[\s-]*bold|demi[\s-]*bold)$/i, weight: '600' },
  { pattern: /\s+(?:extra[\s-]*bold|ultra[\s-]*bold)$/i, weight: '800' },
  { pattern: /\s+(?:black|heavy)$/i, weight: '900' },
  { pattern: /\s+bold$/i, weight: '700' }
]

export function resolveEditorFont(value: unknown): ResolvedEditorFont {
  const configured = normalizeEditorFontFamily(value)

  if (!configured) {
    return { family: DEFAULT_EDITOR_FONT_FAMILY, weight: DEFAULT_EDITOR_FONT_WEIGHT }
  }

  if (configured.includes(',') || /['"]/.test(configured)) {
    return { family: `${configured}, ${DEFAULT_EDITOR_FONT_FAMILY}`, weight: DEFAULT_EDITOR_FONT_WEIGHT }
  }

  let weight = DEFAULT_EDITOR_FONT_WEIGHT
  let typographic = configured

  for (const face of FACE_WEIGHTS) {
    const match = configured.match(face.pattern)

    if (match?.index != null) {
      weight = face.weight
      typographic = configured.slice(0, match.index).trim()
      break
    }
  }

  const preferred = quoteSingleFamily(configured)

  if (typographic && typographic.toLowerCase() !== configured.toLowerCase()) {
    return {
      family: `${preferred}, ${quoteSingleFamily(typographic)}, ${DEFAULT_EDITOR_FONT_FAMILY}`,
      weight
    }
  }

  return { family: `${preferred}, ${DEFAULT_EDITOR_FONT_FAMILY}`, weight }
}

/** Accept a friendly single family name or an authored CSS font stack. */
export function resolveEditorFontFamily(value: unknown): string {
  return resolveEditorFont(value).family
}

export function editorFontCss(value: unknown): {
  fontFamily: string
  fontWeight: string
  '--font-editor': string
  '--font-editor-weight': string
} {
  const font = resolveEditorFont(value)

  return {
    fontFamily: font.family,
    fontWeight: font.weight,
    '--font-editor': font.family,
    '--font-editor-weight': font.weight
  }
}

function applyEditorFontToDocument(font: ResolvedEditorFont): void {
  if (typeof document === 'undefined') {
    return
  }

  const root = document.documentElement
  root.style.setProperty('--font-editor', font.family)
  root.style.setProperty('--font-editor-weight', font.weight)

  if (document.fonts?.load) {
    void document.fonts.load(`${font.weight} 12px ${font.family}`)
  }
}

export function setEditorFontFamilyFromConfig(value: unknown): void {
  const normalized = normalizeEditorFontFamily(value)
  $editorFontFamily.set(normalized)
  applyEditorFontToDocument(resolveEditorFont(normalized))
}
