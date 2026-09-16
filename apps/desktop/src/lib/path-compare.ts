/** Comparing two paths for identity or containment, across host spellings.
 *
 *  A cwd reaches us from the backend, a picker, a session row and a project
 *  record, and the four don't agree on separator, trailing slash or drive-letter
 *  case. Compare through these rather than `===` / `startsWith`.
 */

/** POSIX-style spelling: one separator, no trailing slash. */
export const cleanPath = (path: string): string => path.trim().replace(/\\/g, '/').replace(/\/+$/, '') || '/'

/** Case-folded comparison key. Windows drive/UNC paths are case-insensitive;
 *  POSIX paths are not, and callers that display a path want its real spelling,
 *  so fold only the key. Expects an already-`cleanPath`ed value. */
export const comparisonPath = (path: string): string =>
  /^[A-Za-z]:(?:\/|$)/.test(path) || path.startsWith('//') ? path.toLowerCase() : path

/** True when `child` IS `parent` or lives underneath it. */
export const isUnderPath = (parent: string, child: string): boolean => {
  const p = comparisonPath(cleanPath(parent))
  const c = comparisonPath(cleanPath(child))

  return c === p || c.startsWith(`${p}/`)
}

/** Windows drive/UNC paths compare case-insensitively; POSIX paths do not. */
export const windowsPathIgnoresCase = (path: string): boolean => {
  const cleaned = cleanPath(path)

  return comparisonPath(cleaned) !== cleaned
}

/** Join a repo-relative path onto a project cwd. Absolute `rel` wins. */
export const joinProjectPath = (root: string, rel: string): string => {
  const r = cleanPath(root)
  const raw = rel.trim().replace(/\\/g, '/')

  if (!raw || raw === '.') {
    return r
  }

  if (raw.startsWith('//') || /^[A-Za-z]:(?:\/|$)/.test(raw)) {
    return cleanPath(raw)
  }

  if (raw.startsWith('/') && !/^[A-Za-z]:/.test(r)) {
    return cleanPath(raw)
  }

  return cleanPath(`${r}/${raw.replace(/^\//, '')}`)
}

/** Path segments from `root` to `child`, or null when `child` is outside `root`. */
export const relativePathSegments = (root: string, child: string): string[] | null => {
  const r = cleanPath(root)
  const c = cleanPath(child)
  const rKey = comparisonPath(r)
  const cKey = comparisonPath(c)

  if (cKey === rKey) {
    return []
  }

  if (!cKey.startsWith(`${rKey}/`)) {
    return null
  }

  return c.slice(r.length + (r.endsWith('/') ? 0 : 1)).split('/').filter(Boolean)
}
