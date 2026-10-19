import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import {
  editorSpawnEnv,
  openPathInEditor,
  openPathInVSCode,
  parseEditorCommand,
  resolveEditorCommand,
  resolveEditorExecutable,
  resolveVSCodeLaunch
} from './open-in-editor'

test('parseEditorCommand splits flags and drops --wait', () => {
  assert.deepEqual(parseEditorCommand('code --wait'), { args: [], cmd: 'code' })
  assert.deepEqual(parseEditorCommand('code -g'), { args: ['-g'], cmd: 'code' })
  assert.deepEqual(parseEditorCommand('"C:\\Program Files\\Vim\\vim.exe"'), {
    args: [],
    cmd: 'C:\\Program Files\\Vim\\vim.exe'
  })
})

test('resolveEditorCommand prefers the Windows user-level EDITOR over process.env', () => {
  const editor = resolveEditorCommand({
    env: { EDITOR: 'notepad', VISUAL: 'notepad' },
    platform: 'win32',
    readUserEnv: name => (name === 'EDITOR' ? 'code' : null)
  })

  assert.equal(editor, 'code')
})

test('resolveEditorCommand uses process.env when no user-level value exists', () => {
  assert.equal(
    resolveEditorCommand({
      env: { EDITOR: 'vim' },
      platform: 'linux'
    }),
    'vim'
  )
  assert.equal(
    resolveEditorCommand({
      env: {},
      platform: 'win32',
      readUserEnv: () => null
    }),
    null
  )
})

test('editorSpawnEnv strips Electron and Chromium variables', () => {
  const env = editorSpawnEnv({
    CHROME_CRASHPAD_PIPE_NAME: 'pipe',
    EDITOR: 'code',
    ELECTRON_DISABLE_SANDBOX: '1',
    ELECTRON_RUN_AS_NODE: '1',
    NODE_OPTIONS: '--require ./inject.js',
    PATH: 'C:\\Windows'
  })

  assert.equal(env.EDITOR, 'code')
  assert.equal(env.PATH, 'C:\\Windows')
  assert.equal(env.ELECTRON_RUN_AS_NODE, undefined)
  assert.equal(env.ELECTRON_DISABLE_SANDBOX, undefined)
  assert.equal(env.CHROME_CRASHPAD_PIPE_NAME, undefined)
  assert.equal(env.NODE_OPTIONS, undefined)
})

test('resolveEditorExecutable maps code to Code.exe when it exists', () => {
  const localAppData = 'C:\\Users\\me\\AppData\\Local'
  const codeExe = path.win32.join(localAppData, 'Programs', 'Microsoft VS Code', 'Code.exe')

  assert.equal(
    resolveEditorExecutable('code', {
      env: { LOCALAPPDATA: localAppData },
      exists: filePath => filePath === codeExe,
      platform: 'win32'
    }),
    codeExe
  )
})

test('openPathInEditor launches Code.exe with Electron env stripped', async () => {
  const localAppData = 'C:\\Users\\me\\AppData\\Local'
  const codeExe = path.win32.join(localAppData, 'Programs', 'Microsoft VS Code', 'Code.exe')
  const filePath = path.win32.join('C:', 'Users', 'me', '.hermes', 'config.yaml')

  const spawned: Array<{
    args: readonly string[]
    cmd: string
    opts: { env?: NodeJS.ProcessEnv; shell?: boolean; windowsHide?: boolean }
  }> = []

  let opened: string | null = null

  const ok = await openPathInEditor(filePath, {
    env: {
      ELECTRON_DISABLE_SANDBOX: '1',
      ELECTRON_RUN_AS_NODE: '1',
      LOCALAPPDATA: localAppData
    },
    exists: target => target === codeExe,
    openPath: async target => {
      opened = target

      return ''
    },
    platform: 'win32',
    readUserEnv: name => (name === 'EDITOR' ? 'code' : null),
    spawn: (cmd, args, opts) => {
      spawned.push({ args, cmd, opts })

      return { unref() {} }
    }
  })

  assert.equal(ok, true)
  assert.equal(spawned.length, 1)
  assert.equal(spawned[0]?.cmd, codeExe)
  assert.deepEqual(spawned[0]?.args, [filePath])
  assert.equal(spawned[0]?.opts.shell, false)
  assert.equal(spawned[0]?.opts.windowsHide, false)
  assert.equal(spawned[0]?.opts.env?.ELECTRON_RUN_AS_NODE, undefined)
  assert.equal(spawned[0]?.opts.env?.ELECTRON_DISABLE_SANDBOX, undefined)
  assert.equal(opened, null)
})

test('openPathInEditor falls back to OS association when no editor is set', async () => {
  let opened: string | null = null

  const ok = await openPathInEditor('/home/me/.hermes/config.yaml', {
    env: {},
    openPath: async filePath => {
      opened = filePath

      return ''
    },
    platform: 'linux'
  })

  assert.equal(ok, true)
  assert.equal(opened, '/home/me/.hermes/config.yaml')
})

test('openPathInVSCode spawns Code.exe and strips Electron env', async () => {
  const localAppData = 'C:\\Users\\me\\AppData\\Local'
  const codeExe = path.win32.join(localAppData, 'Programs', 'Microsoft VS Code', 'Code.exe')
  const folder = path.win32.join('E:', 'AI', 'hermes-agent')
  const spawned: Array<{ args: readonly string[]; cmd: string; env?: NodeJS.ProcessEnv }> = []

  const ok = await openPathInVSCode(folder, {
    env: {
      ELECTRON_RUN_AS_NODE: '1',
      LOCALAPPDATA: localAppData,
      PATH: path.win32.join(localAppData, 'Programs', 'Microsoft VS Code', 'bin')
    },
    exists: target => target === codeExe,
    platform: 'win32',
    spawn: (cmd, args, opts) => {
      spawned.push({ args, cmd, env: opts.env })

      return { unref() {} }
    }
  })

  assert.equal(ok, true)
  assert.equal(spawned.length, 1)
  assert.equal(spawned[0]?.cmd, codeExe)
  assert.deepEqual(spawned[0]?.args, [folder])
  assert.equal(spawned[0]?.env?.ELECTRON_RUN_AS_NODE, undefined)
})

test('openPathInVSCode maps a PATH code.cmd shim to the sibling Code.exe', async () => {
  const root = path.win32.join('C:', 'VS Code')
  const shim = path.win32.join(root, 'bin', 'code.cmd')
  const codeExe = path.win32.join(root, 'Code.exe')
  const spawned: string[] = []

  const ok = await openPathInVSCode('D:\\repo', {
    env: { PATH: path.win32.join(root, 'bin') },
    exists: target => target === shim || target === codeExe,
    platform: 'win32',
    spawn: cmd => {
      spawned.push(cmd)

      return { unref() {} }
    }
  })

  assert.equal(ok, true)
  assert.deepEqual(spawned, [codeExe])
})

test('resolveVSCodeLaunch uses open -a on macOS when the app bundle exists', () => {
  assert.deepEqual(
    resolveVSCodeLaunch({
      exists: target => target === '/Users/me/Applications/Visual Studio Code.app',
      homedir: '/Users/me',
      platform: 'darwin'
    }),
    { args: ['-a', 'Visual Studio Code'], cmd: 'open' }
  )
})

test('openPathInVSCode returns false when VS Code is not installed', async () => {
  let spawned = false

  const ok = await openPathInVSCode('/home/me/repo', {
    env: {},
    exists: () => false,
    platform: 'linux',
    spawn: () => {
      spawned = true

      return { unref() {} }
    }
  })

  assert.equal(ok, false)
  assert.equal(spawned, false)
})
