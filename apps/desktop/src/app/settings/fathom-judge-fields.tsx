import { useEffect, useMemo, useRef, useState } from 'react'

import {
  type ProfileScope,
  profileScopeKey,
  saveHermesConfigRecord
} from '@/hermes'
import { useI18n } from '@/i18n'
import { notifyError } from '@/store/notifications'
import type { HermesConfigRecord } from '@/types/hermes'

import { hermesConfigCacheWriter, useHermesConfigRecord } from '../hooks/use-config-record'

import { ConfigField } from './config-field'
import { diffConfig, getNested, inferFieldSchema, setNested } from './helpers'

/** Shipped defaults. Blank config uses the same values in plugins/web/fathom/judge.py. */
export const FATHOM_JUDGE_FIELDS = [
  { key: 'web.fathom.judge.provider', fallback: 'cpa' },
  { key: 'web.fathom.judge.model', fallback: 'grok-4.6' },
  { key: 'web.fathom.judge.effort', fallback: 'xhigh' }
] as const

function shownValue(config: HermesConfigRecord, key: string, fallback: string): string {
  const stored = getNested(config, key)
  const text = typeof stored === 'string' ? stored.trim() : ''

  return text || fallback
}

/**
 * Judge provider, model, and effort for the Fathom web backend. These are
 * config.yaml settings, not secrets, so they are not env-var rows.
 */
export function FathomJudgeFields({ profile }: { profile?: ProfileScope }) {
  const { t } = useI18n()
  const { data: loadedConfig, writeScope } = useHermesConfigRecord(profile)
  const scopeKey = profile == null ? null : profileScopeKey(profile)
  // eslint-disable-next-line react-hooks/exhaustive-deps -- scopeKey is the identity of `profile`
  const writeConfigCache = useMemo(() => hermesConfigCacheWriter(profile), [scopeKey])
  const [config, setConfig] = useState<HermesConfigRecord | null>(null)
  const [baseline, setBaseline] = useState<HermesConfigRecord | null>(null)
  const seeded = useRef(false)

  // eslint-disable-next-line no-restricted-syntax -- one-shot config seed flag, not an atom mirror
  useEffect(() => {
    if (loadedConfig && !seeded.current) {
      seeded.current = true
      setBaseline(loadedConfig)
      setConfig(loadedConfig)
    }
  }, [loadedConfig])

  const saveVersionRef = useRef(0)
  const [saveVersion, setSaveVersion] = useState(0)

  useEffect(() => {
    if (!config || saveVersion === 0) {
      return
    }

    const timeout = window.setTimeout(() => {
      void saveHermesConfigRecord(diffConfig(baseline ?? {}, config), writeScope ?? profile)
        .then(() => {
          setBaseline(config)
          writeConfigCache(config)
        })
        .catch(err => notifyError(err, t.settings.config.autosaveFailed))
    }, 550)

    return () => window.clearTimeout(timeout)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- copy is stable; profile identity is scopeKey
  }, [config, scopeKey, saveVersion, writeConfigCache, writeScope])

  if (!config) {
    return null
  }

  const updateConfig = (next: HermesConfigRecord) => {
    saveVersionRef.current += 1
    setConfig(next)
    setSaveVersion(saveVersionRef.current)
  }

  return (
    <div className="grid gap-0.5 rounded-lg bg-background/55 px-2.5">
      {FATHOM_JUDGE_FIELDS.map(field => {
        const value = shownValue(config, field.key, field.fallback)

        return (
          <ConfigField
            key={field.key}
            onChange={next => updateConfig(setNested(config, field.key, next))}
            schema={inferFieldSchema(value)}
            schemaKey={field.key}
            value={value}
          />
        )
      })}
    </div>
  )
}
