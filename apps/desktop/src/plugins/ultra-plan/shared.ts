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

export function planDisplayTitle(path: string): string {
  const base = planBasename(path).replace(/\.md$/i, '')
  const stripped = base.replace(/^\d{4}-\d{2}-\d{2}_\d{6}-/, '').replace(/[-_]+/g, ' ').trim()

  if (!stripped) {
    return base
  }

  return stripped.charAt(0).toUpperCase() + stripped.slice(1)
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

export type PlanTask = {
  done: boolean
  text: string
}

const TASK_HEADING = /^#{1,3}\s+(任务|tasks)\s*$/i
const TASK_ITEM = /^[-*]\s+\[([ xX])\]\s+(.+)$/
const ANY_HEADING = /^#{1,3}\s+\S/

export function planTasks(markdown: string): PlanTask[] {
  const tasks: PlanTask[] = []
  let inTasks = false

  for (const line of markdown.split(/\r?\n/)) {
    const trimmed = line.trim()

    if (TASK_HEADING.test(trimmed)) {
      inTasks = true

      continue
    }

    if (inTasks && ANY_HEADING.test(trimmed)) {
      break
    }

    if (!inTasks) {
      continue
    }

    const item = TASK_ITEM.exec(trimmed)

    if (!item) {
      continue
    }

    tasks.push({ done: item[1].toLowerCase() === 'x', text: item[2].trim() })
  }

  return tasks
}

export function planBodyWithoutTasks(markdown: string): string {
  const kept: string[] = []
  let skipping = false

  for (const line of markdown.split(/\r?\n/)) {
    const trimmed = line.trim()

    if (TASK_HEADING.test(trimmed)) {
      skipping = true

      continue
    }

    if (skipping && ANY_HEADING.test(trimmed)) {
      skipping = false
    }

    if (!skipping) {
      kept.push(line)
    }
  }

  return kept.join('\n').replace(/^\n+/, '').replace(/\n{3,}/g, '\n\n')
}
