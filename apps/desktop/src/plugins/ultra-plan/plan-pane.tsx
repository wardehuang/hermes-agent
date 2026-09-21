import { MarkdownPreview } from '@/app/chat/right-rail/preview-file'
import { CodeEditor } from '@/components/chat/code-editor'
import { readDesktopFileText, writeDesktopFileText } from '@/lib/desktop-fs'
import {
  Button,
  cn,
  Codicon,
  host,
  Textarea,
  usePluginI18n,
  useValue
} from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'

import { ID, newCommentId, normalizePlanRel, resolvePlanAbs, type PlanComment } from './shared'
import {
  $comments,
  $commentsEpoch,
  $planFile,
  $pluginCtx,
  applyMode,
  armPlanAutoOpen,
  bindPlanDispose,
  clearComments,
  commentsFor,
  consumePlanAutoOpen,
  durableSessionId,
  hideRightSidebarForPlan,
  isPlanViewOpen,
  onPlanViewClosed,
  planTitle,
  runtimeSessionId,
  setComments
} from './plan-store'

type LoadState = 'error' | 'loading' | 'ready'

export function PlanPane() {
  const t = usePluginI18n(ID)
  const file = useValue($planFile)
  const allComments = useValue($comments)
  const cwd = useValue(host.state.cwd)
  const comments = file ? (allComments[file] ?? []) : []
  const commentsEpoch = useValue($commentsEpoch)
  const abs = file ? resolvePlanAbs(cwd, file) : null
  const [load, setLoad] = useState<LoadState>('loading')
  const [text, setText] = useState('')
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [quote, setQuote] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const previewRef = useRef<HTMLDivElement | null>(null)
  const loadKey = `${abs ?? ''}:${file ?? ''}`

  useEffect(() => {
    let cancelled = false
    setEditing(false)
    setQuote('')
    setCommentBody('')
    if (!file) {
      setLoad('error')
      return
    }
    if (!cwd.trim() || !abs) {
      setLoad('error')
      setText('')
      return
    }
    setLoad('loading')
    void readDesktopFileText(abs)
      .then(result => {
        if (cancelled) {
          return
        }
        const next = result.text ?? ''
        setText(next)
        setDraft(next)
        setLoad('ready')
      })
      .catch(() => {
        if (!cancelled) {
          setLoad('error')
          setText('')
        }
      })
    return () => {
      cancelled = true
    }
  }, [abs, cwd, file, loadKey])

  useEffect(() => {
    if (commentsEpoch === 0) {
      return
    }
    setQuote('')
    setCommentBody('')
  }, [commentsEpoch])

  useEffect(() => {
    const onMouseUp = (event: MouseEvent) => {
      const target = event.target
      if (target instanceof Element && target.closest('[data-ultra-plan="comment-draft"]')) {
        return
      }
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed) {
        setQuote('')
        return
      }
      const node = sel.anchorNode
      if (!previewRef.current || !node || !previewRef.current.contains(node)) {
        setQuote('')
        return
      }
      const next = sel.toString().trim()
      if (!next || next.length > 800) {
        setQuote('')
        return
      }
      setQuote(next)
    }
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  const addComment = () => {
    if (!file) {
      return
    }
    const body = commentBody.trim()
    const selected = quote.trim()
    if (!body && !selected) {
      return
    }
    const next: PlanComment = { body, id: newCommentId(), quote: selected }
    setComments(file, [...commentsFor(file), next])
    setCommentBody('')
    setQuote('')
    window.getSelection()?.removeAllRanges()
  }

  const removeComment = (id: string) => {
    if (!file) {
      return
    }
    setComments(
      file,
      commentsFor(file).filter(item => item.id !== id)
    )
  }

  const save = async () => {
    if (!abs) {
      return
    }
    setSaving(true)
    try {
      await writeDesktopFileText(abs, draft)
      setText(draft)
      setEditing(false)
    } catch {
      host.notify({ kind: 'error', message: t('paneSaveError') })
    } finally {
      setSaving(false)
    }
  }

  const runAction = async (action: 'build' | 'continue') => {
    const ctx = $pluginCtx.get()
    const stored = durableSessionId()
    const runtime = runtimeSessionId()
    if (!ctx || !file) {
      return
    }
    if (!stored || !runtime) {
      host.notify({ kind: 'error', message: t('paneNeedSession') })
      return
    }
    try {
      await ctx.rest('/action', {
        method: 'POST',
        body: {
          action,
          comments,
          plan_file: file,
          session_id: stored
        }
      })
      clearComments(file)
      setQuote('')
      setCommentBody('')
      if (action === 'build') {
        applyMode('agent', stored)
      } else {
        applyMode('plan', stored)
        armPlanAutoOpen()
      }
      await host.request('prompt.submit', {
        session_id: runtime,
        text: action === 'build' ? t('submitBuild') : t('submitContinue')
      })
    } catch (error) {
      host.notify({
        kind: 'error',
        message: error instanceof Error ? error.message : String(error)
      })
    }
  }

  const errorMessage = useMemo(() => {
    if (!file) {
      return t('paneLoadError')
    }
    if (!cwd.trim()) {
      return t('paneNoCwd')
    }
    return t('paneLoadError')
  }, [cwd, file, t])

  return (
    <div className="flex h-full min-h-0 flex-col" data-ultra-plan="pane">
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-(--border) px-2 py-1.5">
        <Button type="button" variant="ghost" className="h-6 px-2 text-[0.6875rem]" onClick={() => setEditing(false)}>
          {t('panePreview')}
        </Button>
        <Button type="button" variant="ghost" className="h-6 px-2 text-[0.6875rem]" onClick={() => setEditing(true)}>
          {t('paneEdit')}
        </Button>
        {editing ? (
          <Button type="button" className="h-6 px-2 text-[0.6875rem]" disabled={saving || load !== 'ready'} onClick={() => void save()}>
            {saving ? t('paneSaving') : t('paneSave')}
          </Button>
        ) : null}
        <span className="ml-auto" />
        <Button type="button" variant="ghost" className="h-6 px-2 text-[0.6875rem]" onClick={() => void runAction('continue')}>
          {t('paneContinue')}
        </Button>
        <Button type="button" className="h-6 px-2 text-[0.6875rem]" onClick={() => void runAction('build')}>
          {t('paneBuild')}
        </Button>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 min-w-0 flex-1 overflow-auto">
          {load === 'loading' ? (
            <div className="p-3 text-sm text-(--muted-foreground)">…</div>
          ) : load === 'error' ? (
            <div className="p-3 text-sm text-(--muted-foreground)">{errorMessage}</div>
          ) : editing ? (
            <div className="h-full min-h-[12rem]">
              <CodeEditor
                key={loadKey}
                filePath={abs || file || 'plan.md'}
                initialValue={draft}
                framed
                onChange={setDraft}
                onSave={() => void save()}
                onCancel={() => {
                  setDraft(text)
                  setEditing(false)
                }}
              />
            </div>
          ) : (
            <div
              ref={previewRef}
              className="h-full min-h-0 cursor-text select-text overflow-auto text-foreground [&_.preview-markdown]:mx-0 [&_.preview-markdown]:max-w-none [&_.preview-markdown]:px-5 [&_.preview-markdown]:py-4 [&_.preview-markdown]:text-[0.9375rem] [&_.preview-markdown]:leading-7 [&_.preview-markdown]:text-foreground [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_h4]:text-foreground [&_p]:text-foreground [&_li]:text-foreground"
              data-selectable-text="true"
              data-ultra-plan="preview"
            >
              <MarkdownPreview text={text} />
            </div>
          )}
        </div>
        <aside className="flex w-64 shrink-0 flex-col gap-2 border-l border-(--border) p-2">
          <div className="text-[0.6875rem] font-medium">{t('paneComments')}</div>
          <div className="rounded border border-(--border) bg-(--card)/75 p-2 shadow-sm" data-ultra-plan="comment-draft">
            {quote ? (
              <blockquote className="mb-1 line-clamp-4 text-[0.6875rem] text-(--muted-foreground)">
                {quote}
              </blockquote>
            ) : (
              <div className="mb-1 text-[0.6875rem] text-(--muted-foreground)">{t('paneQuotePlaceholder')}</div>
            )}
            <Textarea
              value={commentBody}
              onChange={event => setCommentBody(event.target.value)}
              placeholder={t('paneCommentPlaceholder')}
              className="min-h-16 text-[0.75rem]"
            />
            <Button type="button" className="mt-1 h-6 px-2 text-[0.6875rem]" onClick={addComment}>
              {t('paneAddComment')}
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {comments.length === 0 ? (
              <div className="text-[0.6875rem] text-(--muted-foreground)">{t('paneEmptyComments')}</div>
            ) : (
              comments.map(item => (
                <div
                  key={item.id}
                  className={cn('mb-2 rounded border border-(--border) bg-(--card)/75 p-2 shadow-sm')}
                >
                  {item.quote ? (
                    <blockquote className="mb-1 line-clamp-4 text-[0.6875rem] text-(--muted-foreground)">
                      {item.quote}
                    </blockquote>
                  ) : null}
                  {item.body ? <div className="text-[0.75rem]">{item.body}</div> : null}
                  <button
                    type="button"
                    className="mt-1 text-[0.625rem] text-(--muted-foreground) underline"
                    onClick={() => removeComment(item.id)}
                  >
                    {t('paneDeleteComment')}
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

export function PlanDirective({
  attrs,
  streaming
}: {
  attrs: Readonly<Record<string, string>>
  streaming: boolean
}) {
  const t = usePluginI18n(ID)
  const file = normalizePlanRel(attrs.file || '')

  useEffect(() => {
    if (streaming || !file) {
      return
    }
    if (!consumePlanAutoOpen()) {
      return
    }
    openPlanView(file)
  }, [file, streaming])

  if (!file) {
    return null
  }

  return (
    <button
      type="button"
      className="mt-2 inline-flex items-center gap-1 rounded border border-(--border) px-2 py-1 text-[0.75rem]"
      onClick={() => openPlanView(file)}
    >
      <Codicon name="checklist" size="0.75rem" />
      {t('directiveOpen', file.split('/').pop() || file)}
    </button>
  )
}

export function openPlanView(file: string) {
  const rel = normalizePlanRel(file)
  if (!rel) {
    return
  }
  $planFile.set(rel)
  hideRightSidebarForPlan()
  if (isPlanViewOpen()) {
    return
  }
  const dispose = host.openWorkspace(`${ID}:view`, {
    dock: { pane: 'workspace', pos: 'right' },
    minWidth: '32rem',
    onClose: onPlanViewClosed,
    render: () => <PlanPane />,
    title: planTitle(rel)
  })
  bindPlanDispose(dispose)
}
