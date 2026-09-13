import { useEffect, useRef, useState } from 'react'

import {
  EDITOR_FONT_SUGGESTIONS,
  editorFontCss,
  normalizeEditorFontFamily,
  normalizeEditorFontSizePx,
  setEditorFontFamilyFromConfig,
  setEditorFontSizeFromConfig
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

interface EditorFontDraft {
  family: string
  size: string
}

function fontFamilyFromConfig(config: HermesConfigRecord): string {
  return normalizeEditorFontFamily(getNested(config, 'editor.font_family'))
}

function fontSizeFromConfig(config: HermesConfigRecord): number {
  return normalizeEditorFontSizePx(getNested(config, 'editor.font_size'))
}

function sizeDraftFromConfig(config: HermesConfigRecord): string {
  const px = fontSizeFromConfig(config)

  return px === 0 ? '' : String(px)
}

function draftFromConfig(config: HermesConfigRecord): EditorFontDraft {
  return { family: fontFamilyFromConfig(config), size: sizeDraftFromConfig(config) }
}

function draftsEqual(left: EditorFontDraft, right: EditorFontDraft): boolean {
  return left.family === right.family && left.size === right.size
}

export function EditorFontSetting() {
  const { t } = useI18n()
  const copy = t.settings.appearance
  const { data: loadedConfig } = useHermesConfigRecord()
  const [draft, setDraft] = useState<EditorFontDraft | null>(null)
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

    const next = draftFromConfig(loadedConfig)
    setDraft(next)
    setEditorFontFamilyFromConfig(next.family)
    setEditorFontSizeFromConfig(next.size)
  }, [draft, loadedConfig, staleConfig])

  useOnProfileSwitch(() => {
    saveVersionRef.current += 1
    setDraft(null)
    setStaleConfig(loadedConfig ?? null)
    setSaveVersion(0)
    setEditorFontFamilyFromConfig('')
    setEditorFontSizeFromConfig(0)
  })

  useEffect(() => {
    if (draft === null || saveVersion === 0 || !loadedConfig) {
      return
    }

    const version = saveVersion
    const persisted = draftFromConfig(loadedConfig)

    if (draftsEqual(draft, persisted)) {
      return
    }

    const timeout = window.setTimeout(() => {
      const family = normalizeEditorFontFamily(draft.family)
      const size = normalizeEditorFontSizePx(draft.size)
      const next = setNested(setNested(loadedConfig, 'editor.font_family', family), 'editor.font_size', size)

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
          setDraft(persisted)
          setEditorFontFamilyFromConfig(persisted.family)
          setEditorFontSizeFromConfig(persisted.size)
          notifyError(error, t.settings.config.autosaveFailed)
        })
    }, AUTOSAVE_DELAY_MS)

    return () => window.clearTimeout(timeout)
  }, [draft, loadedConfig, saveVersion, t.settings.config.autosaveFailed])

  const update = (patch: Partial<EditorFontDraft>) => {
    if (draft === null) {
      return
    }

    const next = { ...draft, ...patch }
    saveVersionRef.current += 1
    setDraft(next)
    setSaveVersion(saveVersionRef.current)
    setEditorFontFamilyFromConfig(next.family)
    setEditorFontSizeFromConfig(next.size)
  }

  const value = draft ?? { family: '', size: '' }
  const previewFont = editorFontCss(value.family, value.size)

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
              onChange={event => update({ family: event.target.value })}
              placeholder={copy.editorFontPlaceholder}
              value={value.family}
            />
            <Button
              disabled={!value.family || draft === null}
              onClick={() => update({ family: '' })}
              size="inline"
              variant="text"
            >
              {copy.editorFontReset}
            </Button>
          </div>
          <datalist id="hermes-editor-font-families">
            {EDITOR_FONT_SUGGESTIONS.map(font => (
              <option key={font} value={font} />
            ))}
          </datalist>
          <div className="flex items-center gap-3">
            <span className="shrink-0 text-xs text-muted-foreground">{copy.editorFontSizeLabel}</span>
            <Input
              aria-label={copy.editorFontSizeLabel}
              className="w-28"
              disabled={draft === null}
              inputMode="numeric"
              max={48}
              min={8}
              onChange={event => update({ size: event.target.value })}
              placeholder={copy.editorFontSizePlaceholder}
              suffix={copy.editorFontSizeUnit}
              type="number"
              value={value.size}
            />
          </div>
          <div
            aria-label={copy.editorFontPreview}
            className="overflow-hidden px-1 py-2 text-(--ui-text-secondary)"
            style={{
              fontFamily: previewFont.fontFamily,
              fontSize: previewFont.fontSize,
              fontWeight: previewFont.fontWeight,
              lineHeight: previewFont.lineHeight
            }}
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
