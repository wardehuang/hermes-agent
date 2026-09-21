import { type MutableRefObject, useCallback, useRef, useState } from 'react'

import { setTerminalFontFamilyFromConfig } from '@/app/right-sidebar/terminal/terminal-font'
import { setEditorFontFamilyFromConfig, setEditorFontSizeFromConfig } from '@/components/chat/editor-font'
import { getHermesConfig, getHermesConfigDefaults } from '@/hermes'
import { BUILTIN_PERSONALITIES, normalizePersonalityValue, personalityNamesFromConfig } from '@/lib/chat-runtime'
import { normalizeReasoningEffortValue } from '@/lib/reasoning-effort'
import { setDisplayTimestampsFromConfig } from '@/store/display-timestamps'
import { composerEffortForSelection } from '@/store/model-presets'
import { setShowReasoningFromConfig } from '@/store/reasoning-disclosure'
import {
  $currentModel,
  $currentProvider,
  getComposerSelectionGeneration,
  getCurrentModelSource,
  setAvailablePersonalities,
  setCurrentFastMode,
  setCurrentPersonality,
  setCurrentReasoningEffort,
  setCurrentServiceTier,
  setDefaultReasoningEffort,
  setIntroPersonality,
  setReasoningOverrides
} from '@/store/session'
import { refreshVoiceLiveStatus } from '@/store/voice-live'
import {
  applyAutoSpeakFromConfig,
  applyThinkingSoundFromConfig,
  applyVoiceStopPhraseFromConfig
} from '@/store/voice-prefs'
import { setChatFontFamilyFromConfig } from '@/themes/chat-font'

const DEFAULT_VOICE_SECONDS = 120
const FAST_TIERS = new Set(['fast', 'priority', 'on'])

function recordingLimit(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : DEFAULT_VOICE_SECONDS
}

function normalizeReasoningOverrides(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {}
  }

  const out: Record<string, string> = {}

  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const effort = normalizeReasoningEffortValue(value)

    if (key && effort) {
      out[key] = effort
    }
  }

  return out
}

interface HermesConfigOptions {
  activeSessionIdRef: MutableRefObject<string | null>
}

export function useHermesConfig({ activeSessionIdRef }: HermesConfigOptions) {
  const [voiceMaxRecordingSeconds, setVoiceMaxRecordingSeconds] = useState(DEFAULT_VOICE_SECONDS)
  const [sttEnabled, setSttEnabled] = useState(true)
  const profileRefreshEpochRef = useRef(0)

  const refreshHermesConfig = useCallback(
    async (force = false, shouldPublish: () => boolean = () => true) => {
      if (force) {
        profileRefreshEpochRef.current += 1
      }

      const profileRefreshEpoch = profileRefreshEpochRef.current
      const selectionGeneration = getComposerSelectionGeneration()

      try {
        const [config, defaults] = await Promise.all([getHermesConfig(), getHermesConfigDefaults().catch(() => ({}))])

        const canPublish = () => profileRefreshEpochRef.current === profileRefreshEpoch && shouldPublish()

        if (!canPublish()) {
          return
        }

        const personality = normalizePersonalityValue(
          typeof config.display?.personality === 'string' ? config.display.personality : ''
        )

        if (!canPublish()) {
          return
        }

        setIntroPersonality(personality)
        // Active sessions keep their per-session value; standalone falls back to config.
        setCurrentPersonality(prev => (activeSessionIdRef.current ? prev || personality : personality))
        setAvailablePersonalities([
          ...new Set([
            'none',
            ...BUILTIN_PERSONALITIES,
            ...personalityNamesFromConfig(defaults),
            ...personalityNamesFromConfig(config)
          ])
        ])

        const reasoning = normalizeReasoningEffortValue(config.agent?.reasoning_effort)
        const overrides = normalizeReasoningOverrides(config.agent?.reasoning_overrides)
        const tier = (config.agent?.service_tier ?? '').trim()

        // Publish the profile default regardless of whether the composer is
        // reseeded below: picker rows and preset application resolve "the
        // default" from here, so a manual model pick must not leave them
        // rendering/applying Hermes' built-in medium over the user's config.
        if (!canPublish()) {
          return
        }

        setDefaultReasoningEffort(reasoning)
        setReasoningOverrides(overrides)

        const shouldSeedComposer =
          !activeSessionIdRef.current &&
          getComposerSelectionGeneration() === selectionGeneration &&
          (force || getCurrentModelSource() !== 'manual')

        if (!activeSessionIdRef.current && getComposerSelectionGeneration() === selectionGeneration) {
          if (!canPublish()) {
            return
          }

          // Draft effort follows per-model overrides (and a user-pinned
          // preset). Sticky High from the last chat must not shadow
          // `agent.reasoning_overrides` on Cmd+N / first paint.
          const nextEffort = composerEffortForSelection($currentProvider.get(), $currentModel.get())

          if (nextEffort) {
            setCurrentReasoningEffort(nextEffort)
          }
        }

        if (shouldSeedComposer) {
          if (!canPublish()) {
            return
          }

          setCurrentFastMode(FAST_TIERS.has(tier.toLowerCase()))
        }

        if (!canPublish()) {
          return
        }

        setCurrentServiceTier(prev => (activeSessionIdRef.current ? prev : tier))

        if (!canPublish()) {
          return
        }

        setVoiceMaxRecordingSeconds(recordingLimit(config.voice?.max_recording_seconds))
        setSttEnabled(config.stt?.enabled !== false)

        if (!canPublish()) {
          return
        }

        setDisplayTimestampsFromConfig(config.display?.timestamps)
        setShowReasoningFromConfig(config.display?.show_reasoning)
        setTerminalFontFamilyFromConfig(config.terminal?.font_family)
        setEditorFontFamilyFromConfig(config.editor?.font_family)
        setEditorFontSizeFromConfig(config.editor?.font_size)
        setChatFontFamilyFromConfig(config.desktop?.font_family)

        if (!canPublish()) {
          return
        }

        applyAutoSpeakFromConfig(config)
        applyVoiceStopPhraseFromConfig(config)
        applyThinkingSoundFromConfig(config)
        // Resolved server-side (mode + whether a key resolves); non-critical.
        void refreshVoiceLiveStatus().catch(() => undefined)
      } catch {
        // Config is nice-to-have; chat still works without it.
      }
    },
    [activeSessionIdRef]
  )

  return { refreshHermesConfig, sttEnabled, voiceMaxRecordingSeconds }
}
