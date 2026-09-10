import { useEffect, useRef, useState } from 'react'

import {
  EDITOR_FONT_SUGGESTIONS,
  normalizeEditorFontFamily,
  resolveEditorFontFamily,
  setEditorFontFamilyFromConfig
} from '@/components/chat/editor-font'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { saveHermesConfig } from '@/hermes'
import { useI18n } from '@/i18n'
import { notifyError } from '@/store/notifications'
import type { HermesConfigRecord } from '@/types/hermes'

import { setHermesConfigCache, useHermesConfigRecord } from '../hooks/use-config-record'
import { useOnProfileSwitch } from '../hooks/use-on-profile-switch'

import { getNested, setNested } from './helpers'
import { ListRow } from './primitives'

const AUTOSAVE_DELAY_MS = 550

function fontFamilyFromConfig(config: HermesConfigRecord): string {
  return normalizeEditorFontFamily(getNested(config, 'editor.font_family'))
}

export function EditorFontSetting() {
  const { t } = useI18n()
  const copy = t.settings.appearance
  const { data: loadedConfig } = useHermesConfigRecord()
  const [draft, setDraft] = useState<string | null>(null)
  const [staleConfig, setStaleConfig] = useState<HermesConfigRecord | null>(null)
  const [saveVersion, setSaveVersion] = useState(0)
  const saveVersionRef = useRef(0)

  const cancelPendingSave = () => {
    saveVersionRef.current = 0
  }

  useEffect(() => {
    if (!loadedConfig || draft !== null || loadedConfig === staleConfig) {
      return
    }

    const value = fontFamilyFromConfig(loadedConfig)
    setDraft(value)
    setEditorFontFamilyFromConfig(value)
  }, [draft, loadedConfig, staleConfig])

  useOnProfileSwitch(() => {
    saveVersionRef.current += 1
    setDraft(null)
    setStaleConfig(loadedConfig ?? null)
    setSaveVersion(0)
    setEditorFontFamilyFromConfig('')
  })

  useEffect(() => {
    if (draft === null || saveVersion === 0 || !loadedConfig) {
      return
    }

    const version = saveVersion
    const value = normalizeEditorFontFamily(draft)

    if (value === fontFamilyFromConfig(loadedConfig)) {
      return
    }

    const rollback = fontFamilyFromConfig(loadedConfig)

    const timeout = window.setTimeout(() => {
      const next = setNested(loadedConfig, 'editor.font_family', value)

      void saveHermesConfig(next)
        .then(result => {
          if (!result.ok) {
            throw new Error(t.settings.config.autosaveFailed)
          }

          if (saveVersionRef.current !== version) {
            return
          }

          setHermesConfigCache(next)
        })
        .catch(error => {
          if (saveVersionRef.current !== version) {
            return
          }

          cancelPendingSave()
          setSaveVersion(0)
          setDraft(rollback)
          setEditorFontFamilyFromConfig(rollback)
          notifyError(error, t.settings.config.autosaveFailed)
        })
    }, AUTOSAVE_DELAY_MS)

    return () => window.clearTimeout(timeout)
  }, [draft, loadedConfig, saveVersion, t.settings.config.autosaveFailed])

  const update = (value: string) => {
    saveVersionRef.current += 1
    setDraft(value)
    setSaveVersion(saveVersionRef.current)
    setEditorFontFamilyFromConfig(value)
  }

  const value = draft ?? ''
  const previewFontFamily = resolveEditorFontFamily(value)

  return (
    <ListRow
      below={
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-3">
            <Input
              aria-label={copy.editorFontTitle}
              className="flex-1"
              disabled={draft === null}
              list="hermes-editor-font-families"
              onChange={event => update(event.target.value)}
              placeholder={copy.editorFontPlaceholder}
              value={value}
            />
            <Button disabled={!value || draft === null} onClick={() => update('')} size="inline" variant="text">
              {copy.editorFontReset}
            </Button>
          </div>
          <datalist id="hermes-editor-font-families">
            {EDITOR_FONT_SUGGESTIONS.map(font => (
              <option key={font} value={font} />
            ))}
          </datalist>
          <div
            aria-label={copy.editorFontPreview}
            className="overflow-hidden px-1 py-2 text-sm text-(--ui-text-secondary)"
            style={{ fontFamily: previewFontFamily }}
          >
            <span className="mr-2 text-[length:var(--conversation-caption-font-size)] text-(--ui-text-tertiary)">
              {copy.editorFontPreview}
            </span>
            <span>const answer = 42</span>
          </div>
        </div>
      }
      description={copy.editorFontDesc}
      title={copy.editorFontTitle}
      wide
    />
  )
}
