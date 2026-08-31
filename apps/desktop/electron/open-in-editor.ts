// Open a local file in $EDITOR (User-scoped on Windows), falling back to the
// OS file association. Used by the Profiles "Edit config" action so the user
// never has to hunt AppData for config.yaml.
//
// Launching VS Code from an Electron app cannot go through `code.cmd`:
// that shim sets ELECTRON_RUN_AS_NODE=1 and starts Code.exe as a CLI helper.
// Inherited Electron/Chromium env then makes the helper flash in the taskbar
// and exit without a window. Spawn Code.exe directly with a cleaned env.
import { type ChildProcess, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

export interface OpenInEditorDeps {
  env?: NodeJS.ProcessEnv
  exists?: (filePath: string) => boolean
  openPath?: (filePath: string) => Promise<string>
  platform?: NodeJS.Platform
  readUserEnv?: (name: string) => null | string
  spawn?: (
    command: string,
    args: readonly string[],
    options: {
      detached?: boolean
      env?: NodeJS.ProcessEnv
      shell?: boolean
      stdio?: 'ignore'
      windowsHide?: boolean
    }
  ) => Pick<ChildProcess, 'unref'>
}

const ELECTRON_CHILD_ENV_PREFIXES = ['CHROME_', 'ELECTRON_', 'GOOGLE_']

export function parseEditorCommand(raw: string): { args: string[]; cmd: string } {
  const tokens = raw.match(/(?:[^\s"]+|"[^"]*")+/g)?.map(token => token.replace(/^"|"$/g, '')) ?? [raw]
  const cmd = tokens[0] ?? raw.trim()
  const args = tokens.slice(1).filter(token => token !== '--wait')

  return { args, cmd }
}

export function resolveEditorCommand(deps: OpenInEditorDeps = {}): null | string {
  const platform = deps.platform ?? process.platform
  const env = deps.env ?? process.env

  // GUI apps launched from Explorer keep the login-time env block, so a
  // `setx`/`SetEnvironmentVariable` after login is invisible in process.env.
  // The live HKCU value is the durable preference (see windows-user-env.ts).
  if (platform === 'win32' && deps.readUserEnv) {
    const userEditor = deps.readUserEnv('EDITOR') || deps.readUserEnv('VISUAL')

    if (userEditor) {
      return userEditor
    }
  }

  const fromEnv = (env.VISUAL || env.EDITOR || '').trim()

  return fromEnv || null
}

export function editorSpawnEnv(source: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...source }

  for (const key of Object.keys(env)) {
    const upper = key.toUpperCase()

    if (ELECTRON_CHILD_ENV_PREFIXES.some(prefix => upper.startsWith(prefix))) {
      delete env[key]
    }
  }

  delete env.NODE_OPTIONS

  return env
}

export function resolveEditorExecutable(cmd: string, deps: OpenInEditorDeps = {}): string {
  const platform = deps.platform ?? process.platform
  const env = deps.env ?? process.env
  const exists = deps.exists ?? (filePath => fs.existsSync(filePath))
  const base = cmd.replace(/[\\/]+$/, '').split(/[\\/]/).pop()?.toLowerCase() || cmd.toLowerCase()

  if (platform !== 'win32' || (base !== 'code' && base !== 'code.cmd' && base !== 'code.exe')) {
    return cmd
  }

  const join = path.win32.join
  const candidates: string[] = []

  if (path.win32.isAbsolute(cmd) || cmd.includes('\\') || cmd.includes('/')) {
    candidates.push(path.win32.resolve(path.win32.dirname(cmd), '..', 'Code.exe'))
  }

  const localAppData = env.LOCALAPPDATA || ''
  const programFiles = env.ProgramFiles || env.PROGRAMFILES || ''

  if (localAppData) {
    candidates.push(join(localAppData, 'Programs', 'Microsoft VS Code', 'Code.exe'))
  }

  if (programFiles) {
    candidates.push(join(programFiles, 'Microsoft VS Code', 'Code.exe'))
  }

  for (const candidate of candidates) {
    if (exists(candidate)) {
      return candidate
    }
  }

  return cmd
}

function isWindowsCmdShim(cmd: string, platform: NodeJS.Platform): boolean {
  if (platform !== 'win32') {
    return false
  }

  const base = cmd.replace(/[\\/]+$/, '').split(/[\\/]/).pop()?.toLowerCase() || cmd.toLowerCase()

  return base === 'code' || base.endsWith('.cmd') || base.endsWith('.bat')
}

export async function openPathInEditor(filePath: string, deps: OpenInEditorDeps = {}): Promise<boolean> {
  const editor = resolveEditorCommand(deps)
  const platform = deps.platform ?? process.platform
  const exists = deps.exists ?? (target => fs.existsSync(target))

  if (editor) {
    const { args, cmd } = parseEditorCommand(editor)
    const resolved = resolveEditorExecutable(cmd, deps)

    if (exists(resolved) || !isWindowsCmdShim(resolved, platform)) {
      launchEditor(resolved, [...args, filePath], deps)

      return true
    }
  }

  if (!deps.openPath) {
    return false
  }

  const error = await deps.openPath(path.normalize(filePath))

  return !error
}

function launchEditor(cmd: string, args: readonly string[], deps: OpenInEditorDeps) {
  const spawnFn = deps.spawn ?? spawn

  const child = spawnFn(cmd, args, {
    detached: true,
    env: editorSpawnEnv(deps.env ?? process.env),
    shell: false,
    stdio: 'ignore',
    windowsHide: false
  })

  child.unref()
}
