type ToolLike = {
  result?: unknown
  toolName?: unknown
  type?: unknown
}

type TextLike = {
  text?: unknown
  type?: unknown
}

// Path-ish result fields the model may echo into its prose. Display prefers the
// primary `video` field (URL or absolute path); stripping also catches public /
// temporary / rematerialized variants so a restated remote link does not double.
const DISPLAY_KEYS = ['video'] as const
const ECHO_KEYS = ['video'] as const
const EXTRA_ECHO_KEYS = ['public_url', 'temporary_url', 'remote_url'] as const

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }

  if (typeof value !== 'string' || !value.trim()) {
    return null
  }

  try {
    const parsed = JSON.parse(value)

    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function stringFields(record: Record<string, unknown>, keys: readonly string[]): string[] {
  return keys.map(key => record[key]).filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
}

function extraEchoFields(record: Record<string, unknown>): string[] {
  const extra = record.extra

  if (!extra || typeof extra !== 'object' || Array.isArray(extra)) {
    return []
  }

  return stringFields(extra as Record<string, unknown>, EXTRA_ECHO_KEYS)
}

function regexEscape(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))]
}

function videoResult(part: ToolLike): Record<string, unknown> | null {
  if (part.type !== 'tool-call' || part.toolName !== 'video_generate') {
    return null
  }

  const record = recordFromUnknown(part.result)

  return record && record.success !== false ? record : null
}

/** Display source for a completed `video_generate` result. */
export function generatedVideoFromResult(result: unknown): string | null {
  const record = recordFromUnknown(result)

  if (!record || record.success === false) {
    return null
  }

  const primary = stringFields(record, DISPLAY_KEYS)[0]

  if (primary) {
    return primary
  }

  return extraEchoFields(record)[0] ?? null
}

/** Every path/URL a generated video might appear as in prose, for de-duping. */
export function generatedVideoEchoSources(parts: readonly ToolLike[]): string[] {
  return unique(
    parts.flatMap(part => {
      const record = videoResult(part)

      if (!record) {
        return []
      }

      return [...stringFields(record, ECHO_KEYS), ...extraEchoFields(record)]
    })
  )
}

/** Strip a generated video out of prose so it only ever shows in the tool slot. */
export function stripGeneratedVideoEchoes(text: string, sources: readonly string[]): string {
  if (!text || sources.length === 0) {
    return text
  }

  let next = text.replace(/!\[[^\]\n]*\]\([^)\n]*\)/g, '').replace(/\[[^\]\n]*\]\(\s*#media:[^)\n]*\)/g, '')

  for (const source of unique([...sources])) {
    next = next.replace(new RegExp(String.raw`(^|[\s([{])<?${regexEscape(source)}>?(?=$|[\s)\]},.!?])`, 'g'), '$1')
  }

  return next
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()
}

/** Strip generated-video echoes from text parts, dropping any part left empty. */
export function dedupeGeneratedVideoEchoesInParts<T extends TextLike & ToolLike>(parts: readonly T[]): T[] {
  const sources = generatedVideoEchoSources(parts)

  if (!sources.length) {
    return [...parts]
  }

  return parts
    .map(part =>
      part.type === 'text' && typeof part.text === 'string'
        ? { ...part, text: stripGeneratedVideoEchoes(part.text, sources) }
        : part
    )
    .filter(part => part.type !== 'text' || (typeof part.text === 'string' && part.text.trim().length > 0))
}
