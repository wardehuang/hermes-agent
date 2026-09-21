import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { requestComposerFocus, requestComposerInsertRefs } from '@/app/chat/composer/focus'
import { $currentCwd } from '@/store/session'

import {
  addCodeSourceSelectionToChat,
  codeSourceFromElement,
  codeSourceHasSelection,
  exclusiveOffsetsToLines,
  inclusiveLineRange,
  lineNumberAtOffset,
  nativeSelectionInHost,
  registerCodeSource,
  SOURCE_CHUNK_START_ATTR
} from './code-source-selection'

vi.mock('@/app/chat/composer/focus', () => ({
  requestComposerFocus: vi.fn(),
  requestComposerInsertRefs: vi.fn()
}))

afterEach(() => {
  vi.clearAllMocks()
  document.body.replaceChildren()
})

describe('inclusiveLineRange', () => {
  it('omits lineEnd on a single line', () => {
    expect(inclusiveLineRange(4, 4)).toEqual({ line: 4 })
  })

  it('orders a backwards range', () => {
    expect(inclusiveLineRange(9, 3)).toEqual({ line: 3, lineEnd: 9 })
  })

  it('rejects non-positive lines', () => {
    expect(inclusiveLineRange(0, 2)).toBeNull()
  })
})

describe('lineNumberAtOffset', () => {
  const text = 'a\nb\nc'

  it('treats offset 0 as line 1', () => {
    expect(lineNumberAtOffset(text, 0)).toBe(1)
  })

  it('counts newlines before the offset', () => {
    expect(lineNumberAtOffset(text, 2)).toBe(2)
    expect(lineNumberAtOffset(text, 4)).toBe(3)
  })
})

describe('exclusiveOffsetsToLines', () => {
  const text = 'a\nb\nc'

  it('covers a whole-document selection', () => {
    expect(exclusiveOffsetsToLines(0, text, 0, 0, text, text.length)).toEqual({ line: 1, lineEnd: 3 })
  })

  it('keeps a single-line exclusive range on that line', () => {
    expect(exclusiveOffsetsToLines(0, text, 2, 0, text, 3)).toEqual({ line: 2 })
  })

  it('does not include the next line when the range ends on a newline', () => {
    expect(exclusiveOffsetsToLines(0, text, 2, 0, text, 4)).toEqual({ line: 2 })
  })

  it('adds the windowed chunk start', () => {
    expect(exclusiveOffsetsToLines(200, text, 0, 200, text, 1)).toEqual({ line: 201 })
  })
})

describe('registerCodeSource', () => {
  it('resolves the host that contains the click target', () => {
    const host = document.createElement('div')
    const child = document.createElement('span')

    host.append(child)
    document.body.append(host)

    const unregister = registerCodeSource(host, () => ({ filePath: '/tmp/a.ts', line: 4, lineEnd: 8, text: 'x' }))

    expect(codeSourceFromElement(child)).toEqual({ filePath: '/tmp/a.ts', line: 4, lineEnd: 8, text: 'x' })
    expect(codeSourceHasSelection()).toBe(true)
    unregister()
    expect(codeSourceFromElement(child)).toBeNull()
    expect(codeSourceHasSelection()).toBe(false)
  })

  it('claims Ctrl+L for a live selection and inserts a line ref', () => {
    $currentCwd.set('/tmp')
    const host = document.createElement('div')

    document.body.append(host)

    const unregister = registerCodeSource(host, () => ({
      filePath: '/tmp/app.ts',
      line: 4,
      lineEnd: 9,
      text: 'picked'
    }))

    const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ctrlKey: true, key: 'l' })

    try {
      window.dispatchEvent(event)

      expect(event.defaultPrevented).toBe(true)
      expect(requestComposerInsertRefs).toHaveBeenCalledWith(['@line:app.ts:4-9'])
      expect(requestComposerFocus).toHaveBeenCalledWith('active')
    } finally {
      unregister()
    }
  })
})

describe('nativeSelectionInHost', () => {
  beforeEach(() => {
    window.getSelection()?.removeAllRanges()
  })

  it('maps a native selection onto chunk-relative lines', () => {
    const host = document.createElement('div')
    const chunk = document.createElement('div')

    chunk.setAttribute(SOURCE_CHUNK_START_ATTR, '0')
    chunk.textContent = 'alpha\nbeta\ngamma'
    host.append(chunk)
    document.body.append(host)

    const textNode = chunk.firstChild

    expect(textNode).toBeTruthy()

    const range = document.createRange()

    range.setStart(textNode!, 6)
    range.setEnd(textNode!, 10)
    window.getSelection()?.addRange(range)

    expect(nativeSelectionInHost(host, '/tmp/app.ts')).toEqual({
      filePath: '/tmp/app.ts',
      line: 2,
      text: 'beta'
    })
  })
})

describe('addCodeSourceSelectionToChat', () => {
  it('builds an @line ref relative to cwd', () => {
    $currentCwd.set('/repo')

    expect(
      addCodeSourceSelectionToChat({ filePath: '/repo/src/main.ts', line: 10, lineEnd: 12, text: 'body' })
    ).toBe(true)
    expect(requestComposerInsertRefs).toHaveBeenCalledWith(['@line:src/main.ts:10-12'])
  })

  it('omits lineEnd on a one-line selection', () => {
    $currentCwd.set('/repo')

    addCodeSourceSelectionToChat({ filePath: '/repo/a.ts', line: 3, text: 'x' })
    expect(requestComposerInsertRefs).toHaveBeenCalledWith(['@line:a.ts:3'])
  })

  it('relativizes a Windows path against a mixed-separator cwd', () => {
    $currentCwd.set('E:\\AI\\hermes-agent')

    addCodeSourceSelectionToChat({
      filePath: 'E:\\AI\\hermes-agent\\gateway\\__init__.py',
      line: 10,
      text: 'from .delivery import DeliveryRouter, DeliveryTarget'
    })
    expect(requestComposerInsertRefs).toHaveBeenCalledWith(['@line:gateway/__init__.py:10'])
  })
})
