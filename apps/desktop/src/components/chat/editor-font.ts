import { atom } from 'nanostores'

/** Empty config means the active theme's `--font-mono`. */
export const DEFAULT_EDITOR_FONT_FAMILY = 'var(--font-mono)'
export const DEFAULT_EDITOR_FONT_WEIGHT = '400'
export const DEFAULT_EDITOR_FONT_SIZE_CSS = '0.7rem'
export const DEFAULT_EDITOR_LINE_HEIGHT_CSS = '1.25rem'
/** Line box used by SourceView's windowed scroller when size is unset. */
export const DEFAULT_EDITOR_LINE_PX = 20
export const MIN_EDITOR_FONT_SIZE_PX = 8
export const MAX_EDITOR_FONT_SIZE_PX = 48

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

export interface ResolvedEditorFontSize {
  line: string
  linePx: number
  size: string
}

/** Profile-backed family as written in config.yaml. Empty means theme mono. */
export const $editorFontFamily = atom('')
/** Profile-backed size in px. 0 means the default 0.7rem / 1.25rem row. */
export const $editorFontSizePx = atom(0)

export function normalizeEditorFontFamily(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

/** 0 = unset (default rem size). Otherwise a clamped integer px. */
export function normalizeEditorFontSizePx(value: unknown): number {
  if (value == null || value === '') {
    return 0
  }

  const raw = typeof value === 'number' ? value : typeof value === 'string' ? Number.parseFloat(value.trim()) : Number.NaN

  if (!Number.isFinite(raw) || raw <= 0) {
    return 0
  }

  return Math.min(MAX_EDITOR_FONT_SIZE_PX, Math.max(MIN_EDITOR_FONT_SIZE_PX, Math.round(raw)))
}

function quoteSingleFamily(value: string): string {
  return JSON.stringify(value)
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

/**
 * Keep the current 0.7rem : 1.25rem row ratio (20px at a 16px root).
 * Explicit px sizes get an integer line box for SourceView's virtualizer.
 */
export function resolveEditorFontSize(value: unknown): ResolvedEditorFontSize {
  const px = normalizeEditorFontSizePx(value)

  if (!px) {
    return {
      line: DEFAULT_EDITOR_LINE_HEIGHT_CSS,
      linePx: DEFAULT_EDITOR_LINE_PX,
      size: DEFAULT_EDITOR_FONT_SIZE_CSS
    }
  }

  const linePx = Math.round((px * 25) / 14)

  return { line: `${linePx}px`, linePx, size: `${px}px` }
}

export function editorFontCss(
  family?: unknown,
  size?: unknown
): {
  fontFamily: string
  fontSize: string
  fontWeight: string
  lineHeight: string
  '--font-editor': string
  '--font-editor-line': string
  '--font-editor-size': string
  '--font-editor-weight': string
} {
  const font = resolveEditorFont(family)
  const sizing = resolveEditorFontSize(size ?? $editorFontSizePx.get())

  return {
    fontFamily: font.family,
    fontSize: sizing.size,
    fontWeight: font.weight,
    lineHeight: sizing.line,
    '--font-editor': font.family,
    '--font-editor-line': sizing.line,
    '--font-editor-size': sizing.size,
    '--font-editor-weight': font.weight
  }
}

function applyEditorFontToDocument(): void {
  if (typeof document === 'undefined') {
    return
  }

  const font = resolveEditorFont($editorFontFamily.get())
  const sizing = resolveEditorFontSize($editorFontSizePx.get())
  const root = document.documentElement
  root.style.setProperty('--font-editor', font.family)
  root.style.setProperty('--font-editor-weight', font.weight)
  root.style.setProperty('--font-editor-size', sizing.size)
  root.style.setProperty('--font-editor-line', sizing.line)

  if (document.fonts?.load) {
    void document.fonts.load(`${font.weight} ${sizing.size} ${font.family}`)
  }
}

export function setEditorFontFamilyFromConfig(value: unknown): void {
  $editorFontFamily.set(normalizeEditorFontFamily(value))
  applyEditorFontToDocument()
}

export function setEditorFontSizeFromConfig(value: unknown): void {
  $editorFontSizePx.set(normalizeEditorFontSizePx(value))
  applyEditorFontToDocument()
}
