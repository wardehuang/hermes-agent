import { describe, expect, it } from 'vitest'

import { completePathWord, parseCompletePathHit } from './go-to-file'

describe('completePathWord', () => {
  it('prefixes a typed query with @', () => {
    expect(completePathWord('main')).toBe('@main')
    expect(completePathWord('  src/app  ')).toBe('@src/app')
  })

  it('keeps a query that is already an @-word', () => {
    expect(completePathWord('@file:main')).toBe('@file:main')
  })
})

describe('parseCompletePathHit', () => {
  it('keeps files and folders and drops other @-kinds', () => {
    expect(parseCompletePathHit({ display: 'main.tsx', meta: 'src', text: '@file:src/main.tsx' })).toEqual({
      kind: 'file',
      label: 'main.tsx',
      parent: 'src',
      rel: 'src/main.tsx'
    })
    expect(parseCompletePathHit({ display: 'desktop/', meta: 'dir', text: '@folder:apps/desktop/' })).toEqual({
      kind: 'folder',
      label: 'desktop',
      parent: 'apps',
      rel: 'apps/desktop'
    })
    expect(parseCompletePathHit({ text: '@diff' })).toBeNull()
    expect(parseCompletePathHit({ text: '@alice' })).toBeNull()
  })

  it('unwraps backtick-quoted paths', () => {
    expect(parseCompletePathHit({ display: 'my file.ts', meta: 'src', text: '@file:`src/my file.ts`' })).toEqual({
      kind: 'file',
      label: 'my file.ts',
      parent: 'src',
      rel: 'src/my file.ts'
    })
  })
})
