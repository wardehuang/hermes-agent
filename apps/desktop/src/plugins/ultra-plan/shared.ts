export const ID = 'ultra-plan'

export type PlanMode = 'agent' | 'plan'

export type PlanComment = {
  body: string
  id: string
  quote: string
}

export const PLAN_REL_RE = /^\.hermes\/plans\/[A-Za-z0-9._-]+\.md$/

export function toPosix(path: string): string {
  return path.replace(/\\/g, '/')
}

export function normalizePlanRel(path: string): null | string {
  const posix = toPosix(path).trim().replace(/^['"]|['"]$/g, '')
  const match = posix.match(/\.hermes\/plans\/[A-Za-z0-9._-]+\.md$/)

  return match ? match[0] : null
}

export function isPlanRel(path: string): boolean {
  return PLAN_REL_RE.test(normalizePlanRel(path) ?? '')
}

export function planBasename(path: string): string {
  const rel = normalizePlanRel(path) ?? path
  const parts = toPosix(rel).split('/')

  return parts[parts.length - 1] || rel
}

export function resolvePlanAbs(cwd: string, rel: string): null | string {
  const normalized = normalizePlanRel(rel)

  if (!normalized || !cwd.trim()) {
    return null
  }

  const sep = cwd.includes('\\') && !cwd.includes('/') ? '\\' : '/'

  return cwd.replace(/[\\/]+$/, '') + sep + normalized.replace(/\//g, sep)
}

export function newCommentId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}
