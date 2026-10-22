import { normalizeWs as normalizedText } from './parts'
import type { ChatMessage, ChatMessagePart } from './types'

function sameOccurrencePart(stored: ChatMessagePart, local: ChatMessagePart): boolean {
  if (stored.type === 'tool-call' && local.type === 'tool-call') {
    return Boolean(stored.toolCallId) && stored.toolCallId === local.toolCallId
  }

  if ((stored.type === 'text' || stored.type === 'reasoning') && local.type === stored.type) {
    return normalizedText(stored.text) === normalizedText(local.text)
  }

  return false
}

const toolCallIds = (message: ChatMessage): string[] =>
  message.parts.flatMap(part => (part.type === 'tool-call' && part.toolCallId ? [part.toolCallId] : []))

const textParts = (message: ChatMessage): string[] =>
  message.parts.flatMap(part => (part.type === 'text' ? [part.text.trim()] : [])).filter(Boolean)

/**
 * Drop the live bubbles a stored transcript already carries.
 *
 * A tool-heavy turn fills the hydration page entirely, so the page's newest rows
 * ARE the turn the window streamed. Its live bubbles carry no rowId, so every
 * stored-id merge has nothing to pair them with: they ride in front of the next
 * durable row, or after the newest one, and the same commentary paints again at
 * the bottom of the transcript.
 *
 * Coverage is proved the way hydration really folds a turn: one durable row can
 * hold every bubble the stream sealed (commentary, tool calls, answer), so
 * bubble ordinals and equal counts prove nothing. A live bubble is covered only
 * when the stored turn carries every tool call it ran (call ids are unique to
 * the turn) and every text it showed appears whole in that turn's text. Anything
 * else — a turn the page only partly covers, an unpaired repeated paragraph —
 * stays.
 *
 * Only the stored turn the live tail belongs to can cover it: the rows after the
 * transcript's newest prompt. Earlier turns are other occurrences.
 */
export function withoutPageCoveredLiveBubbles(previous: ChatMessage[], page: ChatMessage[]): ChatMessage[] {
  const lastPrompt = previous.findLastIndex(message => message.role === 'user')
  const liveStart = lastPrompt < 0 ? 0 : lastPrompt + 1
  const live = previous.slice(liveStart)

  if (!live.some(message => message.role === 'assistant' && message.rowId === undefined)) {
    return previous
  }

  const lastPagePrompt = page.findLastIndex(message => message.role === 'user')

  const storedAssistants = page
    .slice(lastPagePrompt + 1)
    .filter(message => message.role === 'assistant' && message.rowId !== undefined)

  if (!storedAssistants.length) {
    return previous
  }

  const storedToolIds = new Set(storedAssistants.flatMap(toolCallIds))
  const storedTexts = storedAssistants.flatMap(textParts)

  const covered = (message: ChatMessage): boolean => {
    if (toolCallIds(message).some(id => !storedToolIds.has(id))) {
      return false
    }

    // A sealed segment is its own text part in the folded row, so the stored
    // copy either equals it or extends it by the delta that streamed after.
    return textParts(message).every(text => storedTexts.some(stored => stored === text || stored.startsWith(text)))
  }

  const liveAssistants = live.filter(message => message.role === 'assistant' && message.rowId === undefined)

  // All-or-nothing on purpose. A page that carries SOME of the turn is a page
  // that stops mid-turn; dropping just the covered bubbles would leave the
  // rest of the run without the siblings the pairing below expects, and the
  // turn's own reply can be lost with them. Only a page that already holds the
  // WHOLE run makes every live bubble redundant.
  if (!liveAssistants.every(covered)) {
    return previous
  }

  return [...previous.slice(0, liveStart), ...live.filter(message => !liveAssistants.includes(message))]
}

/** Subtract an ordered, tool-anchored prefix within an already matched user
 * interval. Hydration can fold several live bubbles into one durable row;
 * bubble ordinals and equal text alone cannot establish that coverage. */
export function withoutCoveredAssistantPrefix(stored: ChatMessage[], local: ChatMessage[]): ChatMessage[] {
  const parts = stored.flatMap(message => (message.role === 'assistant' ? message.parts : []))
  let cursor = 0
  let anchored = false
  let stopped = false
  const remaining: ChatMessage[] = []

  for (const message of local) {
    if (stopped || message.role !== 'assistant' || message.error) {
      stopped = true
      remaining.push(message)

      continue
    }

    let consumed = 0

    for (const part of message.parts) {
      if (!parts[cursor] || !sameOccurrencePart(parts[cursor], part)) {
        break
      }

      anchored ||= part.type === 'tool-call'
      cursor += 1
      consumed += 1
    }

    if (consumed < message.parts.length) {
      stopped = true
      remaining.push(consumed ? { ...message, parts: message.parts.slice(consumed) } : message)
    }
  }

  // A coincidentally equal paragraph, without the same tool occurrence after
  // it, is insufficient evidence to remove anything.
  return anchored ? remaining : local
}
