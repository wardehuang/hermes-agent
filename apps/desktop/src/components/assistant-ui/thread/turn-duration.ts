// Whole-turn wall clock for the assistant footer.
//
// `durationS` is stamped only while this desktop watched the turn
// (message.start → message.complete). Hydrated history never has it — the
// backend stores row timestamps, not a duration — so the footer derives the
// same number: the user row that opened the turn → the latest authored
// timestamp on that turn. One pass per messages-array identity; every mounted
// row then looks up its id. A selector that scanned the transcript itself
// would rerun mounted-rows × length on every streamed chunk.

interface ClockPart {
  completedAt?: unknown
  text?: unknown
  timestamp?: unknown
  type?: unknown
}

interface ClockCustom {
  durationS?: unknown
  timelineCompletedAt?: unknown
  timelineTimestamp?: unknown
}

export interface TurnClockMessage {
  content?: readonly ClockPart[]
  id: string
  metadata?: { custom?: ClockCustom }
  role: string
  status?: { type?: string }
}

const durationsByTranscript = new WeakMap<readonly TurnClockMessage[], Map<string, number>>()

const finiteSeconds = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined

/** Authored unix seconds. `createdAt` alone is not enough: a row with no
 *  stored timestamp falls back to the conversion clock, which would paint a
 *  multi-hour duration onto an undated reply. */
const authoredSeconds = (message: TurnClockMessage): number | undefined =>
  finiteSeconds(message.metadata?.custom?.timelineTimestamp)

const consider = (latest: number | undefined, value: number | undefined): number | undefined =>
  value !== undefined && (latest === undefined || value > latest) ? value : latest

const latestAuthoredSeconds = (message: TurnClockMessage): number | undefined => {
  let latest = consider(undefined, authoredSeconds(message))

  latest = consider(latest, finiteSeconds(message.metadata?.custom?.timelineCompletedAt))

  for (const part of message.content ?? []) {
    latest = consider(latest, finiteSeconds(part?.timestamp))
    latest = consider(latest, finiteSeconds(part?.completedAt))
  }

  return latest
}

const hasVisibleText = (message: TurnClockMessage): boolean =>
  (message.content ?? []).some(part => part?.type === 'text' && typeof part.text === 'string' && part.text.trim().length > 0)

const explicitDuration = (message: TurnClockMessage): number | undefined => {
  const value = finiteSeconds(message.metadata?.custom?.durationS)

  return value !== undefined ? Math.max(1, Math.round(value)) : undefined
}

const buildDurations = (messages: readonly TurnClockMessage[]): Map<string, number> => {
  const durations = new Map<string, number>()
  let turnStart: number | undefined
  let end: number | undefined
  let lastTextId: string | undefined
  let running = false

  const closeTurn = () => {
    // A watched turn already stamped the exact number; the derived span is the
    // fallback for history only, and never overrides it.
    if (!running && lastTextId !== undefined && turnStart !== undefined && end !== undefined && end > turnStart) {
      if (!durations.has(lastTextId)) {
        durations.set(lastTextId, Math.max(1, Math.round(end - turnStart)))
      }
    }

    turnStart = undefined
    end = undefined
    lastTextId = undefined
    running = false
  }

  for (const message of messages) {
    if (message.role === 'user') {
      closeTurn()
      turnStart = authoredSeconds(message)

      continue
    }

    // The desktop's own measurement rides the settled reply and belongs to it
    // alone, whether or not the user row was timestamped.
    const watched = explicitDuration(message)

    if (watched !== undefined) {
      durations.set(message.id, watched)
    }

    if (turnStart === undefined) {
      continue
    }

    // Only assistant rows measure the turn's work. A system row (background
    // delivery, compaction notice) can land long after the reply and must not
    // stretch the derived span.
    if (message.role !== 'assistant') {
      continue
    }

    if (message.status?.type === 'running') {
      running = true
    }

    end = consider(end, latestAuthoredSeconds(message))

    if (hasVisibleText(message)) {
      lastTextId = message.id
    }
  }

  closeTurn()

  return durations
}

/** Seconds this turn took, for the assistant message that carries the footer.
 *  Undefined while the turn is still running, or when neither a watched
 *  `durationS` nor authored start/end timestamps exist. */
export function turnDurationSeconds(messages: readonly TurnClockMessage[], messageId: string): number | undefined {
  let durations = durationsByTranscript.get(messages)

  if (!durations) {
    durations = buildDurations(messages)
    durationsByTranscript.set(messages, durations)
  }

  return durations.get(messageId)
}
