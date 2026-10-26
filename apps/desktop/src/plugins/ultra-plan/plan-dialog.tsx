import {
  Button,
  CodeEditor,
  Codicon,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  host,
  MarkdownPreview,
  readDesktopFileText,
  SegmentedControl,
  Textarea,
  usePluginI18n,
  useValue,
  writeDesktopFileText
} from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  $comments,
  $commentsEpoch,
  $planFile,
  $planOpen,
  $pluginCtx,
  applyMode,
  armPlanAutoOpen,
  clearComments,
  closePlanView,
  commentsFor,
  consumePlanAutoOpen,
  durableSessionId,
  openPlanDialog,
  runtimeSessionId,
  setComments
} from './plan-store'
import { ID, newCommentId, normalizePlanRel, type PlanComment, planDisplayTitle, resolvePlanAbs } from './shared'

type LoadState = 'error' | 'loading' | 'ready'
type ViewMode = 'edit' | 'preview'

export function PlanDialogHost() {
  const open = useValue($planOpen)
  const file = useValue($planFile)

  return (
    <Dialog
      onOpenChange={next => {
        if (!next) {
          closePlanView()
        }
      }}
      open={open && Boolean(file)}
    >
      {open && file ? <PlanDialog /> : null}
    </Dialog>
  )
}

function PlanDialog() {
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
  const [view, setView] = useState<ViewMode>('preview')
  const [saving, setSaving] = useState(false)
  const [quote, setQuote] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const previewRef = useRef<HTMLDivElement | null>(null)
  const loadKey = `${abs ?? ''}:${file ?? ''}`
  const dirty = draft !== text

  useEffect(() => {
    let cancelled = false
    setView('preview')
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
      setView('preview')
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
        closePlanView()
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
    if (!cwd.trim()) {
      return t('paneNoCwd')
    }

    return t('paneLoadError')
  }, [cwd, t])

  const ready = load === 'ready'

  return (
    <DialogContent
      bodyClassName="flex h-full min-h-0 flex-1 flex-col gap-0 overflow-hidden p-0"
      className="h-[min(44rem,86vh)] w-[min(76rem,94vw)] max-w-none"
      data-ultra-plan="dialog"
    >
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-4 border-b border-(--stroke-nous) px-5 py-4 pr-12">
        <div className="min-w-0 flex-1">
          <div className="text-[0.6875rem] text-(--ui-text-tertiary)">{t('dialogKicker')}</div>
          <DialogTitle className="mt-1 truncate text-lg">{file ? planDisplayTitle(file) : t('dialogKicker')}</DialogTitle>
          {file ? <DialogDescription className="mt-0.5 truncate">{file}</DialogDescription> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-1">
          <SegmentedControl
            disabled={!ready}
            onChange={next => setView(next)}
            options={[
              { id: 'preview', label: t('panePreview') },
              { id: 'edit', label: t('paneEdit') }
            ]}
            sizing="content"
            value={view}
          />
          {view === 'edit' ? (
            <Button disabled={!ready || saving || !dirty} onClick={() => void save()} size="sm" type="button" variant="secondary">
              {saving ? t('paneSaving') : t('paneSave')}
            </Button>
          ) : null}
          <Button disabled={!ready} onClick={() => void runAction('continue')} size="sm" type="button" variant="secondary">
            {t('paneContinue')}
          </Button>
          <Button disabled={!ready} onClick={() => void runAction('build')} size="sm" type="button">
            {t('paneBuild')}
          </Button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 min-w-0 flex-1">
          {load === 'loading' ? (
            <div className="px-8 py-6 text-sm text-(--ui-text-tertiary)">{t('dialogLoading')}</div>
          ) : load === 'error' ? (
            <div className="px-8 py-6 text-sm text-(--ui-text-secondary)">{errorMessage}</div>
          ) : view === 'edit' ? (
            <div className="h-full min-h-0">
              <CodeEditor
                filePath={abs || file || 'plan.md'}
                initialValue={draft}
                key={loadKey}
                onCancel={() => {
                  setDraft(text)
                  setView('preview')
                }}
                onChange={setDraft}
                onSave={() => void save()}
              />
            </div>
          ) : (
            <div
              className="h-full cursor-text select-text overflow-auto text-foreground [&_.preview-markdown]:mx-0 [&_.preview-markdown]:max-w-[46rem] [&_.preview-markdown]:px-8 [&_.preview-markdown]:py-6 [&_.preview-markdown]:text-[0.9375rem] [&_.preview-markdown]:leading-7 [&_.preview-markdown]:text-foreground [&_h1]:mt-0 [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_li]:text-foreground [&_p]:text-foreground"
              data-selectable-text="true"
              data-ultra-plan="preview"
              ref={previewRef}
            >
              <MarkdownPreview text={text} />
            </div>
          )}
        </div>
        <aside className="flex w-72 shrink-0 flex-col border-l border-(--stroke-nous)">
          <div className="px-4 py-3 text-[0.6875rem] text-(--ui-text-tertiary)">{t('paneComments')}</div>
          <div className="min-h-0 flex-1 overflow-auto px-4">
            {comments.length === 0 ? (
              <p className="text-[0.75rem] leading-5 text-(--ui-text-tertiary)">{t('paneEmptyComments')}</p>
            ) : (
              comments.map(item => (
                <div className="mb-4" key={item.id}>
                  {item.quote ? (
                    <blockquote className="border-l border-(--stroke-nous) pl-2 text-[0.75rem] leading-5 text-(--ui-text-tertiary)">
                      {item.quote}
                    </blockquote>
                  ) : null}
                  {item.body ? <p className="mt-1 text-[0.8125rem] leading-5 text-foreground">{item.body}</p> : null}
                  <Button className="mt-1" onClick={() => removeComment(item.id)} size="inline" type="button" variant="text">
                    {t('paneDeleteComment')}
                  </Button>
                </div>
              ))
            )}
          </div>
          <div className="border-t border-(--stroke-nous) p-3" data-ultra-plan="comment-draft">
            {quote ? (
              <blockquote className="mb-2 line-clamp-4 border-l border-(--stroke-nous) pl-2 text-[0.75rem] leading-5 text-(--ui-text-tertiary)">
                {quote}
              </blockquote>
            ) : (
              <p className="mb-2 text-[0.75rem] leading-5 text-(--ui-text-tertiary)">{t('paneQuotePlaceholder')}</p>
            )}
            <Textarea
              className="min-h-16 text-[0.8125rem]"
              onChange={event => setCommentBody(event.target.value)}
              placeholder={t('paneCommentPlaceholder')}
              value={commentBody}
            />
            <Button className="mt-2" onClick={addComment} size="sm" type="button" variant="secondary">
              {t('paneAddComment')}
            </Button>
          </div>
        </aside>
      </div>
    </DialogContent>
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

    openPlanDialog(file)
  }, [file, streaming])

  if (!file) {
    return null
  }

  return (
    <button
      className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-(--stroke-nous) bg-(--ui-chat-bubble-background) px-2.5 py-1 text-[0.75rem] text-foreground shadow-nous"
      onClick={() => openPlanDialog(file)}
      type="button"
    >
      <Codicon name="checklist" size="0.75rem" />
      {t('directiveOpen', file.split('/').pop() || file)}
    </button>
  )
}
