import { describe, expect, it } from 'vitest'

import { generatedVideoFromResult } from './generated-videos'

describe('generatedVideoFromResult', () => {
  it('reads the primary video field', () => {
    expect(
      generatedVideoFromResult({
        success: true,
        video: 'https://cdn.example/media/videos/vid_abc'
      })
    ).toBe('https://cdn.example/media/videos/vid_abc')
  })

  it('falls back to extra.public_url when video is missing', () => {
    expect(
      generatedVideoFromResult({
        extra: { public_url: 'https://cdn.example/v.mp4' },
        success: true
      })
    ).toBe('https://cdn.example/v.mp4')
  })

  it('ignores failed video generation results', () => {
    expect(generatedVideoFromResult({ success: false, video: 'https://cdn.example/v.mp4' })).toBeNull()
  })

  it('parses JSON string tool results', () => {
    expect(
      generatedVideoFromResult(
        JSON.stringify({
          success: true,
          video: 'C:\\Users\\me\\.hermes\\cache\\videos\\clip.mp4'
        })
      )
    ).toBe('C:\\Users\\me\\.hermes\\cache\\videos\\clip.mp4')
  })
})
