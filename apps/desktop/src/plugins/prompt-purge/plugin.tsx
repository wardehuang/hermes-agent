/**
 * Prompt Purge — drop harness prompt sections and inject composable prompt
 * templates into SOUL.md.
 *
 * Profile is a per-request `target` (see the backend note), never a global
 * request-scope switch. Templates are edited in VS Code, not in an inline box.
 */

import './prompt-purge.css'

import {
  type HermesPlugin,
  type RouteContribution,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  type SidebarNavContribution
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useMemo, useState } from 'react'

// ── types ──────────────────────────────────────────────────────────────────
interface Section {
  id: string
  head: string
  chars: number
  tier: string
  source: string
  count: number
  text: string
  droppable: boolean
}

interface TemplateInfo {
  name: string
  chars: number
}

interface PurgeState {
  profile: string
  drop: string[]
  templates: string[]
}

type Rest = <T>(path: string, opts?: { method?: string; body?: unknown }) => Promise<T>

let rest: Rest | null = null
let targetProfile: string | null = null

/**
 * 每个请求带 `target=<profile>`。刻意不叫 `profile`：dashboard auth 用
 * `?profile=` / `body.profile` 做连接级鉴权，撞上会 403。`target` 只影响后端
 * 读写哪个 profile 的文件，不动全局请求 scope。
 */
function api<T>(path: string, opts?: { method?: string; body?: unknown }, noTarget = false): Promise<T> {
  if (!rest) {return Promise.reject(new Error('plugin not bound'))}
  const want = noTarget ? null : targetProfile

  if (!want) {return rest<T>(path, opts)}
  const method = (opts?.method ?? 'GET').toUpperCase()

  if (method === 'GET') {
    const sep = path.includes('?') ? '&' : '?'

    return rest<T>(`${path}${sep}target=${encodeURIComponent(want)}`, opts)
  }

  const body = { ...((opts?.body as Record<string, unknown> | undefined) ?? {}), target: want }

  return rest<T>(path, { ...opts, body })
}

