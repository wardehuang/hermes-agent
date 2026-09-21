import { atom, type PluginContext, host } from '@hermes/plugin-sdk'

import {
  $fileBrowserOpen,
  $panesFlipped,
  $sidebarOpen,
  setFileBrowserOpen,
  setSidebarOpen
} from '@/store/layout'

import { type PlanComment, type PlanMode, planBasename } from './shared'

export const COMMENTS_KEY = 'commentsV1'
export const MODE_KEY = 'mode'

export const $pluginCtx = atom<null | PluginContext>(null)
export const $mode = atom<PlanMode>('agent')
export const $planFile = atom<null | string>(null)
export const $comments = atom<Record<string, PlanComment[]>>({})
export const $commentsEpoch = atom(0)

let planDispose: (() => void) | null = null
let persistTimer: ReturnType<typeof setTimeout> | null = null
let rightSidebarSnapshot: boolean | null = null
let autoOpenArmed = false

export function armPlanAutoOpen() {
  autoOpenArmed = true
  const file = $planFile.get()
  if (file) {
    clearComments(file)
  }
}

export function disarmPlanAutoOpen() {
  autoOpenArmed = false
}

export function consumePlanAutoOpen(): boolean {
  if (!autoOpenArmed) {
    return false
  }
  autoOpenArmed = false
  return true
}

function physicalRightSidebarOpen(): boolean {
  return $panesFlipped.get() ? $sidebarOpen.get() : $fileBrowserOpen.get()
}

function setPhysicalRightSidebar(open: boolean) {
  if ($panesFlipped.get()) {
    setSidebarOpen(open)
  } else {
    setFileBrowserOpen(open)
  }
}

export function hideRightSidebarForPlan() {
  if (rightSidebarSnapshot === null) {
    rightSidebarSnapshot = physicalRightSidebarOpen()
  }
  setPhysicalRightSidebar(false)
}

export function restoreRightSidebarAfterPlan() {
  const wasOpen = rightSidebarSnapshot
  rightSidebarSnapshot = null
  if (wasOpen === true) {
    setPhysicalRightSidebar(true)
  }
}

export function setPluginCtx(ctx: PluginContext | null) {
  $pluginCtx.set(ctx)
}

export function hydrate(ctx: PluginContext) {
  $mode.set('agent')

  const saved = ctx.storage.get<Record<string, PlanComment[]>>(COMMENTS_KEY, {})
  if (saved && typeof saved === 'object') {
    const clean: Record<string, PlanComment[]> = {}
    for (const [file, list] of Object.entries(saved)) {
      if (!Array.isArray(list)) {
        continue
      }
      clean[file] = list
        .filter(item => item && typeof item === 'object')
        .map(item => ({
          id: String(item.id || ''),
          quote: String(item.quote || ''),
          body: String(item.body || '')
        }))
        .filter(item => item.id && (item.quote || item.body))
    }
    $comments.set(clean)
  }
}

function persistComments() {
  const ctx = $pluginCtx.get()
  if (!ctx) {
    return
  }
  ctx.storage.set(COMMENTS_KEY, $comments.get())
}

export function schedulePersistComments() {
  if (persistTimer) {
    clearTimeout(persistTimer)
  }
  persistTimer = setTimeout(persistComments, 250)
}

export function commentsFor(file: string): PlanComment[] {
  return $comments.get()[file] ?? []
}

export function setComments(file: string, list: PlanComment[]) {
  $comments.set({ ...$comments.get(), [file]: list })
  schedulePersistComments()
}

export function clearComments(file: string) {
  const prev = $comments.get()
  if (!Object.hasOwn(prev, file)) {
    return
  }
  const next = { ...prev }
  delete next[file]
  $comments.set(next)
  schedulePersistComments()
  $commentsEpoch.set($commentsEpoch.get() + 1)
}

export function durableSessionId(override?: null | string): string | undefined {
  if (override) {
    return override
  }
  return host.state.focusedStoredSessionId.get() || undefined
}

export function runtimeSessionId(): string | undefined {
  return host.state.focusedSessionId.get() || host.state.activeSessionId.get() || undefined
}

export async function stageMode(mode: PlanMode, sidOverride?: null | string): Promise<boolean> {
  const ctx = $pluginCtx.get()
  if (!ctx) {
    return false
  }
  const sid = durableSessionId(sidOverride)
  try {
    await ctx.rest('/mode', { method: 'POST', body: { mode, session_id: sid } })
    return true
  } catch {
    return false
  }
}

export function setModeLocal(mode: PlanMode) {
  $mode.set(mode)
  $pluginCtx.get()?.storage.set(MODE_KEY, mode)
}

export function applyMode(mode: PlanMode, sidOverride?: null | string) {
  setModeLocal(mode)
  if (mode === 'agent') {
    closePlanView()
  }
  void stageMode(mode, sidOverride)
}

export function cycleMode() {
  applyMode($mode.get() === 'plan' ? 'agent' : 'plan')
}

export function onPlanViewClosed() {
  planDispose = null
  $planFile.set(null)
  disarmPlanAutoOpen()
  restoreRightSidebarAfterPlan()
}

export function closePlanView() {
  const dispose = planDispose
  planDispose = null
  $planFile.set(null)
  disarmPlanAutoOpen()
  try {
    dispose?.()
  } catch {
    /* close must never throw */
  }
  restoreRightSidebarAfterPlan()
}

export function isPlanViewOpen(): boolean {
  return planDispose !== null
}

export function bindPlanDispose(dispose: () => void) {
  planDispose = dispose
}

export function planTitle(file: string): string {
  return planBasename(file)
}

export function flush() {
  if (persistTimer) {
    clearTimeout(persistTimer)
    persistTimer = null
  }
  persistComments()
  closePlanView()
}
