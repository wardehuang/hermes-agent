import { atom } from 'nanostores'

/** Empty config means the active theme's `--font-mono`. */
export const DEFAULT_EDITOR_FONT_FAMILY = 'var(--font-mono)'

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

/** Profile-backed value as written in config.yaml. Empty means theme mono. */
export const $editorFontFamily = atom('')

export function normalizeEditorFontFamily(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function quoteSingleFamily(value: string): string {
  return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}

/** Accept a friendly single family name or an authored CSS font stack. */
export function resolveEditorFontFamily(value: unknown): string {
  const configured = normalizeEditorFontFamily(value)

  if (!configured) {
    return DEFAULT_EDITOR_FONT_FAMILY
  }

  const preferred = configured.includes(',') || /['"]/.test(configured) ? configured : quoteSingleFamily(configured)

  return `${preferred}, ${DEFAULT_EDITOR_FONT_FAMILY}`
}

export function setEditorFontFamilyFromConfig(value: unknown): void {
  $editorFontFamily.set(normalizeEditorFontFamily(value))
}