// ── page ───────────────────────────────────────────────────────────────────
function PurgePage() {
  const [current, setCurrent] = useState('')
  const [profiles, setProfiles] = useState<string[]>([])
  const [target, setTarget] = useState<string | null>(null)
  const [tab, setTab] = useState<'drop' | 'inject' | 'preview'>('drop')

  const [sections, setSections] = useState<Section[]>([])
  const [warming, setWarming] = useState(false)
  const [drop, setDrop] = useState<string[]>([])
  const [detail, setDetail] = useState<Section | null>(null)

  const [templates, setTemplates] = useState<TemplateInfo[]>([])
  const [picked, setPicked] = useState<string[]>([])

  const [preview, setPreview] = useState<{ text: string; chars: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const flash = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2600)
  }, [])

  const fail = useCallback((exc: unknown) => {
    setError(exc instanceof Error ? exc.message : String(exc))
  }, [])

  const loadTemplates = useCallback(async () => {
    const tpl = await api<{ templates: TemplateInfo[] }>('/templates', undefined, true)
    setTemplates(tpl.templates)
  }, [])

  const load = useCallback(async () => {
    setError(null)
    setPreview(null)

    try {
      const p = await api<{ profiles: string[]; current: string }>('/profiles', undefined, true)
      setProfiles(p.profiles)
      setCurrent(p.current)

      if (!targetProfile) {
        targetProfile = p.current
        setTarget(p.current)
      }

      const st = await api<PurgeState>('/state')
      setDrop(st.drop)
      setPicked(st.templates)
      await loadTemplates()

      setWarming(true)

      try {
        const sec = await api<{ sections: Section[]; warmed: boolean }>('/sections')
        setSections(sec.sections)
      } finally {
        setWarming(false)
      }
    } catch (exc) {
      fail(exc)
    }
  }, [fail, loadTemplates])

  useEffect(() => {
    void load()
  }, [load])

  const switchProfile = (next: string) => {
    if (!next || next === target) {return}
    targetProfile = next
    setTarget(next)
    void load()
  }

  // 只列「稳定」层里属于 harness 的段；后端已用 droppable 标出可安全删除的。
  const droppable = useMemo(() => sections.filter(s => s.droppable), [sections])

  const toggleDrop = (head: string) =>
    setDrop(prev => (prev.includes(head) ? prev.filter(x => x !== head) : [...prev, head]))

  const movePicked = (name: string, dir: -1 | 1) =>
    setPicked(prev => {
      const i = prev.indexOf(name)

      if (i < 0) {return prev}
      const j = i + dir

      if (j < 0 || j >= prev.length) {return prev}

      const next = [...prev]

      ;[next[i], next[j]] = [next[j], next[i]]

      return next
    })

  const saveAll = async () => {
    setBusy(true)
    setError(null)

    try {
      await api('/state', { method: 'POST', body: { drop, templates: picked } })
      flash('已保存（下次新会话生效）')
    } catch (exc) {
      fail(exc)
    } finally {
      setBusy(false)
    }
  }

  const applySoul = async () => {
    setBusy(true)
    setError(null)

    try {
      const r = await api<{ chars: number }>('/apply', {
        method: 'POST',
        body: { templates: picked, drop }
      })

      flash(`已写入 SOUL.md（${r.chars} 字符）`)
    } catch (exc) {
      fail(exc)
    } finally {
      setBusy(false)
    }
  }

  const revertSoul = async () => {
    setBusy(true)
    setError(null)

    try {
      await api('/revert', { method: 'POST', body: {} })
      flash('已从备份还原 SOUL.md')
    } catch (exc) {
      fail(exc)
    } finally {
      setBusy(false)
    }
  }

  const runPreview = async () => {
    setBusy(true)
    setError(null)
    setPreview(null)

    try {
      const r = await api<{ text: string; chars: number }>('/preview', {
        method: 'POST',
        body: { templates: picked, drop }
      })

      setPreview({ text: r.text, chars: r.chars })
    } catch (exc) {
      fail(exc)
    } finally {
      setBusy(false)
    }
  }

  const copyPreview = async () => {
    if (!preview) {return}

    try {
      await navigator.clipboard.writeText(preview.text)
      flash('已复制到剪贴板')
    } catch {
      // 剪贴板需要 secure context；退回到手动选择
      const sel = window.getSelection()
      const node = document.querySelector('.pp-preview')

      if (node && sel) {
        const range = document.createRange()
        range.selectNodeContents(node)
        sel.removeAllRanges()
        sel.addRange(range)
        flash('已全选，按 Ctrl+C 复制')
      }
    }
  }

  const openTemplate = async (name: string) => {
    setError(null)

    try {
      const r = await api<{ opened_with: string }>('/open', { method: 'POST', body: { name } }, true)
      flash(r.opened_with === 'code' ? `已在 VS Code 打开 ${name}` : `已用默认程序打开 ${name}`)
    } catch (exc) {
      fail(exc)
    }
  }

  const createTemplate = async () => {
    const name = window.prompt('新模板名称')

    if (!name) {return}
    setBusy(true)
    setError(null)

    try {
      await api(`/templates/${encodeURIComponent(name)}`, { method: 'PUT', body: { content: '' } }, true)
      await loadTemplates()
      await openTemplate(name)
    } catch (exc) {
      fail(exc)
    } finally {
      setBusy(false)
    }
  }

  const renameTemplate = async (name: string) => {
    const to = window.prompt('重命名为', name)

    if (!to || to === name) {return}
    setBusy(true)

    try {
      await api(`/templates/${encodeURIComponent(name)}/rename`, { method: 'POST', body: { to } }, true)
      await loadTemplates()
      setPicked(prev => prev.map(x => (x === name ? to : x)))
    } catch (exc) {
      fail(exc)
    } finally {
      setBusy(false)
    }
  }

  const deleteTemplate = async (name: string) => {
    if (!window.confirm(`删除模板 ${name}？`)) {return}
    setBusy(true)

    try {
      await api(`/templates/${encodeURIComponent(name)}`, { method: 'DELETE' }, true)
      await loadTemplates()
      setPicked(prev => prev.filter(x => x !== name))
    } catch (exc) {
      fail(exc)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="pp-root">
      <header className="pp-header">
        <div className="pp-title">
          <span className="pp-dot" />
          <h1>Prompt Purge</h1>
          <span className="pp-sub">剥离 harness 段 · 注入提示词模板</span>
        </div>
        <label className="pp-select">
          <span>profile</span>
          <select onChange={e => switchProfile(e.target.value)} value={target ?? current}>
            {profiles.map(p => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
      </header>

      <nav className="pp-tabs">
        {(
          [
            ['drop', '删除', `${drop.length} 项`],
            ['inject', '注入', `${picked.length} 个模板`],
            ['preview', '预览', '']
          ] as const
        ).map(([key, label, hint]) => (
          <button
            className={tab === key ? 'pp-tab pp-tab--active' : 'pp-tab'}
            key={key}
            onClick={() => setTab(key)}
            type="button"
          >
            {label}
            {hint ? <em>{hint}</em> : null}
          </button>
        ))}
      </nav>

      {error ? <div className="pp-error">{error}</div> : null}
      {toast ? <div className="pp-toast">{toast}</div> : null}

      <main className="pp-body">
        {tab === 'drop' ? (
          <section className="pp-pane">
            <div className="pp-pane-head">
              <div>
                <h2>可删除的 harness 段</h2>
                <p>
                  只列「稳定」层里属于 harness 的段——身份、行为指引、coding brief。项目上下文和 skills/memory
                  属于功能内容，不在此列。选项由运行时枚举得出，Hermes 升级后自动跟着变。
                </p>
              </div>
              {warming ? <span className="pp-hint">枚举中…</span> : null}
            </div>

            <div className="pp-list">
              {droppable.length === 0 ? (
                <div className="pp-empty">{warming ? '正在构造一次 prompt 来枚举段…' : '还没有枚举到段落。'}</div>
              ) : (
                droppable.map(s => (
                  <div className={drop.includes(s.head) ? 'pp-row pp-row--on' : 'pp-row'} key={s.id}>
                    <input checked={drop.includes(s.head)} onChange={() => toggleDrop(s.head)} type="checkbox" />
                    <span className="pp-row-main" onClick={() => toggleDrop(s.head)}>
                      <code>{s.head}</code>
                      <span className="pp-meta">
                        <em className="pp-tier pp-tier--stable">稳定</em>
                        <em>{s.chars} 字符</em>
                      </span>
                    </span>
                    <button className="pp-detail-btn" onClick={() => setDetail(s)} type="button">
                      详情
                    </button>
                  </div>
                ))
              )}
            </div>

            <footer className="pp-actions">
              <button className="pp-btn pp-btn--primary" disabled={busy} onClick={saveAll} type="button">
                保存删除项
              </button>
              <button className="pp-btn" disabled={busy} onClick={() => setDrop([])} type="button">
                全部保留
              </button>
            </footer>
          </section>
        ) : null}

        {tab === 'inject' ? (
          <section className="pp-pane">
            <div className="pp-pane-head">
              <div>
                <h2>模板</h2>
                <p>
                  按列表顺序从上往下拼接，整体替换该 profile 的 SOUL.md。点「编辑」用 VS Code 打开模板文件，
                  改完点「刷新」重新读取大小。
                </p>
              </div>
              <div className="pp-head-actions">
                <button className="pp-btn" onClick={createTemplate} type="button">
                  新建
                </button>
                <button className="pp-btn" onClick={() => void loadTemplates()} type="button">
                  刷新
                </button>
              </div>
            </div>

            <div className="pp-list">
              {templates.length === 0 ? (
                <div className="pp-empty">还没有模板。点「新建」会创建文件并用 VS Code 打开。</div>
              ) : (
                templates.map(t => {
                  const idx = picked.indexOf(t.name)
                  const on = idx >= 0

                  return (
                    <div className={on ? 'pp-row pp-row--on' : 'pp-row'} key={t.name}>
                      <input
                        checked={on}
                        onChange={() =>
                          setPicked(prev =>
                            prev.includes(t.name) ? prev.filter(x => x !== t.name) : [...prev, t.name]
                          )
                        }
                        type="checkbox"
                      />
                      <span className="pp-row-main">
                        <code>{t.name}</code>
                        <span className="pp-meta">
                          <em>{t.chars} 字符</em>
                          {on ? <em className="pp-order">#{idx + 1}</em> : null}
                        </span>
                      </span>
                      <span className="pp-row-actions">
                        <button onClick={() => openTemplate(t.name)} type="button">
                          编辑
                        </button>
                        <button onClick={() => renameTemplate(t.name)} type="button">
                          重命名
                        </button>
                        <button onClick={() => deleteTemplate(t.name)} type="button">
                          删除
                        </button>
                      </span>
                    </div>
                  )
                })
              )}
            </div>

            {picked.length > 0 ? (
              <div className="pp-order-bar">
                <span>拼接顺序：</span>
                {picked.map((n, i) => (
                  <span className="pp-order-chip" key={n}>
                    {i + 1}. {n}
                    <button onClick={() => movePicked(n, -1)} type="button">
                      ↑
                    </button>
                    <button onClick={() => movePicked(n, 1)} type="button">
                      ↓
                    </button>
                  </span>
                ))}
              </div>
            ) : null}

            <footer className="pp-actions">
              <button
                className="pp-btn pp-btn--primary"
                disabled={busy || picked.length === 0}
                onClick={applySoul}
                type="button"
              >
                写入 SOUL.md
              </button>
              <button className="pp-btn" disabled={busy} onClick={saveAll} type="button">
                只保存选择
              </button>
              <button className="pp-btn pp-btn--danger" disabled={busy} onClick={revertSoul} type="button">
                还原 SOUL.md
              </button>
            </footer>
          </section>
        ) : null}

        {tab === 'preview' ? (
          <section className="pp-pane">
            <div className="pp-pane-head">
              <div>
                <h2>完整系统提示词</h2>
                <p>
                  用当前勾选的删除项 + 拼接后的模板，构造一个真实 agent 并生成 system
                  prompt。不落盘、不调模型。内容可直接选中复制。
                </p>
              </div>
              <div className="pp-head-actions">
                {preview ? (
                  <button className="pp-btn" onClick={copyPreview} type="button">
                    复制
                  </button>
                ) : null}
                <button className="pp-btn pp-btn--primary" disabled={busy} onClick={runPreview} type="button">
                  {busy ? '生成中…' : '生成预览'}
                </button>
              </div>
            </div>

            {preview ? (
              <>
                <div className="pp-stats">
                  <span>{preview.chars} 字符</span>
                  <span>删除 {drop.length} 段</span>
                  <span>模板 {picked.length} 个</span>
                </div>
                <pre className="pp-preview">{preview.text}</pre>
              </>
            ) : (
              <div className="pp-empty">还没有预览。点「生成预览」（约 3–5 秒）。</div>
            )}
          </section>
        ) : null}
      </main>

      {detail ? (
        <div className="pp-modal" onClick={() => setDetail(null)}>
          <div className="pp-modal-body" onClick={e => e.stopPropagation()}>
            <header className="pp-modal-head">
              <code>{detail.head}</code>
              <span className="pp-meta">
                <em>{detail.chars} 字符</em>
                <em className="pp-tier pp-tier--stable">稳定</em>
              </span>
              <button className="pp-btn" onClick={() => setDetail(null)} type="button">
                关闭
              </button>
            </header>
            <pre className="pp-modal-text">{detail.text}</pre>
          </div>
        </div>
      ) : null}
    </div>
  )
}

// ── plugin ─────────────────────────────────────────────────────────────────
const plugin: HermesPlugin = {
  id: 'prompt-purge',
  name: 'Prompt Purge',
  register(ctx) {
    rest = ctx.rest as Rest
    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/prompt-purge' } satisfies RouteContribution,
        render: () => <PurgePage />
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        order: 60,
        data: {
          codicon: 'filter',
          label: 'Prompt Purge',
          path: '/prompt-purge'
        } satisfies SidebarNavContribution
      }
    ])
  }
}

export default plugin
