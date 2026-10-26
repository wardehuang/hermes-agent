import assert from 'node:assert/strict'
import path from 'node:path'

import { test } from 'vitest'

import { openPathInVSCode, resolveVSCodeLaunch } from './open-in-vscode'

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
