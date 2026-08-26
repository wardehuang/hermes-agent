/**
 * create-image — Desktop plugin
 * Fields come from image_gen provider capabilities (config.yaml models.*.params).
 * Only configured params are shown / sent. n omitted from yaml → hidden.
 * prompt_constraints is server-side (config); panel only reflects status.
 */
import {
  atom,
  Button,
  cn,
  Codicon,
  COMPOSER_AREAS,
  host,
  PALETTE_AREA,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  usePluginI18n,
  useValue,
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'create-image'
const $panel = atom({ open: false, seed: '' })
const $busy = atom(false)
/** Live form values keyed by API param name (size, background, …). */
const $form = atom({})

/** Preferred field order in the bar. */
const FIELD_ORDER = [
  'size',
  'background',
  'output_format',
  'moderation',
  'quality',
  'n',
]

/** @type {(path: string, opts?: object) => Promise<any>} */
let restClient = async () => {
  throw new Error('create-image rest not ready')
}

/** @type {(key: string, ...args: unknown[]) => string} */
let tNow = key => key

const LOCALES = {
  en: {
    title: 'Create Image',
    labels: {
      size: 'Resize',
      resize: 'Resize',
      background: 'Background',
      output_format: 'Format',
      moderation: 'Safety filter',
      quality: 'Quality',
      n: 'Count',
    },
    ratios: {
      square: 'Square',
      portrait: 'Portrait',
      story: 'Story',
      landscape: 'Landscape',
      widescreen: 'Widescreen',
    },
    options: {
      auto: 'Auto',
      opaque: 'Opaque',
      transparent: 'Transparent',
      low: 'Low',
      medium: 'Medium',
      high: 'High',
    },
    status: {
      notReady: 'not ready',
      loading: 'loading…',
      injectOn: 'prompt inject on',
      injectOff: 'API only',
    },
    actions: {
      refresh: 'Refresh',
      close: 'Close',
    },
    errors: {
      emptyPrompt: 'Type a prompt in the chat box, then press Send',
      noParams: 'No image params configured in config.yaml',
    },
    notify: { errorTitle: 'Create Image' },
  },
  zh: {
    title: '创建图片',
    labels: {
      size: '尺寸',
      resize: '尺寸',
      background: '背景',
      output_format: '格式',
      moderation: '安全过滤',
      quality: '质量',
      n: '张数',
    },
    ratios: {
      square: '方形',
      portrait: '竖版',
      story: '故事',
      landscape: '横版',
      widescreen: '宽屏',
    },
    options: {
      auto: '自动',
      opaque: '不透明',
      transparent: '透明',
      low: '宽松',
      medium: '中',
      high: '高',
    },
    status: {
      notReady: '未就绪',
      loading: '加载中…',
      injectOn: '注入提示词',
      injectOff: '仅 API 参数',
    },
    actions: {
      refresh: '刷新',
      close: '关闭',
    },
    errors: {
      emptyPrompt: '在下方聊天输入框写提示词，再点发送',
      noParams: 'config.yaml 未配置可用图片参数',
    },
    notify: { errorTitle: '创建图片' },
  },
  'zh-hant': {
    title: '建立圖片',
    labels: {
      size: '尺寸',
      resize: '尺寸',
      background: '背景',
      output_format: '格式',
      moderation: '安全過濾',
      quality: '品質',
      n: '張數',
    },
    ratios: {
      square: '方形',
      portrait: '直式',
      story: '限時動態',
      landscape: '橫式',
      widescreen: '寬螢幕',
    },
    options: {
      auto: '自動',
      opaque: '不透明',
      transparent: '透明',
      low: '寬鬆',
      medium: '中',
      high: '高',
    },
    status: {
      notReady: '未就緒',
      loading: '載入中…',
      injectOn: '注入提示詞',
      injectOff: '僅 API 參數',
    },
    actions: {
      refresh: '重新整理',
      close: '關閉',
    },
    errors: {
      emptyPrompt: '在下方聊天輸入框寫提示詞，再點傳送',
      noParams: 'config.yaml 未設定可用圖片參數',
    },
    notify: { errorTitle: '建立圖片' },
  },
  ja: {
    title: '画像を作成',
    labels: {
      size: 'サイズ',
      resize: 'サイズ',
      background: '背景',
      output_format: '形式',
      moderation: 'セーフティ',
      quality: '品質',
      n: '枚数',
    },
    ratios: {
      square: 'スクエア',
      portrait: 'ポートレート',
      story: 'ストーリー',
      landscape: 'ランドスケープ',
      widescreen: 'ワイド',
    },
    options: {
      auto: '自動',
      opaque: '不透明',
      transparent: '透明',
      low: '低',
      medium: '中',
      high: '高',
    },
    status: {
      notReady: '未準備',
      loading: '読み込み中…',
      injectOn: 'プロンプト注入',
      injectOff: 'APIのみ',
    },
    actions: {
      refresh: '更新',
      close: '閉じる',
    },
    errors: {
      emptyPrompt: '下の入力欄にプロンプトを書いて送信',
      noParams: 'config.yaml に画像パラメータがありません',
    },
    notify: { errorTitle: '画像を作成' },
  },
  ar: {
    title: 'إنشاء صورة',
    labels: {
      size: 'الحجم',
      resize: 'الحجم',
      background: 'الخلفية',
      output_format: 'التنسيق',
      moderation: 'مرشح الأمان',
      quality: 'الجودة',
      n: 'العدد',
    },
    ratios: {
      square: 'مربع',
      portrait: 'عمودي',
      story: 'قصة',
      landscape: 'أفقي',
      widescreen: 'عريض',
    },
    options: {
      auto: 'تلقائي',
      opaque: 'معتم',
      transparent: 'شفاف',
      low: 'منخفض',
      medium: 'متوسط',
      high: 'عالٍ',
    },
    status: {
      notReady: 'غير جاهز',
      loading: 'جارٍ التحميل…',
      injectOn: 'حقن الموجه',
      injectOff: 'API فقط',
    },
    actions: {
      refresh: 'تحديث',
      close: 'إغلاق',
    },
    errors: {
      emptyPrompt: 'اكتب المطالبة في مربع الدردشة ثم أرسل',
      noParams: 'لا توجد معاملات صورة في config.yaml',
    },
    notify: { errorTitle: 'إنشاء صورة' },
  },
}

function openPanel(seed = '') {
  $panel.set({ open: true, seed: typeof seed === 'string' ? seed : '' })
}

function closePanel() {
  $panel.set({ open: false, seed: '' })
}

function clearComposerText() {
  try {
    const nodes = document.querySelectorAll('[data-slot="composer-rich-input"]')
    for (const el of nodes) {
      if (!(el instanceof HTMLElement)) continue
      const style = window.getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden') continue
      el.focus()
      if (el.isContentEditable) {
        el.innerHTML = ''
        el.dispatchEvent(new InputEvent('input', { bubbles: true }))
      }
    }
  } catch {
    /* ignore */
  }
}

function patchForm(partial) {
  $form.set({ ...$form.get(), ...partial })
}

function measureLabelCh(label) {
  let n = 0
  for (const ch of String(label ?? '')) {
    n += /[\u1100-\u115F\u2E80-\uA4CF\uAC00-\uD7A3\uF900-\uFAFF\uFE10-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/.test(
      ch,
    )
      ? 1.7
      : 1
  }
  return n
}

function Field({ label, children }) {
  return jsxs('div', {
    className: 'flex w-fit flex-col gap-1',
    children: [
      jsx('span', {
        className: 'pl-1.5 text-[11px] font-semibold text-(--ui-text-secondary)',
        children: label,
      }),
      children,
    ],
  })
}

function EnumSelect({ value, options, onChange, disabled }) {
  const items = (options || [])
    .map(opt => {
      if (opt && typeof opt === 'object' && !Array.isArray(opt)) {
        const valueRaw = opt.value != null ? opt.value : opt.size != null ? opt.size : ''
        const labelRaw =
          opt.label != null
            ? opt.label
            : opt.ratio != null
              ? opt.ratio
              : valueRaw
        const value = typeof valueRaw === 'string' || typeof valueRaw === 'number'
          ? String(valueRaw)
          : ''
        const label = typeof labelRaw === 'string' || typeof labelRaw === 'number'
          ? String(labelRaw)
          : value
        return { value, label: label || value }
      }
      if (typeof opt === 'string' || typeof opt === 'number' || typeof opt === 'boolean') {
        return { value: String(opt), label: String(opt) }
      }
      return { value: '', label: '' }
    })
    .filter(o => o.value)
  if (!items.length) return null
  const v = String(value ?? '')
  const safe = items.some(o => o.value === v) ? v : items[0].value
  let maxCh = 2
  for (const it of items) maxCh = Math.max(maxCh, measureLabelCh(it.label))
  const triggerStyle = {
    width: `calc(${maxCh.toFixed(1)}ch + 2.25rem)`,
    minWidth: `calc(${maxCh.toFixed(1)}ch + 2.25rem)`,
  }
  return jsxs(Select, {
    value: safe,
    onValueChange: onChange,
    disabled: Boolean(disabled),
    children: [
      jsx(SelectTrigger, {
        className: 'h-8 shrink-0 justify-between text-xs tabular-nums',
        style: triggerStyle,
        children: jsx(SelectValue, {
          className: 'truncate',
          placeholder: items.find(i => i.value === safe)?.label || safe,
        }),
      }),
      jsx(SelectContent, {
        style: { minWidth: triggerStyle.minWidth },
        children: items.map(opt =>
          jsx(
            SelectItem,
            {
              value: opt.value,
              textValue: opt.label,
              children: opt.label,
            },
            opt.value,
          ),
        ),
      }),
    ],
  })
}

function IconBtn({ title, name, onClick, disabled, spinning }) {
  return jsx(Button, {
    type: 'button',
    size: 'sm',
    variant: 'ghost',
    title,
    'aria-label': title,
    disabled: Boolean(disabled),
    className: 'h-7 w-7 shrink-0 p-0',
    onClick,
    children: jsx(Codicon, {
      name,
      className: cn('text-[0.9rem]', spinning && 'animate-spin'),
    }),
  })
}

function optionLabel(raw, t) {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    const v = raw.value != null ? raw.value : raw.label != null ? raw.label : ''
    return optionLabel(v, t)
  }
  const v = String(raw ?? '')
  const lower = v.toLowerCase()
  if (lower === 'png' || lower === 'jpeg' || lower === 'jpg' || lower === 'webp') {
    return lower === 'jpg' ? 'JPEG' : lower.toUpperCase()
  }
  const known = t(`options.${lower}`)
  if (known && known !== `options.${lower}`) return known
  return v
}

function fieldLabel(name, t) {
  const k = t(`labels.${name}`)
  if (k && k !== `labels.${name}`) return k
  if (name === 'size') {
    const r = t('labels.resize')
    if (r && r !== 'labels.resize') return r
  }
  return name
}

function coerceOptionValue(raw) {
  if (raw == null) return ''
  if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') {
    return String(raw)
  }
  if (typeof raw === 'object') {
    if (raw.value != null) return coerceOptionValue(raw.value)
    if (raw.size != null) return coerceOptionValue(raw.size)
  }
  return ''
}

