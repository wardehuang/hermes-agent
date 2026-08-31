import { describe, expect, it } from 'vitest'

import {
  dedupeGeneratedImageEchoesInParts,
  generatedImageEchoSources,
  generatedImageFromResult,
  generatedImagesFromResult,
  stripGeneratedImageEchoes
} from './generated-images'

describe('generatedImageFromResult', () => {
  it('prefers the host-visible image path', () => {
    expect(
      generatedImageFromResult({
        agent_visible_image: '/container/cache/cat.png',
        host_image: '/Users/me/.hermes/cache/images/cat.png',
        image: '/Users/me/.hermes/cache/images/cat.png',
        success: true
      })
    ).toBe('/Users/me/.hermes/cache/images/cat.png')
  })

  it('ignores failed image generation results', () => {
    expect(generatedImageFromResult({ image: 'https://cdn.example/cat.png', success: false })).toBeNull()
  })
})

describe('generatedImagesFromResult', () => {
  it('returns every path from the images array', () => {
    expect(
      generatedImagesFromResult({
        image: '/host/a.png',
        images: ['/host/a.png', '/host/b.png'],
        success: true
      })
    ).toEqual(['/host/a.png', '/host/b.png'])
  })

  it('falls back to the scalar host path when images is absent', () => {
    expect(
      generatedImagesFromResult({
        host_image: '/host/cat.png',
        image: '/host/cat.png',
        success: true
      })
    ).toEqual(['/host/cat.png'])
  })

  it('ignores failed image generation results', () => {
    expect(
      generatedImagesFromResult({
        image: '/host/a.png',
        images: ['/host/a.png', '/host/b.png'],
        success: false
      })
    ).toEqual([])
  })
})

describe('stripGeneratedImageEchoes', () => {
  it('removes repeated generated image markdown without removing prose', () => {
    expect(
      stripGeneratedImageEchoes('Here you go.\n\n![Generated image](https://cdn.example/cat.png)', [
        'https://cdn.example/cat.png'
      ])
    ).toBe('Here you go.')
  })

  it('removes media links for generated local image paths', () => {
    expect(stripGeneratedImageEchoes('Saved image: [Image: cat.png](#media:%2Ftmp%2Fcat.png)', ['/tmp/cat.png'])).toBe(
      'Saved image:'
    )
  })
})

describe('generatedImageEchoSources', () => {
  it('collects every path variant the model might restate', () => {
    expect(
      generatedImageEchoSources([
        {
          result: {
            agent_visible_image: '/sandbox/cat.png',
            host_image: '/host/cat.png',
            image: '/host/cat.png',
            success: true
          },
          toolName: 'image_generate',
          type: 'tool-call'
        }
      ])
    ).toEqual(['/host/cat.png', '/sandbox/cat.png'])
  })

  it('collects every n>1 path so restated extras are stripped', () => {
    expect(
      generatedImageEchoSources([
        {
          result: {
            image: '/host/a.png',
            images: ['/host/a.png', '/host/b.png'],
            success: true
          },
          toolName: 'image_generate',
          type: 'tool-call'
        }
      ])
    ).toEqual(['/host/a.png', '/host/b.png'])
  })
})

describe('dedupeGeneratedImageEchoesInParts', () => {
  it('keeps the agent prose while removing the duplicated image', () => {
    expect(
      dedupeGeneratedImageEchoesInParts([
        { text: 'Here is your peacock! ![peacock](/host/p.png) Enjoy.', type: 'text' },
        {
          result: { host_image: '/host/p.png', image: '/host/p.png', success: true },
          toolName: 'image_generate',
          type: 'tool-call'
        }
      ])
    ).toEqual([
      { text: 'Here is your peacock! Enjoy.', type: 'text' },
      {
        result: { host_image: '/host/p.png', image: '/host/p.png', success: true },
        toolName: 'image_generate',
        type: 'tool-call'
      }
    ])
  })

  it('strips a sandbox path the model restated instead of the host path', () => {
    expect(
      dedupeGeneratedImageEchoesInParts([
        { text: '![cat](/sandbox/cat.png)', type: 'text' },
        {
          result: {
            agent_visible_image: '/sandbox/cat.png',
            host_image: '/host/cat.png',
            image: '/host/cat.png',
            success: true
          },
          toolName: 'image_generate',
          type: 'tool-call'
        }
      ])
    ).toEqual([
      {
        result: {
          agent_visible_image: '/sandbox/cat.png',
          host_image: '/host/cat.png',
          image: '/host/cat.png',
          success: true
        },
        toolName: 'image_generate',
        type: 'tool-call'
      }
    ])
  })

  it('leaves pending generations untouched so the agent prose survives', () => {
    const parts = [
      { text: 'Another peacock, coming up!', type: 'text' },
      { result: undefined, toolName: 'image_generate', type: 'tool-call' }
    ]

    expect(dedupeGeneratedImageEchoesInParts(parts)).toEqual(parts)
  })
})
