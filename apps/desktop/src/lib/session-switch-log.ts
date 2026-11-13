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