/** Visible UI fields from capabilities.params (skip prompt / hidden). */
function buildUiFields(params, t) {
  if (!params || typeof params !== 'object') return []
  const keys = Object.keys(params).filter(k => k && k !== 'prompt')
  keys.sort((a, b) => {
    const ia = FIELD_ORDER.indexOf(a)
    const ib = FIELD_ORDER.indexOf(b)
    if (ia === -1 && ib === -1) return a.localeCompare(b)
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
  /** @type {Array<{name:string, label:string, options:Array<{value:string,label:string}>, defaultValue:string}>} */
  const fields = []
  for (const name of keys) {
    const spec = params[name]
    if (!spec || typeof spec !== 'object') continue
    if (String(spec.ui || '') === 'hidden') continue

    /** @type {Array<{value:string,label:string}>} */
    let options = []
    if (name === 'size' || spec.type === 'size') {
      const presets = Array.isArray(spec.presets) ? spec.presets : []
      const meta = spec.preset_meta && typeof spec.preset_meta === 'object' ? spec.preset_meta : {}
      for (const p of presets) {
        /** @type {Record<string, unknown>} */
        let m = {}
        let value = ''
        if (p && typeof p === 'object' && !Array.isArray(p)) {
          value = coerceOptionValue(p.value != null ? p.value : p.size)
          m = p
        } else {
          value = coerceOptionValue(p)
          m = meta[value] && typeof meta[value] === 'object' ? meta[value] : {}
        }
        if (!value) continue
        const key = m.key != null ? String(m.key) : ''
        const ratio = m.ratio != null ? String(m.ratio) : ''
        let label = value
        if (key) {
          const nameL = t(`ratios.${key}`)
          const base = nameL && nameL !== `ratios.${key}` ? nameL : key
          label = ratio ? `${base}  ${ratio}` : base
        } else if (ratio) {
          label = `${ratio}  ${value}`
        }
        options.push({ value, label: String(label) })
      }
      if (!options.length && spec.default != null) {
        const d = coerceOptionValue(spec.default)
        if (d) options = [{ value: d, label: d }]
      }
    } else {
      const enumVals = Array.isArray(spec.enum) ? spec.enum : []
      options = enumVals
        .map(v => {
          const value = coerceOptionValue(v)
          if (!value) return null
          return { value, label: optionLabel(v, t) }
        })
        .filter(Boolean)
    }
    if (!options.length) continue
    const defaultValue = coerceOptionValue(
      spec.default != null && spec.default !== '' ? spec.default : options[0].value,
    ) || options[0].value
    fields.push({
      name,
      label: fieldLabel(name, t),
      options,
      defaultValue,
    })
  }
  return fields
}

function defaultsFromFields(fields) {
  /** @type {Record<string, string>} */
  const out = {}
  for (const f of fields) out[f.name] = f.defaultValue
  return out
}

async function pushOverrides(active, fields) {
  try {
    if (!active) {
      await restClient('/overrides', { method: 'DELETE' })
      return
    }
    const form = $form.get()
    /** @type {Record<string, unknown>} */
    const body = { active: true }
    const list = Array.isArray(fields) ? fields : []
    if (list.length) {
      for (const f of list) {
        const v = form[f.name]
        if (v == null || v === '') continue
        if (f.name === 'n') {
          const n = Number(v)
          if (Number.isFinite(n) && n >= 1) body.n = n
          continue
        }
        body[f.name] = v
      }
    } else {
      // fallback: dump form keys
      for (const [k, v] of Object.entries(form || {})) {
        if (v == null || v === '') continue
        body[k] = v
      }
    }
    // Never invent n when not configured
    if (!list.some(f => f.name === 'n') && body.n != null) delete body.n
    await restClient('/overrides', { method: 'PUT', body })
  } catch {
    /* optional */
  }
}

function collectImageSources(draft) {
  const attachments = Array.isArray(draft?.attachments) ? draft.attachments : []
  /** @type {string[]} */
  const paths = []
  for (const att of attachments) {
    if (!att || typeof att !== 'object') continue
    const kind = String(att.kind || '')
    const path = typeof att.path === 'string' ? att.path.trim() : ''
    if (!path) continue
    if (kind === 'image' || /\.(png|jpe?g|webp|gif|bmp|tif?f)$/i.test(path)) {
      paths.push(path)
    }
  }
  return [...new Set(paths)]
}

/** Last loaded fields for middleware (module scope). */
let lastFields = []

function buildImageGenerateArgs(rawText, draft) {
  let text = String(rawText || '').trim()
  text = text.replace(/^\/create-image(?:\s+|$)/i, '').trim()
  const seed = $panel.get().seed
  if (!text && seed) text = String(seed).trim()
  if (!text) return null

  const form = $form.get()
  /** @type {Record<string, unknown>} */
  const args = { prompt: text }
  for (const f of lastFields) {
    const v = form[f.name]
    if (v == null || v === '') continue
    if (f.name === 'n') {
      const n = Number(v)
      if (Number.isFinite(n) && n >= 1) args.n = n
      continue
    }
    args[f.name] = v
  }
  const sources = collectImageSources(draft)
  if (sources.length === 1) {
    args.image_url = sources[0]
  } else if (sources.length > 1) {
    args.image_url = sources[0]
    args.reference_image_urls = sources.slice(1)
  }
  return args
}

function buildForceToolPrompt(args) {
  return [
    'Call the image_generate tool exactly once with these JSON arguments.',
    'Do not call any other tool. Do not ask questions. Do not regenerate.',
    'After the tool result, reply with one short confirmation line only.',
    '```json',
    JSON.stringify(args),
    '```',
  ].join('\n')
}

function CreateImageBar() {
  const t = usePluginI18n(ID)
  const panel = useValue($panel)
  const form = useValue($form)
  const open = Boolean(panel?.open)
  const busy = useValue($busy)

  const [capsPayload, setCapsPayload] = useState(null)
  const [loadingCaps, setLoadingCaps] = useState(false)
  const [error, setError] = useState('')
  const [fields, setFields] = useState([])

  const loadCaps = useCallback(async () => {
    setLoadingCaps(true)
    setError('')
    try {
      const data = await restClient('/capabilities', { method: 'GET' })
      setCapsPayload(data)
      const params = data?.capabilities?.params || {}
      const nextFields = buildUiFields(params, t)
      setFields(nextFields)
      lastFields = nextFields
      // seed form defaults without wiping user picks for still-valid keys
      const defaults = defaultsFromFields(nextFields)
      const prev = $form.get() || {}
      /** @type {Record<string, string>} */
      const merged = {}
      for (const f of nextFields) {
        const cur = prev[f.name]
        const ok = f.options.some(o => o.value === String(cur))
        merged[f.name] = ok ? String(cur) : f.defaultValue
      }
      $form.set(Object.keys(merged).length ? merged : defaults)
    } catch (err) {
      setCapsPayload(null)
      setFields([])
      lastFields = []
      setError(err?.message || String(err))
    } finally {
      setLoadingCaps(false)
    }
  }, [t])

  useEffect(() => {
    if (!open) {
      void pushOverrides(false, [])
      return
    }
    void loadCaps()
  }, [open, loadCaps])

  useEffect(() => {
    if (!open || !fields.length) return
    void pushOverrides(true, fields)
  }, [open, fields, form])

  if (!open) return null

  const provider = capsPayload?.provider || '—'
  const model = capsPayload?.model || '—'
  const ready = Boolean(
    capsPayload?.available ?? capsPayload?.ready ?? (capsPayload?.provider && capsPayload?.model),
  )
  const inject = Boolean(
    capsPayload?.prompt_constraints ?? capsPayload?.capabilities?.prompt_constraints,
  )
  const statusBits = [
    !ready && capsPayload ? t('status.notReady') : null,
    loadingCaps ? t('status.loading') : null,
    capsPayload ? (inject ? t('status.injectOn') : t('status.injectOff')) : null,
  ].filter(Boolean)
  const meta = `${provider} · ${model}${statusBits.length ? ` · ${statusBits.join(' · ')}` : ''}`

  return jsxs('div', {
    className: cn(
      'mb-2 w-full rounded-xl border border-(--ui-border) bg-(--ui-bg-secondary)/80 px-3 py-2',
      'text-xs text-(--ui-text-secondary) shadow-sm backdrop-blur',
    ),
    'data-create-image-bar': '1',
    children: [
      jsxs('div', {
        className: 'flex flex-wrap items-center gap-1.5',
        children: [
          jsx('span', {
            className:
              'rounded-md bg-(--ui-bg-tertiary) px-1.5 py-0.5 text-[11px] font-medium text-(--ui-text-primary)',
            children: t('title'),
          }),
          jsx('span', {
            className: 'text-[11px] text-(--ui-text-tertiary)',
            children: meta,
          }),
          jsx('div', { className: 'flex-1' }),
          jsx(IconBtn, {
            title: t('actions.refresh'),
            name: 'refresh',
            spinning: loadingCaps,
            disabled: loadingCaps || busy,
            onClick: () => void loadCaps(),
          }),
          jsx(IconBtn, {
            title: t('actions.close'),
            name: 'close',
            disabled: busy,
            onClick: () => {
              void pushOverrides(false, [])
              closePanel()
            },
          }),
        ],
      }),

      fields.length
        ? jsx('div', {
            className: 'mt-2 flex flex-wrap gap-2',
            children: fields.map(f =>
              jsx(
                Field,
                {
                  label: f.label,
                  children: jsx(EnumSelect, {
                    value: form?.[f.name] ?? f.defaultValue,
                    options: f.options,
                    disabled: busy,
                    onChange: v => patchForm({ [f.name]: v }),
                  }),
                },
                f.name,
              ),
            ),
          })
        : jsx('div', {
            className: 'mt-2 text-[11px] text-(--ui-text-tertiary)',
            children: loadingCaps ? t('status.loading') : t('errors.noParams'),
          }),

      error
        ? jsx('div', {
            className: 'mt-1 break-all text-[11px] text-red-500',
            children: error,
          })
        : null,
    ],
  })
}

export default {
  id: ID,
  name: 'Create Image',
  description:
    'Image bar driven by config.yaml model params. prompt_constraints toggles EN inject.',
  defaultEnabled: true,

  register(ctx) {
    restClient = (path, opts) => ctx.rest(path, opts)
    ctx.i18n.register(LOCALES)
    tNow = (key, ...args) => ctx.i18n.t(key, ...args)

    const onHostOpen = ev => {
      const seed = ev?.detail?.seed || ''
      openPanel(typeof seed === 'string' ? seed : '')
    }
    window.addEventListener('hermes:create-image', onHostOpen)
    ctx.onDispose(() => {
      window.removeEventListener('hermes:create-image', onHostOpen)
      void pushOverrides(false, [])
    })

    ctx.register({
      id: 'bar',
      area: COMPOSER_AREAS.top,
      order: 10,
      render: () => jsx(CreateImageBar, {}),
    })

    ctx.register({
      id: 'palette-open',
      area: PALETTE_AREA,
      data: {
        id: `${ID}.open`,
        label: 'Create Image',
        keywords: ['image', 'generate', 'draw', 'create-image', 'gpt-image', '/create-image'],
        run: () => openPanel(''),
      },
    })

    ctx.register({
      id: 'middleware',
      area: COMPOSER_AREAS.middleware,
      order: 5,
      data: {
        handler: async draft => {
          const text = String(draft?.text || '').trim()
          const m = text.match(/^\/create-image(?:\s+([\s\S]+))?$/i)
          if (m) {
            openPanel(m[1] ? m[1].trim() : '')
            window.setTimeout(clearComposerText, 0)
            window.setTimeout(clearComposerText, 40)
            return null
          }

          if (!$panel.get().open) return draft

          const args = buildImageGenerateArgs(text, draft)
          if (!args) {
            try {
              host.notify({
                kind: 'error',
                title: tNow('notify.errorTitle'),
                message: tNow('errors.emptyPrompt'),
              })
            } catch {
              /* ignore */
            }
            return null
          }

          void pushOverrides(true, lastFields)
          return {
            ...draft,
            text: buildForceToolPrompt(args),
            displayText: String(args.prompt || text),
          }
        },
      },
    })

    ctx.register({
      id: 'attach-open',
      area: COMPOSER_AREAS.attachments,
      data: {
        label: 'Create Image…',
        icon: 'symbol-color',
        run: () => openPanel(''),
      },
    })
  },
}
