// Open a folder in Microsoft VS Code itself — not $EDITOR, and not `code.cmd`.
// That shim sets ELECTRON_RUN_AS_NODE=1 and starts Code.exe as a CLI helper.
// Inherited Electron/Chromium env then makes the helper flash and exit
// without a window. Spawn Code.exe directly with a cleaned env.
import { type ChildProcess, spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export interface OpenInVSCodeDeps {
  env?: NodeJS.ProcessEnv
  exists?: (filePath: string) => boolean
  homedir?: string
  platform?: NodeJS.Platform
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

function guiSpawnEnv(source: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...source }

  for (const key of Object.keys(env)) {
    if (ELECTRON_CHILD_ENV_PREFIXES.some(prefix => key.toUpperCase().startsWith(prefix))) {
      delete env[key]
    }
  }

  delete env.NODE_OPTIONS

  return env
}

function pathApi(platform: NodeJS.Platform) {
  return platform === 'win32' ? path.win32 : path.posix
}

function existingOnPath(fileName: string, deps: OpenInVSCodeDeps, platform: NodeJS.Platform): null | string {
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

// `code.cmd` lives in `...\bin`. The real Code.exe is the parent of that bin.
function codeExeBesideShim(shim: string, deps: OpenInVSCodeDeps): null | string {
  const exists = deps.exists ?? (filePath => fs.existsSync(filePath))
  const sibling = path.win32.resolve(path.win32.dirname(shim), '..', 'Code.exe')

  return exists(sibling) ? sibling : null
}

function resolveWindowsCodeExe(deps: OpenInVSCodeDeps): null | string {
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

  const shim = existingOnPath('code.cmd', deps, 'win32')

  return shim ? codeExeBesideShim(shim, deps) : null
}

export function resolveVSCodeLaunch(deps: OpenInVSCodeDeps = {}): null | { args: string[]; cmd: string } {
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

function launch(cmd: string, args: readonly string[], deps: OpenInVSCodeDeps) {
  const spawnFn = deps.spawn ?? spawn

  const child = spawnFn(cmd, args, {
    detached: true,
    env: guiSpawnEnv(deps.env ?? process.env),
    shell: false,
    stdio: 'ignore',
    windowsHide: false
  })

  child.unref()
}

export async function openPathInVSCode(targetPath: string, deps: OpenInVSCodeDeps = {}): Promise<boolean> {
  const spec = resolveVSCodeLaunch(deps)

  if (!spec) {
    return false
  }

  try {
    launch(spec.cmd, [...spec.args, targetPath], deps)

    return true
  } catch {
    return false
  }
}
