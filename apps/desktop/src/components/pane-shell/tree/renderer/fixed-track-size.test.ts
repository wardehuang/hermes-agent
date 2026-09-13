import { describe, expect, it } from 'vitest'

import type { Contribution } from '@/contrib/types'

import { group, split } from '../model'

import { fixedTrackSize, MINIMIZED_TRACK, type TrackContext } from './track-model'

function ctx(data: Record<string, object>): TrackContext {
  return {
    overrides: {},
    paneFor: id =>
      ({
        area: 'panes',
        data: data[id] ?? {},
        id,
        render: () => null,
        title: id
      }) as Contribution,
    paneGone: () => false
  }
}

describe('fixedTrackSize nested minimized rails', () => {
  const panes = ctx({
    editor: { minWidth: '22vw', placement: 'main' },
    terminal: { height: '20vh', placement: 'bottom' },
    workspace: { placement: 'main' }
  })

  it('does not report a minimized bottom rail as the column WIDTH', () => {
    const center = split(
      'column',
      [group(['editor'], { id: 'grp-editor' }), group(['terminal'], { id: 'grp-terminal', minimized: true })],
      [2.2, 1],
      'spl-center'
    )

    expect(fixedTrackSize(center, 'row', panes)).toBeNull()
  })

  it('keeps a column with an open terminal flex along WIDTH', () => {
    const center = split(
      'column',
      [group(['editor'], { id: 'grp-editor' }), group(['terminal'], { id: 'grp-terminal' })],
      [2.2, 1],
      'spl-center'
    )

    expect(fixedTrackSize(center, 'row', panes)).toBeNull()
  })

  it('still reports the minimized rail as HEIGHT when asked as a group', () => {
    const terminal = group(['terminal'], { id: 'grp-terminal', minimized: true })

    expect(fixedTrackSize(terminal, 'column', panes)).toBe(MINIMIZED_TRACK)
  })

  it('does not report a minimized side rail as the row HEIGHT', () => {
    const row = split(
      'row',
      [group(['sessions'], { id: 'grp-sessions', minimized: true }), group(['workspace'], { id: 'grp-main' })],
      [1, 3]
    )
    const sidePanes = ctx({
      sessions: { placement: 'left', width: '237px' },
      workspace: { placement: 'main' }
    })

    expect(fixedTrackSize(row, 'column', sidePanes)).toBeNull()
  })
})
