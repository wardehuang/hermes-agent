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
import os from 'node:os'
import path from 'node:path'

export interface OpenInEditorDeps {
  env?: NodeJS.ProcessEnv
  exists?: (filePath: string) => boolean
  homedir?: string
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

function pathApi(platform: NodeJS.Platform) {
  return platform === 'win32' ? path.win32 : path.posix
}

function existingOnPath(fileName: string, deps: OpenInEditorDeps, platform: NodeJS.Platform): null | string {
  const env = deps.env ?? process.env
  const exists = deps.exists ?? (filePath => fs.existsSync(filePath))
  const api = pathApi(platform)
  const raw = env.PATH || env.Path || ''

  for (const dir of raw.split(api.delimiter)) {
    if (!dir) {
      continue
    }

    const candidate = api.join(dir, fileName)

    if (exists(candidate)) {
      return candidate
    }
  }

  return null
}

function resolveWindowsCodeExe(deps: OpenInEditorDeps): null | string {
  const env = deps.env ?? process.env
  const exists = deps.exists ?? (filePath => fs.existsSync(filePath))
  const join = path.win32.join
  const localAppData = env.LOCALAPPDATA || ''
  const programFiles = env.ProgramFiles || env.PROGRAMFILES || ''
  const programFilesX86 = env['ProgramFiles(x86)'] || ''
  const candidates = [
    localAppData ? join(localAppData, 'Programs', 'Microsoft VS Code', 'Code.exe') : '',
    programFiles ? join(programFiles, 'Microsoft VS Code', 'Code.exe') : '',
    programFilesX86 ? join(programFilesX86, 'Microsoft VS Code', 'Code.exe') : ''
  ]

  for (const candidate of candidates) {
    if (candidate && exists(candidate)) {
      return candidate
    }
  }

  const onPath = existingOnPath('Code.exe', deps, 'win32')

  if (onPath) {
    return onPath
  }

  // `code.cmd` inherits ELECTRON_RUN_AS_NODE and exits without a window.
  // Only accept it when the real Code.exe sits next to that shim.
  const shim = existingOnPath('code.cmd', deps, 'win32')

  if (!shim) {
    return null
  }

  const resolved = resolveEditorExecutable(shim, { ...deps, platform: 'win32' })

  return resolved.toLowerCase().endsWith('code.exe') && exists(resolved) ? resolved : null
}

// Launch Microsoft VS Code itself — not $EDITOR, and not `code.cmd`.
export function resolveVSCodeLaunch(deps: OpenInEditorDeps = {}): null | { args: string[]; cmd: string } {
  const platform = deps.platform ?? process.platform
  const exists = deps.exists ?? (filePath => fs.existsSync(filePath))

  if (platform === 'win32') {
    const exe = resolveWindowsCodeExe(deps)

    return exe ? { args: [], cmd: exe } : null
  }

  if (platform === 'darwin') {
    const home = deps.homedir ?? os.homedir()
    const apps = [
      '/Applications/Visual Studio Code.app',
      path.posix.join(home, 'Applications', 'Visual Studio Code.app')
    ]

    if (apps.some(app => exists(app))) {
      return { args: ['-a', 'Visual Studio Code'], cmd: 'open' }
    }
  }

  const cli =
    existingOnPath('code', deps, platform) ||
    ['/usr/bin/code', '/usr/share/code/bin/code', '/snap/bin/code'].find(candidate => exists(candidate)) ||
    null

  return cli ? { args: [], cmd: cli } : null
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

export async function openPathInVSCode(targetPath: string, deps: OpenInEditorDeps = {}): Promise<boolean> {
  const launch = resolveVSCodeLaunch(deps)

  if (!launch) {
    return false
  }

  try {
    launchEditor(launch.cmd, [...launch.args, targetPath], deps)

    return true
  } catch {
    return false
  }
}
