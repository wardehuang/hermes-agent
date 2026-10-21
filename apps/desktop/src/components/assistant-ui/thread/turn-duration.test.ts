import { describe, expect, it } from 'vitest'

import { type TurnClockMessage, turnDurationSeconds } from './turn-duration'

const user = (id: string, timestamp: number): TurnClockMessage => ({
  id,
  role: 'user',
  metadata: { custom: { timelineTimestamp: timestamp } }
})

const assistant = (
  id: string,
  timestamp: number,
  text = 'Done.',
  extra: Partial<TurnClockMessage> = {}
): TurnClockMessage => ({
  id,
  role: 'assistant',
  content: [{ type: 'text', text, timestamp }],
  metadata: { custom: { timelineTimestamp: timestamp } },
  status: { type: 'complete' },
  ...extra
})

describe('turnDurationSeconds', () => {
  it('uses the watched duration when the desktop saw the turn finish', () => {
    const messages = [
      user('u', 100),
      assistant('a', 400, 'Done.', {
        metadata: { custom: { durationS: 38.2, timelineTimestamp: 400 } }
      })
    ]

    expect(turnDurationSeconds(messages, 'a')).toBe(38)
  })

  it('derives history from the user row to the latest authored timestamp', () => {
    const messages = [
      user('u', 1_000),
      {
        id: 'tools',
        role: 'assistant',
        content: [
          { type: 'tool-call', timestamp: 1_010, completedAt: 1_040 },
          { type: 'text', text: 'Done.', timestamp: 1_060 }
        ],
        metadata: { custom: { timelineTimestamp: 1_010 } },
        status: { type: 'complete' }
      } satisfies TurnClockMessage
    ]

    expect(turnDurationSeconds(messages, 'tools')).toBe(60)
  })

  it('puts the whole turn on the last text reply, including a later tool row', () => {
    const messages = [
      user('u', 100),
      assistant('a', 110, 'Working.'),
      {
        id: 'tail-tools',
        role: 'assistant',
        content: [{ type: 'tool-call', timestamp: 150, completedAt: 180 }],
        metadata: { custom: { timelineTimestamp: 150 } },
        status: { type: 'complete' }
      } satisfies TurnClockMessage
    ]

    expect(turnDurationSeconds(messages, 'a')).toBe(80)
    expect(turnDurationSeconds(messages, 'tail-tools')).toBeUndefined()
  })

  it('keeps each user turn separate', () => {
    const messages = [user('u1', 10), assistant('a1', 15), user('u2', 40), assistant('a2', 70)]

    expect(turnDurationSeconds(messages, 'a1')).toBe(5)
    expect(turnDurationSeconds(messages, 'a2')).toBe(30)
  })

  it('ignores a system notice that lands after the reply', () => {
    const messages: TurnClockMessage[] = [
      user('u', 100),
      assistant('a', 130),
      { id: 'notice', role: 'system', content: [{ type: 'text', text: 'Compacted.', timestamp: 900 }] }
    ]

    expect(turnDurationSeconds(messages, 'a')).toBe(30)
  })

  it('stays blank while the turn is still running', () => {
    const messages = [user('u', 100), assistant('a', 110, 'partial', { status: { type: 'running' } })]

    expect(turnDurationSeconds(messages, 'a')).toBeUndefined()
  })

  it('does not invent a duration without an authored start', () => {
    const messages = [assistant('greeting', 50, 'Hello.')]

    expect(turnDurationSeconds(messages, 'greeting')).toBeUndefined()
  })

  it('rounds a sub-second turn up to one second and ignores a non-positive span', () => {
    expect(turnDurationSeconds([user('u', 10), assistant('a', 10.4)], 'a')).toBe(1)
    expect(turnDurationSeconds([user('u', 10), assistant('a', 10)], 'a')).toBeUndefined()
  })
})
