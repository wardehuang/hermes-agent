import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import {
  editorSpawnEnv,
  openPathInEditor,
  parseEditorCommand,
  resolveEditorCommand,
  resolveEditorExecutable
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
