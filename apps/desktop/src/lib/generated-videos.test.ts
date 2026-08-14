import { describe, expect, it } from 'vitest'

import {
  dedupeGeneratedVideoEchoesInParts,
  generatedVideoEchoSources,
  generatedVideoFromResult,
  stripGeneratedVideoEchoes
} from './generated-videos'

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

describe('stripGeneratedVideoEchoes', () => {
  it('removes restated remote video URLs without removing prose', () => {
    expect(
      stripGeneratedVideoEchoes('Done.\n\nhttps://cdn.example/media/videos/vid_abc', [
        'https://cdn.example/media/videos/vid_abc'
      ])
    ).toBe('Done.')
  })

  it('removes media links for generated local video paths', () => {
    expect(
      stripGeneratedVideoEchoes('Saved video: [Video: clip.mp4](#media:%2Ftmp%2Fclip.mp4)', ['/tmp/clip.mp4'])
    ).toBe('Saved video:')
  })
})

describe('generatedVideoEchoSources', () => {
  it('collects video and extra URL variants the model might restate', () => {
    expect(
      generatedVideoEchoSources([
        {
          result: {
            extra: {
              public_url: 'https://cdn.example/public.mp4',
              remote_url: 'https://cdn.example/content'
            },
            success: true,
            video: 'https://cdn.example/media/videos/vid_abc'
          },
          toolName: 'video_generate',
          type: 'tool-call'
        }
      ])
    ).toEqual([
      'https://cdn.example/media/videos/vid_abc',
      'https://cdn.example/public.mp4',
      'https://cdn.example/content'
    ])
  })
})

describe('dedupeGeneratedVideoEchoesInParts', () => {
  it('keeps agent prose while removing the duplicated video URL', () => {
    expect(
      dedupeGeneratedVideoEchoesInParts([
        { text: 'Here is your clip! https://cdn.example/v.mp4 Enjoy.', type: 'text' },
        {
          result: { success: true, video: 'https://cdn.example/v.mp4' },
          toolName: 'video_generate',
          type: 'tool-call'
        }
      ])
    ).toEqual([
      { text: 'Here is your clip! Enjoy.', type: 'text' },
      {
        result: { success: true, video: 'https://cdn.example/v.mp4' },
        toolName: 'video_generate',
        type: 'tool-call'
      }
    ])
  })

  it('leaves pending generations untouched so the agent prose survives', () => {
    const parts = [
      { text: 'Animating next…', type: 'text' },
      { result: undefined, toolName: 'video_generate', type: 'tool-call' }
    ]

    expect(dedupeGeneratedVideoEchoesInParts(parts)).toEqual(parts)
  })
})
