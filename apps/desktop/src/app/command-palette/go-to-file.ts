import { normalizeOrLocalPreviewTarget } from '@/lib/local-preview'
import { joinProjectPath } from '@/lib/path-compare'
import { revealFileInTree } from '@/store/layout'
import { openPreview } from '@/store/preview'

export interface CompletePathItem {
  display?: string
  meta?: string
  text: string
}

export interface ProjectFileHit {
  kind: 'file' | 'folder'
  label: string
  parent: string
  rel: string
}

const HIT_RE = /^@(file|folder):(.+)$/

export function completePathWord(query: string): string {
  const trimmed = query.trim()

  if (!trimmed) {
    return '@'
  }

  return trimmed.startsWith('@') ? trimmed : `@${trimmed}`
}

function unquotePath(raw: string): string {
  const head = raw[0]
  const tail = raw[raw.length - 1]
  const quoted = (head === '`' && tail === '`') || (head === '"' && tail === '"') || (head === "'" && tail === "'")

  return (quoted ? raw.slice(1, -1) : raw).trim()
}

export function parseCompletePathHit(item: CompletePathItem): ProjectFileHit | null {
  const match = HIT_RE.exec(item.text.trim())

  if (!match) {
    return null
  }

  const kind = match[1] as 'file' | 'folder'
  const rel = unquotePath(match[2]).replace(/\\/g, '/').replace(/\/+$/, '')

  if (!rel) {
    return null
  }

  const parts = rel.split('/').filter(Boolean)
  const label = (item.display?.replace(/\/+$/, '') || parts[parts.length - 1] || rel).trim()

  if (!label) {
    return null
  }

  const parent =
    kind === 'file' && item.meta && item.meta !== 'dir' ? item.meta.replace(/\\/g, '/') : parts.slice(0, -1).join('/')

  return { kind, label, parent, rel }
}

export async function fetchProjectFileHits(
  request: <T>(method: string, params: Record<string, unknown>) => Promise<T>,
  opts: { cwd: string; query: string; sessionId?: string | null }
): Promise<ProjectFileHit[]> {
  const result = await request<{ items?: CompletePathItem[] }>('complete.path', {
    cwd: opts.cwd,
    word: completePathWord(opts.query),
    ...(opts.sessionId ? { session_id: opts.sessionId } : {})
  })

  return (result.items ?? []).flatMap(item => {
    const hit = parseCompletePathHit(item)

    return hit ? [hit] : []
  })
}

/** Reveal in the Files tree. Files also open in the in-app editor/preview. */
export async function jumpToProjectHit(hit: ProjectFileHit, cwd: string): Promise<boolean> {
  const abs = joinProjectPath(cwd, hit.rel)

  revealFileInTree(abs)

  if (hit.kind === 'folder') {
    return true
  }

  const target = await normalizeOrLocalPreviewTarget(abs, cwd)

  if (!target) {
    return false
  }

  openPreview(target, 'file-browser')

  return true
}
