/**
 * Editor / source-view selections as composer `@line:` refs.
 *
 * CodeMirror and the windowed SourceView both register their host. A right-click
 * or ⌘/Ctrl+L on a live selection inserts the same chip the gutter drag already
 * produces, then focuses the active composer.
 */

import { requestComposerFocus, requestComposerInsertRefs } from '@/app/chat/composer/focus'
import { droppedFileInlineRef } from '@/app/chat/composer/inline-refs'
import { isComposerChord } from '@/lib/keybinds/chords'
import { $currentCwd } from '@/store/session'

/** Marks a windowed source-view chunk so a native text selection maps to file lines. */
export const SOURCE_CHUNK_START_ATTR = 'data-source-chunk-start'

export interface CodeSourceLineRange {
  line: number
  lineEnd?: number
}

export interface CodeSourceSelection extends CodeSourceLineRange {
  filePath: string
  text: string
}

interface CodeSourceHandle {
  host: HTMLElement
  read: () => CodeSourceSelection | null
}

const sources: CodeSourceHandle[] = []

let chordListening = false

/** Inclusive 1-based line range covering selected content. */
export function inclusiveLineRange(startLine: number, endLine: number): CodeSourceLineRange | null {
  const line = Math.min(startLine, endLine)
  const last = Math.max(startLine, endLine)

  if (line < 1 || last < 1) {
    return null
  }

  return last > line ? { line, lineEnd: last } : { line }
}

/** 1-based line number of the character at `offset` (clamped). */
export function lineNumberAtOffset(text: string, offset: number): number {
  if (offset <= 0) {
    return 1
  }

  let line = 1
  const cap = Math.min(offset, text.length)

  for (let i = 0; i < cap; i++) {
    if (text.charCodeAt(i) === 10) {
      line++
    }
  }

  return line
}

/**
 * Map an exclusive-end range (native Selection / CodeMirror) onto 1-based
 * inclusive file lines. `chunkStart` is the 0-based first line of that chunk.
 */
export function exclusiveOffsetsToLines(
  startChunkStart: number,
  startText: string,
  startOffset: number,
  endChunkStart: number,
  endText: string,
  exclusiveEndOffset: number
): CodeSourceLineRange | null {
  const startLine = startChunkStart + lineNumberAtOffset(startText, startOffset)
  const endProbe = Math.max(0, exclusiveEndOffset - (exclusiveEndOffset > 0 ? 1 : 0))
  const endLine = endChunkStart + lineNumberAtOffset(endText, endProbe)

  return inclusiveLineRange(startLine, endLine)
}

export function textOffsetIn(root: Node, node: Node, nodeOffset: number): number {
  const range = document.createRange()

  range.selectNodeContents(root)

  try {
    range.setEnd(node, nodeOffset)
  } catch {
    return 0
  }

  return range.toString().length
}

function chunkHost(node: Node): HTMLElement | null {
  const el = node instanceof Element ? node : node.parentElement
  const chunk = el?.closest(`[${SOURCE_CHUNK_START_ATTR}]`)

  return chunk instanceof HTMLElement ? chunk : null
}

/** Native window selection inside a SourceView scroller, mapped to file lines. */
export function nativeSelectionInHost(host: HTMLElement, filePath: string): CodeSourceSelection | null {
  const sel = window.getSelection()

  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
    return null
  }

  const range = sel.getRangeAt(0)

  if (!host.contains(range.startContainer) && range.startContainer !== host) {
    return null
  }

  const startEl = chunkHost(range.startContainer)
  const endEl = chunkHost(range.endContainer)

  if (!startEl || !endEl) {
    return null
  }

  const startChunk = Number(startEl.dataset.sourceChunkStart)
  const endChunk = Number(endEl.dataset.sourceChunkStart)

  if (!Number.isFinite(startChunk) || !Number.isFinite(endChunk)) {
    return null
  }

  const lines = exclusiveOffsetsToLines(
    startChunk,
    startEl.textContent ?? '',
    textOffsetIn(startEl, range.startContainer, range.startOffset),
    endChunk,
    endEl.textContent ?? '',
    textOffsetIn(endEl, range.endContainer, range.endOffset)
  )

  if (!lines) {
    return null
  }

  return { filePath, text: sel.toString(), ...lines }
}

export function addCodeSourceSelectionToChat(selection: CodeSourceSelection): boolean {
  const ref = droppedFileInlineRef(
    {
      line: selection.line,
      lineEnd: selection.lineEnd && selection.lineEnd > selection.line ? selection.lineEnd : undefined,
      path: selection.filePath
    },
    $currentCwd.get()
  )

  if (!ref) {
    return false
  }

  requestComposerInsertRefs([ref])
  requestComposerFocus('active')

  return true
}

export function codeSourceFromElement(element: Element | null): CodeSourceSelection | null {
  if (!element) {
    return null
  }

  for (const handle of sources) {
    if (handle.host === element || handle.host.contains(element)) {
      return handle.read()
    }
  }

  return null
}

function firstCodeSourceWithSelection(): CodeSourceSelection | null {
  for (const handle of sources) {
    const selection = handle.read()

    if (selection) {
      return selection
    }
  }

  return null
}

/** True when an editor / source view currently owns a line selection.
 *  The terminal's capture-phase ⌘/Ctrl+L handler yields when this is set,
 *  otherwise window.getSelection() in the preview is stolen as `@terminal:`. */
export function codeSourceHasSelection(): boolean {
  return firstCodeSourceWithSelection() !== null
}

function onComposerChord(event: KeyboardEvent) {
  if (event.defaultPrevented || !isComposerChord(event)) {
    return
  }

  const raw = event.target
  const element = raw instanceof Element ? raw : raw instanceof Node ? raw.parentElement : null
  const active = document.activeElement instanceof Element ? document.activeElement : null

  const selection =
    codeSourceFromElement(element) ?? codeSourceFromElement(active) ?? firstCodeSourceWithSelection()

  if (!selection) {
    return
  }

  event.preventDefault()
  event.stopPropagation()
  addCodeSourceSelectionToChat(selection)
}

function attachComposerChordListener() {
  if (chordListening || typeof window === 'undefined') {
    return
  }

  // Register at module load so this capture listener is in front of the
  // terminal's useEffect listener (same target, registration order).
  window.addEventListener('keydown', onComposerChord, true)
  chordListening = true
}

export function registerCodeSource(host: HTMLElement, read: () => CodeSourceSelection | null): () => void {
  const handle: CodeSourceHandle = { host, read }

  sources.push(handle)
  attachComposerChordListener()

  return () => {
    const index = sources.indexOf(handle)

    if (index >= 0) {
      sources.splice(index, 1)
    }
  }
}

attachComposerChordListener()
