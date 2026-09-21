import { DEFAULT_REASONING_EFFORT, REASONING_EFFORT_VALUES } from '@hermes/shared'
import { describe, expect, it } from 'vitest'

import {
  isThinkingEnabled,
  matchingReasoningOverride,
  reasoningEffortClamp,
  reasoningEffortLabel,
  resolveModelReasoningEffort,
  resolveReasoningEffort
} from './reasoning-effort'

describe('reasoning-effort', () => {
  it('labels every level it claims to support', () => {
    for (const effort of REASONING_EFFORT_VALUES) {
      expect(reasoningEffortLabel(effort)).not.toBe('')
    }

    expect(reasoningEffortLabel('')).toBe('')
    // Unknown values pass through rather than silently reading as a real level.
    expect(reasoningEffortLabel('bogus')).toBe('bogus')
  })

  it('labels a route clamp from the gateway wire level only, never by inference', () => {
    expect(reasoningEffortLabel('ultra', 'max')).toBe('Ultra→Max')
    expect(reasoningEffortClamp('ultra', 'max')).toEqual({ effort: 'ultra', wire: 'max' })
    // Unknown ('' — not stamped yet / optimistic pick) or verbatim: plain label, no claim.
    expect(reasoningEffortLabel('ultra', '')).toBe('Ultra')
    expect(reasoningEffortLabel('ultra')).toBe('Ultra')
    expect(reasoningEffortLabel('high', 'high')).toBe('High')
    expect(reasoningEffortClamp('high', 'high')).toBeNull()
    expect(reasoningEffortClamp('none', '')).toBeNull()
  })

  it('treats empty as inherit and only `none` as off', () => {
    expect(isThinkingEnabled('none')).toBe(false)
    expect(isThinkingEnabled('high')).toBe(true)
    // Empty inherits the fallback, so an off fallback reads as off.
    expect(isThinkingEnabled('', 'none')).toBe(false)
    expect(isThinkingEnabled('', 'high')).toBe(true)
  })

  it('resolves a scale value: inherit, off, or clamp', () => {
    expect(resolveReasoningEffort('high')).toBe('high')
    // Empty inherits the profile default rather than snapping to medium.
    expect(resolveReasoningEffort('', 'ultra')).toBe('ultra')
    // Off selects nothing on the scale.
    expect(resolveReasoningEffort('none')).toBe('')
    expect(resolveReasoningEffort('bogus')).toBe(DEFAULT_REASONING_EFFORT)
  })

  it('matches per-model reasoning overrides with spelling-tolerant keys', () => {
    const overrides = { 'grok-4.6': 'xhigh' }

    expect(matchingReasoningOverride('grok-4.6', overrides)).toBe('xhigh')
    expect(matchingReasoningOverride('Grok-4.6', overrides)).toBe('xhigh')
    expect(matchingReasoningOverride('cpa/grok-4.6', overrides)).toBe('xhigh')
    expect(matchingReasoningOverride('grok-4-6', overrides)).toBe('xhigh')
    expect(matchingReasoningOverride('gpt-5.6-luna', overrides)).toBe('')
  })

  it('prefers a user-pinned effort over the per-model override', () => {
    expect(resolveModelReasoningEffort('grok-4.6', { 'grok-4.6': 'xhigh' }, 'high', 'low')).toBe('low')
    expect(resolveModelReasoningEffort('grok-4.6', { 'grok-4.6': 'xhigh' }, 'high')).toBe('xhigh')
    expect(resolveModelReasoningEffort('gpt-5.6-luna', { 'grok-4.6': 'xhigh' }, 'high')).toBe('high')
  })
})
