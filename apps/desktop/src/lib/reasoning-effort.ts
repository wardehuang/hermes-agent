import { DEFAULT_REASONING_EFFORT, isReasoningEffort } from '@hermes/shared'

import { normalize } from '@/lib/text'

/** config.yaml hands back whatever the user wrote — `reasoning_effort: false`
 *  (or `off`/`no`, which YAML also parses to boolean false) means thinking
 *  disabled, and a bare boolean must not throw on `.trim()`. */
export function normalizeReasoningEffortValue(value: unknown): string {
  if (value === false) {
    return 'none'
  }

  if (typeof value !== 'string') {
    return ''
  }

  const effort = normalize(value)

  return effort === 'false' || effort === 'disabled' ? 'none' : effort
}

function overrideLookupKeys(model: string): string[] {
  const trimmed = model.trim()

  if (!trimmed) {
    return []
  }

  const lower = trimmed.toLowerCase()
  const slash = lower.lastIndexOf('/')
  const bare = slash >= 0 ? lower.slice(slash + 1) : lower
  const dashToDot = bare.replace(/(\d)-(\d)/g, '$1.$2')
  const dotToDash = bare.replace(/(\d)\.(\d)/g, '$1-$2')

  return [...new Set([trimmed, lower, bare, dashToDot, dotToDash])]
}

/** Per-model `agent.reasoning_overrides` match — spelling-tolerant like
 *  `hermes_constants.resolve_per_model_reasoning_effort` (exact, case, bare
 *  id, dots↔dashes). First lookup-key hit wins. */
export function matchingReasoningOverride(model: string, overrides: Record<string, string>): string {
  const folded = new Map<string, string>()

  for (const [key, raw] of Object.entries(overrides)) {
    const effort = normalizeReasoningEffortValue(raw)

    if (!effort) {
      continue
    }

    for (const alt of overrideLookupKeys(key)) {
      if (!folded.has(alt)) {
        folded.set(alt, effort)
      }
    }
  }

  for (const key of overrideLookupKeys(model)) {
    const effort = folded.get(key)

    if (effort) {
      return effort
    }
  }

  return ''
}

/** Effective effort for a model: user-pinned preset, then per-model override,
 *  then the profile's `agent.reasoning_effort`. */
export function resolveModelReasoningEffort(
  model: string,
  overrides: Record<string, string>,
  globalDefault: string,
  pinnedEffort?: string
): string {
  if (pinnedEffort) {
    return normalizeReasoningEffortValue(pinnedEffort)
  }

  return matchingReasoningOverride(model, overrides) || globalDefault
}

/** Compact labels for chrome where space is tight (pill, picker rows). Menus
 *  and settings use the translated `shell.modelOptions` strings instead. */
const SHORT_LABELS: Record<string, string> = {
  none: 'Off',
  minimal: 'Min',
  low: 'Low',
  medium: 'Med',
  high: 'High',
  xhigh: 'XHigh',
  max: 'Max',
  ultra: 'Ultra'
}

export function reasoningEffortLabel(effort: string): string {
  const key = normalize(effort)

  return key ? (SHORT_LABELS[key] ?? effort) : ''
}

/** Thinking is on unless a level explicitly says otherwise; an empty value
 *  means "inherit", so it resolves through `fallback` first. */
export const isThinkingEnabled = (effort: string, fallback: string = DEFAULT_REASONING_EFFORT): boolean =>
  normalize(effort || fallback) !== 'none'

/** The level a scale control should show. Empty inherits `fallback`; `none`
 *  (thinking off) selects nothing; anything unrecognized clamps to the default. */
export function resolveReasoningEffort(effort: string, fallback: string = DEFAULT_REASONING_EFFORT): string {
  const value = normalize(effort || fallback)

  if (value === 'none') {
    return ''
  }

  return isReasoningEffort(value) ? value : DEFAULT_REASONING_EFFORT
}
