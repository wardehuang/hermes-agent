/** Session-switch diagnostics that must survive a packaged Desktop.
 *
 * Renderer `console.info` never reaches desktop.log (the console tap keeps
 * error level only). `logLine` is the IPC that does. */
export function logSessionSwitch(message: string): void {
  const line = `[session-switch] ${message}`

  console.info(line)
  window.hermesDesktop?.logLine?.(line.slice(0, 4000))
}

/** A few caller frames, so a readiness reset can be tied to the write that caused it. */
export function sessionSwitchCaller(): string {
  const frames = (new Error().stack ?? '')
    .split('\n')
    .map(frame => frame.trim())
    .filter(frame => frame.startsWith('at ') && !frame.includes('session-switch-log'))
    .slice(0, 4)

  return frames.join(' | ').slice(0, 700)
}

/** One phase of a `setup.*` RPC, timed from the caller's own `performance.now()` at entry, so the gap between the status hook asking and the backend answering can be placed in the renderer, the route resolution, or the socket. */
export function logSetupRpcPhase(method: string, phase: string, startedAt: number): void {
  if (method.startsWith('setup.')) {
    logSessionSwitch(`rpc ${method} ${phase} +${Math.round(performance.now() - startedAt)}ms`)
  }
}

/** Logs every renderer frame that blocked the main thread for 200ms or more, so a gap between two session-switch lines can be told apart from an idle renderer that is waiting on IPC or the socket. Long Animation Frames carry script attribution; plain long tasks do not. */
export function observeSwitchLongFrames(): void {
  const type = PerformanceObserver.supportedEntryTypes.includes('long-animation-frame') ? 'long-animation-frame' : 'longtask'

  new PerformanceObserver(list => {
    for (const entry of list.getEntries()) {
      if (entry.duration < 200) {
        continue
      }

      const { scripts = [] } = entry as PerformanceEntry & {
        scripts?: Array<{ duration: number; invoker?: string; sourceURL?: string }>
      }

      const culprits = scripts
        .filter(script => script.duration >= 50)
        .map(script => `${script.invoker ?? '?'}@${(script.sourceURL ?? '').split('/').pop()}:${Math.round(script.duration)}ms`)
        .join(' ')

      logSessionSwitch(`${type} dur=${Math.round(entry.duration)}ms ${culprits}`)
    }
  }).observe({ type })
}
