import { Button, cn, Codicon, host, Tip, usePluginI18n, useValue } from '@hermes/plugin-sdk'
import { useEffect, useRef } from 'react'

import { $mode, $pluginCtx, applyMode, modeEpochNow, sessionRestScope, setModeLocal, stageMode } from './plan-store'
import { ID } from './shared'

export function PlanChip() {
  const t = usePluginI18n(ID)
  const mode = useValue($mode)
  const sid = useValue(host.state.focusedStoredSessionId)
  const lastSid = useRef<null | string | undefined>(undefined)

  // Previous focused session id, compared inside this effect before it is stored.
  // Not an atom mirror for a later callback — nothing outside the effect reads it.
  // eslint-disable-next-line no-restricted-syntax -- session transition, not a stale callback read
  useEffect(() => {
    if (sid === lastSid.current) {
      return
    }

    const prev = lastSid.current
    lastSid.current = sid

    if (prev === null && sid !== null) {
      void stageMode($mode.get(), sid)

      return
    }

    const ctx = $pluginCtx.get()

    if (!sid || !ctx) {
      if (prev !== undefined) {
        setModeLocal('agent')
      }

      return
    }

    const epoch = modeEpochNow()

    void ctx
      .rest<{ mode?: string }>(`/mode?session_id=${encodeURIComponent(sid)}`, sessionRestScope())
      .then(result => {
        if (epoch !== modeEpochNow()) {
          return
        }

        setModeLocal(result.mode === 'plan' ? 'plan' : 'agent')
      })
      .catch(() => {
        if (epoch !== modeEpochNow()) {
          return
        }

        setModeLocal('agent')
      })
  }, [sid])

  if (mode !== 'plan') {
    return null
  }

  return (
    <Tip label={t('modeHint')}>
      <div
        className={cn(
          'inline-flex h-6 shrink-0 items-center gap-0.5 rounded pl-1.5 pr-0.5 text-[0.6875rem] font-medium'
        )}
        data-ultra-plan-mode="plan"
        style={{
          backgroundColor: 'var(--ui-accent)',
          color: 'var(--ui-text-primary)'
        }}
      >
        <Codicon className="relative top-px shrink-0" name="checklist" size="0.75rem" />
        <span className="px-0.5 leading-none">{t('modePlan')}</span>
        <Button
          aria-label={t('modeClose')}
          className="size-5 shrink-0 rounded p-0 hover:bg-black/15"
          onClick={() => applyMode('agent')}
          type="button"
          variant="ghost"
        >
          <Codicon name="close" size="0.625rem" />
        </Button>
      </div>
    </Tip>
  )
}
