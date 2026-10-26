import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'

import { test } from 'vitest'

import { launchWinMerge, resolveWinMergeExecutable, WINMERGE_NOT_FOUND } from './external-diff'

test('resolveWinMergeExecutable prefers a standard install path', () => {
  const found = resolveWinMergeExecutable({
    env: { ProgramFiles: 'C:\\Program Files' },
    exists: filePath => filePath === 'C:\\Program Files\\WinMerge\\WinMergeU.exe',
    platform: 'win32',
    where: () => {
      throw new Error('where should not run')
    }
  })

  assert.equal(found, 'C:\\Program Files\\WinMerge\\WinMergeU.exe')
})

test('resolveWinMergeExecutable falls back to where.exe', () => {
  const found = resolveWinMergeExecutable({
    env: {},
    exists: filePath => filePath === 'D:\\Tools\\WinMergeU.exe',
    platform: 'win32',
    where: () => ['D:\\Tools\\WinMergeU.exe']
  })

  assert.equal(found, 'D:\\Tools\\WinMergeU.exe')
})

test('resolveWinMergeExecutable is windows-only', () => {
  assert.equal(
    resolveWinMergeExecutable({
      exists: () => true,
      platform: 'linux'
    }),
    null
  )
  assert.equal(WINMERGE_NOT_FOUND, 'WINMERGE_NOT_FOUND')
})

test('launchWinMerge passes the two sides and unrefs after spawn', async () => {
  const calls: Array<{ args: readonly string[]; command: string }> = []

  await launchWinMerge('C:\\WinMerge\\WinMergeU.exe', 'C:\\left', 'C:\\right', { left: 'HEAD', right: 'Working tree' }, {
    spawn: (command, args) => {
      calls.push({ args, command })
      const child = new EventEmitter() as EventEmitter & { unref: () => void; unrefed: boolean }

      child.unrefed = false
      child.unref = () => {
        child.unrefed = true
      }
      queueMicrotask(() => child.emit('spawn'))

      return child
    }
  })

  assert.deepEqual(calls, [
    {
      args: ['/e', '/u', '/wl', '/dl', 'HEAD', '/dr', 'Working tree', 'C:\\left', 'C:\\right'],
      command: 'C:\\WinMerge\\WinMergeU.exe'
    }
  ])
})
