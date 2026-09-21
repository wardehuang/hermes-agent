/**
 * Ultra Plan — Cursor-like Plan mode for Hermes Desktop.
 *
 * + menu Plan chip, dedicated plan view, selection comments,
 * Continue/Build. Agent half (plugins/ultra-plan) owns the note + mutation gate.
 */
import {
  COMPOSER_AREAS,
  host,
  type HermesPlugin,
  type PluginContext,
  TRANSCRIPT_DIRECTIVE_AREA,
  type TranscriptDirectiveContribution
} from '@hermes/plugin-sdk'

import { LOCALES } from './i18n'
import { PlanChip } from './mode-button'
import { PlanDirective } from './plan-pane'
import {
  $mode,
  applyMode,
  armPlanAutoOpen,
  closePlanView,
  cycleMode,
  flush,
  hydrate,
  setPluginCtx,
  stageMode
} from './plan-store'
import { ID } from './shared'

const SLASH_SHAPE = /^\/[^\s/]/
const WORK_AREA =
  '[data-slot="composer-root"], [data-slot="composer-surface"], [data-slot="composer-bounds"]'
const SKIP_TARGET =
  '.xterm, [data-terminal], [role="dialog"], [role="alertdialog"], [role="listbox"], [role="menu"], .cm-editor'

const plugin: HermesPlugin = {
  id: ID,
  name: 'Ultra Plan',
  description:
    'Cursor-like Plan mode: + menu Plan chip, dedicated plan view, comments, Continue/Build.',
  defaultEnabled: true,
  register(ctx: PluginContext) {
    setPluginCtx(ctx)
    ctx.i18n.register(LOCALES)
    hydrate(ctx)

    ctx.register({
      id: 'plan-menu',
      area: COMPOSER_AREAS.attachments,
      data: {
        icon: 'checklist',
        label: 'Plan',
        run: () => applyMode('plan')
      }
    })

    ctx.register({
      id: 'plan-chip',
      area: COMPOSER_AREAS.leading,
      order: 10,
      render: () => <PlanChip />
    })

    ctx.register({
      id: 'rewrite',
      area: COMPOSER_AREAS.middleware,
      order: 10,
      data: {
        handler: async (draft: { attachments?: unknown[]; text: string }) => {
          try {
            const text = String(draft.text || '').trim()
            if (!text) {
              return draft
            }
            const hasAtts = Boolean(draft.attachments && draft.attachments.length)
            if (!hasAtts && SLASH_SHAPE.test(text)) {
              return draft
            }
            await stageMode($mode.get())
            if ($mode.get() === 'plan') {
              armPlanAutoOpen()
            }
            return draft
          } catch {
            return draft
          }
        }
      }
    })

    ctx.register({
      id: 'plan-directive',
      area: TRANSCRIPT_DIRECTIVE_AREA,
      data: {
        name: 'plan',
        render: ({ attrs, streaming }) => <PlanDirective attrs={attrs} streaming={streaming} />
      } satisfies TranscriptDirectiveContribution
    })

    const onModeKey = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !event.shiftKey) {
        return
      }
      if (event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented || event.repeat) {
        return
      }
      if (typeof document === 'undefined' || !document.hasFocus()) {
        return
      }
      const el = event.target instanceof Element ? event.target : null
      if (!el) {
        return
      }
      if (el.closest(SKIP_TARGET)) {
        return
      }
      const isBody = el === document.body || el === document.documentElement
      if (!isBody && !el.closest(WORK_AREA) && !el.closest('[data-ultra-plan]')) {
        return
      }
      try {
        cycleMode()
        event.preventDefault()
        event.stopPropagation()
      } catch {
        /* listener must never throw */
      }
    }

    window.addEventListener('keydown', onModeKey, true)
    let lastStored = host.state.focusedStoredSessionId.get()
    let lastRuntime = host.state.focusedSessionId.get()
    const onSessionFocus = () => {
      const stored = host.state.focusedStoredSessionId.get()
      const runtime = host.state.focusedSessionId.get()
      const sameDraftPromote = !lastStored && Boolean(stored) && lastRuntime === runtime
      const switched = stored !== lastStored || runtime !== lastRuntime
      lastStored = stored
      lastRuntime = runtime
      if (switched && !sameDraftPromote) {
        closePlanView()
      }
    }
    const stopStored = host.state.focusedStoredSessionId.listen(onSessionFocus)
    const stopRuntime = host.state.focusedSessionId.listen(onSessionFocus)
    ctx.onDispose(() => {
      stopStored()
      stopRuntime()
      window.removeEventListener('keydown', onModeKey, true)
      flush()
      setPluginCtx(null)
    })
  }
}

export default plugin
