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
  return keys
    .map(key => record[key])
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
}

function extraPublicUrl(record: Record<string, unknown>): string | null {
  const extra = record.extra

  if (!extra || typeof extra !== 'object' || Array.isArray(extra)) {
    return null
  }

  const publicUrl = (extra as Record<string, unknown>).public_url

  return typeof publicUrl === 'string' && publicUrl.trim() ? publicUrl : null
}

/** Display source for a completed `video_generate` result. Prose is left alone. */
export function generatedVideoFromResult(result: unknown): string | null {
  const record = recordFromUnknown(result)

  if (!record || record.success === false) {
    return null
  }

  const primary = stringFields(record, ['video'])[0]

  if (primary) {
    return primary
  }

  return extraPublicUrl(record)
}
