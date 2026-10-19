// Launch WinMerge against the two sides of a review-pane file. The executable
// is resolved on this machine; the caller supplies already-materialized paths.
import { type ChildProcess, execFileSync, spawn } from 'node:child_process'
import fs from 'node:fs'

import { editorSpawnEnv } from './open-in-editor'

export const WINMERGE_NOT_FOUND = 'WINMERGE_NOT_FOUND'

export interface ExternalDiffDeps {
  env?: NodeJS.ProcessEnv
  exists?: (filePath: string) => boolean
  platform?: NodeJS.Platform
  spawn?: (
    command: string,
    args: readonly string[],
    options: {
      detached?: boolean
      env?: NodeJS.ProcessEnv
      stdio?: 'ignore'
      windowsHide?: boolean
    }
  ) => Pick<ChildProcess, 'once' | 'unref'>
  where?: (name: string) => string[]
}

export function winMergeCandidates(env: NodeJS.ProcessEnv): string[] {
  const programFiles = env.ProgramFiles || env.PROGRAMFILES || ''
  const programFilesX86 = env['ProgramFiles(x86)'] || env.PROGRAMFILESX86 || ''
  const localAppData = env.LOCALAPPDATA || ''
  const candidates = [
    programFiles ? pathJoinWin(programFiles, 'WinMerge', 'WinMergeU.exe') : '',
    programFilesX86 ? pathJoinWin(programFilesX86, 'WinMerge', 'WinMergeU.exe') : '',
    localAppData ? pathJoinWin(localAppData, 'Programs', 'WinMerge', 'WinMergeU.exe') : ''
  ]

  return candidates.filter(Boolean)
}

function pathJoinWin(...parts: string[]): string {
  return parts.join('\\')
}

function defaultWhere(name: string): string[] {
  try {
    const output = execFileSync('where.exe', [name], {
      encoding: 'utf8',
      timeout: 5_000,
      windowsHide: true
    })

    return output
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean)
  } catch {
    return []
  }
}

export function resolveWinMergeExecutable(deps: ExternalDiffDeps = {}): null | string {
  const platform = deps.platform ?? process.platform

  if (platform !== 'win32') {
    return null
  }

  const env = deps.env ?? process.env
  const exists = deps.exists ?? (filePath => fs.existsSync(filePath))
  const where = deps.where ?? defaultWhere

  for (const candidate of winMergeCandidates(env)) {
    if (exists(candidate)) {
      return candidate
    }
  }

  for (const candidate of where('WinMergeU.exe')) {
    if (exists(candidate)) {
      return candidate
    }
  }

  return null
}

export function launchWinMerge(
  executable: string,
  leftPath: string,
  rightPath: string,
  labels: { left: string; right: string },
  deps: ExternalDiffDeps = {}
): Promise<void> {
  const spawnChild = deps.spawn ?? spawn

  return new Promise((resolve, reject) => {
    let child: Pick<ChildProcess, 'once' | 'unref'>

    try {
      child = spawnChild(
        executable,
        ['/e', '/u', '/wl', '/dl', labels.left, '/dr', labels.right, leftPath, rightPath],
        {
          detached: true,
          env: editorSpawnEnv(),
          stdio: 'ignore',
          windowsHide: true
        }
      )
    } catch (error) {
      reject(error instanceof Error ? error : new Error(String(error)))

      return
    }

    child.once('error', error => {
      reject(error instanceof Error ? error : new Error(String(error)))
    })
    child.once('spawn', () => {
      child.unref()
      resolve()
    })
  })
}
