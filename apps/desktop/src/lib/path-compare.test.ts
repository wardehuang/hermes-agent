import { describe, expect, it } from 'vitest'

import {
  cleanPath,
  comparisonPath,
  isUnderPath,
  joinProjectPath,
  relativePathSegments,
  windowsPathIgnoresCase
} from './path-compare'

describe('cleanPath', () => {
  it('unifies separators and drops trailing slashes', () => {
    expect(cleanPath('C:\\Repos\\App\\')).toBe('C:/Repos/App')
    expect(cleanPath('  /home/user/repo//  ')).toBe('/home/user/repo')
  })

  it('keeps root rather than collapsing to empty', () => {
    expect(cleanPath('/')).toBe('/')
  })
})

describe('comparisonPath', () => {
  it('folds case for Windows drive and UNC paths only', () => {
    expect(comparisonPath('C:/Repos/App')).toBe('c:/repos/app')
    expect(comparisonPath('//server/Share')).toBe('//server/share')
    expect(comparisonPath('/home/User/Repo')).toBe('/home/User/Repo')
  })
})

describe('isUnderPath', () => {
  it('matches a nested path across separator and case differences', () => {
    expect(isUnderPath('C:\\Repos\\App', 'c:/repos/app/src')).toBe(true)
    expect(isUnderPath('C:/Repos/App/', 'C:\\Repos\\App')).toBe(true)
  })

  it('stays case-sensitive on POSIX', () => {
    expect(isUnderPath('/home/user/repo', '/home/user/repo/src')).toBe(true)
    expect(isUnderPath('/home/user/repo', '/home/user/Repo/src')).toBe(false)
  })

  it('does not treat a sibling with a shared prefix as nested', () => {
    expect(isUnderPath('/repos/app', '/repos/app-retry')).toBe(false)
  })
})

describe('joinProjectPath', () => {
  it('joins a relative path onto the cwd', () => {
    expect(joinProjectPath('C:\\Repos\\App\\', 'src\\main.tsx')).toBe('C:/Repos/App/src/main.tsx')
    expect(joinProjectPath('/home/user/repo', 'apps/desktop/src/main.tsx')).toBe(
      '/home/user/repo/apps/desktop/src/main.tsx'
    )
  })

  it('keeps an absolute Windows or POSIX path', () => {
    expect(joinProjectPath('/home/user/repo', '/etc/hosts')).toBe('/etc/hosts')
    expect(joinProjectPath('C:/Repos/App', 'D:/other/file.ts')).toBe('D:/other/file.ts')
  })
})

describe('relativePathSegments', () => {
  it('splits the nested path even when separators and drive case differ', () => {
    expect(relativePathSegments('C:\\Repos\\App', 'c:/repos/app/src/main.tsx')).toEqual(['src', 'main.tsx'])
    expect(relativePathSegments('/home/user/repo', '/home/user/repo/apps/desktop/src/main.tsx')).toEqual([
      'apps',
      'desktop',
      'src',
      'main.tsx'
    ])
  })

  it('returns null outside the project and [] at the root', () => {
    expect(relativePathSegments('/home/user/repo', '/home/user/other/file.ts')).toBeNull()
    expect(relativePathSegments('C:/Repos/App', 'C:/Repos/App')).toEqual([])
  })
})

describe('windowsPathIgnoresCase', () => {
  it('is true only for Windows drive and UNC paths', () => {
    expect(windowsPathIgnoresCase('C:/Repos/App')).toBe(true)
    expect(windowsPathIgnoresCase('/home/User/Repo')).toBe(false)
  })
})
