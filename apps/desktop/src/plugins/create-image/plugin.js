/**
 * create-image — Desktop plugin
 * Fields come from image_gen provider capabilities (config.yaml models.*.params).
 * Only configured params are shown / sent. n omitted from yaml → hidden.
 * Provider+model dropdown from config catalog; params reload on switch.
 * prompt_constraints: panel checkbox (default from config); live inject preview.
 * Panel route/params override image_generate while open.
 * Panel-open send skips the main model: one-shot direct=true in overrides,
 * agent runs image_generate as a synthetic tool call.
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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'create-image'
const $panel = atom({ open: false, seed: '' })
const $busy = atom(false)
/** Live form values keyed by API param name (size, background, …). */
const $form = atom({})

/** Preferred field order in the bar. */
const FIELD_ORDER = [
  'aspect_ratio',
  'size',
  'background',
  'quality',
  'n',
  'output_format',
  'moderation',
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
      aspect_ratio: 'Ratio',
      route: 'Model',
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
    inject: {
      label: 'Inject prompt constraints',
      hint: 'Append English output constraints',
      preview: 'Constraints to inject',
      placeholder: '',
      off: '',
      empty: 'No constraint lines for current params',
      onlyBlock: 'Only the block below is appended',
    },
    actions: {
      refresh: 'Refresh',
      close: 'Close',
      settings: 'Settings',
    },
    settings: {
      title: 'Endpoints',
      name: 'Name',
      baseUrl: 'Base URL',
      key: 'API key',
      keyKeep: 'Leave blank to keep the saved key',
      saveEndpoint: 'Save endpoint',
      fetch: 'Load models',
      editModels: 'Edit models',
      paramKey: 'Key',
      label: 'Label',
      value: 'Value',
      ratioControlsSize: 'Ratio controls size',
      ratioSizeMismatch: 'Enabled ratio and size options must match one to one',
      addOption: 'Add',
      injectHint: '{label} and {value}',
      injectEmpty: 'No injection line',
      editBody: 'Edit request',
      saveModels: 'Save models',
      quality: 'Quality',
      transparent: 'Transparent',
      count: 'Count',
      customRatio: 'Custom ratios',
      customQuality: 'Custom quality',
      customCount: 'Custom count',
      empty: 'No endpoints yet',
      delete: 'Delete',
    },
    errors: {
      emptyPrompt: 'Type a prompt in the chat box, then press Send',
      noParams: 'No endpoint yet. Open settings.',
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
      aspect_ratio: '比例',
      route: '模型',
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
    inject: {
      label: '注入提示词约束',
      hint: '追加英文输出约束到提示词',
      preview: '将注入的约束',
      placeholder: '',
      off: '',
      empty: '当前参数无需追加约束行',
      onlyBlock: '仅追加下方约束块，不改聊天原文',
    },
    actions: {
      refresh: '刷新',
      close: '关闭',
      settings: '设置',
    },
    settings: {
      title: '端点',
      name: '名称',
      baseUrl: 'Base URL',
      key: 'API Key',
      keyKeep: '留空则保留已保存的密钥',
      saveEndpoint: '保存端点',
      fetch: '读取模型',
      editModels: '修改模型',
      paramKey: 'Key',
      label: 'Label',
      value: 'Value',
      ratioControlsSize: '比例控制尺寸',
      ratioSizeMismatch: '已勾选的比例和尺寸必须数量一致、一一对应',
      addOption: '添加',
      injectHint: '可用 {label} 和 {value}',
      injectEmpty: '这段不注入',
      editBody: '图生图',
      saveModels: '保存模型',
      quality: '质量',
      transparent: '透明',
      count: '张数',
      customRatio: '自定义比例',
      customQuality: '自定义质量',
      customCount: '自定义张数',
      empty: '还没有端点',
      delete: '删除',
    },
    errors: {
      emptyPrompt: '在下方聊天输入框写提示词，再点发送',
      noParams: '还没有端点。打开设置添加。',
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
      aspect_ratio: '比例',
      route: '模型',
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
    inject: {
      label: '注入提示詞約束',
      hint: '依目前參數追加英文 [Output constraints]',
      preview: '將注入的約束',
      placeholder: '',
      off: '',
      empty: '目前參數無需追加約束',
      onlyBlock: '僅追加下方約束塊',
    },
    actions: {
      refresh: '重新整理',
      close: '關閉',
      settings: '設定',
    },
    settings: {
      title: '端點',
      name: '名稱',
      baseUrl: 'Base URL',
      key: 'API Key',
      keyKeep: '留空則保留已儲存的金鑰',
      saveEndpoint: '儲存端點',
      fetch: '讀取模型',
      editModels: '修改模型',
      paramKey: 'Key',
      label: 'Label',
      value: 'Value',
      ratioControlsSize: '比例控制尺寸',
      ratioSizeMismatch: '已勾選的比例和尺寸必須數量一致、一一對應',
      addOption: '添加',
      injectHint: '可用 {label} 和 {value}',
      injectEmpty: '這段不注入',
      editBody: '圖生圖',
      saveModels: '儲存模型',
      quality: '品質',
      transparent: '透明',
      count: '張數',
      customRatio: '自訂比例',
      customQuality: '自訂品質',
      customCount: '自訂張數',
      empty: '還沒有端點',
      delete: '刪除',
    },
    errors: {
      emptyPrompt: '在下方聊天輸入框寫提示詞，再點傳送',
      noParams: '還沒有端點。打開設定新增。',
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
      aspect_ratio: '比率',
      route: 'モデル',
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
    inject: {
      label: 'プロンプト制約を注入',
      hint: '現在のパラメータから英文 [Output constraints] を追加',
      preview: 'プロンプトプレビュー',
      placeholder: '（チャット欄のプロンプト）',
      off: '注入オフ — APIパラメータのみ',
      empty: '現在のパラメータに追加行なし',
    },
    actions: {
      refresh: '更新',
      close: '閉じる',
      settings: '設定',
    },
    settings: {
      title: 'エンドポイント',
      name: '名前',
      baseUrl: 'Base URL',
      key: 'API Key',
      keyKeep: '空欄なら保存済みのキーを維持',
      saveEndpoint: 'エンドポイントを保存',
      fetch: 'モデルを読む',
      editModels: 'モデルを編集',
      paramKey: 'Key',
      label: 'Label',
      value: 'Value',
      ratioControlsSize: '比率がサイズを決める',
      ratioSizeMismatch: '有効な比率とサイズの件数は一致が必要',
      addOption: '追加',
      injectHint: '{label} と {value}',
      injectEmpty: '注入なし',
      editBody: '画像編集',
      saveModels: 'モデルを保存',
      quality: '品質',
      transparent: '透明',
      count: '枚数',
      customRatio: 'カスタム比率',
      customQuality: 'カスタム品質',
      customCount: 'カスタム枚数',
      empty: 'エンドポイントがありません',
      delete: '削除',
    },
    errors: {
      emptyPrompt: '下の入力欄にプロンプトを書いて送信',
      noParams: 'エンドポイントがありません。設定から追加してください。',
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
      aspect_ratio: 'النسبة',
      route: 'النموذج',
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
    inject: {
      label: 'حقن قيود الموجه',
      hint: 'إضافة [Output constraints] بالإنجليزية من المعاملات الحالية',
      preview: 'معاينة الموجه',
      placeholder: '(موجه مربع الدردشة)',
      off: 'الحقن متوقف — معاملات API فقط',
      empty: 'لا توجد قيود للمعاملات الحالية',
    },
    actions: {
      refresh: 'تحديث',
      close: 'إغلاق',
      settings: 'إعدادات',
    },
    settings: {
      title: 'نقاط النهاية',
      name: 'الاسم',
      baseUrl: 'Base URL',
      key: 'API Key',
      keyKeep: 'اتركه فارغًا للإبقاء على المفتاح المحفوظ',
      saveEndpoint: 'حفظ',
      fetch: 'جلب النماذج',
      editModels: 'تعديل النماذج',
      paramKey: 'Key',
      label: 'Label',
      value: 'Value',
      ratioControlsSize: 'النسبة تتحكم بالحجم',
      ratioSizeMismatch: 'عدد خيارات النسبة والحجم يجب أن يتطابق',
      addOption: 'إضافة',
      injectHint: '{label} و {value}',
      injectEmpty: 'بدون حقن',
      editBody: 'تحرير الصورة',
      saveModels: 'حفظ النماذج',
      quality: 'الجودة',
      transparent: 'شفاف',
      count: 'العدد',
      customRatio: 'نسب مخصصة',
      customQuality: 'جودة مخصصة',
      customCount: 'عدد مخصص',
      empty: 'لا توجد نقاط نهاية',
      delete: 'حذف',
    },
    errors: {
      emptyPrompt: 'اكتب المطالبة في مربع الدردشة ثم أرسل',
      noParams: 'لا توجد نقطة نهاية. أضفها من الإعدادات.',
    },
    notify: { errorTitle: 'إنشاء صورة' },
  },
}

function openPanel(seed = '') {
  $panel.set({ open: true, seed: typeof seed === 'string' ? seed : '' })
}

/** When true, closing the bar skips DELETE /overrides (send-in-flight). */
let keepOverridesOnClose = false

function closePanel({ keepOverrides = false } = {}) {
  keepOverridesOnClose = Boolean(keepOverrides)
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

function Field({ label, children, className }) {
  return jsxs('div', {
    className: cn('flex min-w-0 flex-col gap-1', className),
    children: [
      label
        ? jsx('span', {
            className: 'pl-0.5 text-[11px] font-medium text-(--ui-text-primary)',
            children: label,
          })
        : null,
      children,
    ],
  })
}

function EnumSelect({ value, options, onChange, disabled, className, fullWidth, minWidthCh }) {
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
        const value =
          typeof valueRaw === 'string' || typeof valueRaw === 'number'
            ? String(valueRaw)
            : ''
        const label =
          typeof labelRaw === 'string' || typeof labelRaw === 'number'
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
  const selectedLabel = items.find(i => i.value === safe)?.label || safe
  let maxCh = measureLabelCh(selectedLabel)
  for (const it of items) maxCh = Math.max(maxCh, measureLabelCh(it.label))
  const floorCh = Number.isFinite(Number(minWidthCh)) ? Number(minWidthCh) : 8
  const minCh = Math.max(floorCh, Math.min(maxCh, 36))
  const triggerStyle = fullWidth
    ? { width: '100%', minWidth: `calc(${floorCh.toFixed(1)}ch + 2.5rem)` }
    : {
        width: `calc(${minCh.toFixed(1)}ch + 2.5rem)`,
        minWidth: `calc(${floorCh.toFixed(1)}ch + 2.5rem)`,
        maxWidth: '24rem',
      }
  return jsxs(Select, {
      value: safe,
      onValueChange: onChange,
      disabled: Boolean(disabled),
      children: [
        jsx(SelectTrigger, {
          className: cn(
            'h-8 justify-between gap-1.5 rounded-md text-xs font-normal',
            // Lift off panel bg so controls read as interactive.
            'border border-(--ui-border) bg-(--ui-bg-primary)',
            'text-(--ui-text-primary) shadow-sm',
            'hover:border-(--ui-text-tertiary)/50 hover:bg-(--ui-bg-primary)',
            'data-[state=open]:border-(--ui-accent, #22c55e)/60',
            'data-[state=open]:ring-1 data-[state=open]:ring-(--ui-accent, #22c55e)/25',
            fullWidth ? 'w-full min-w-0' : 'shrink-0',
            className,
          ),
          style: triggerStyle,
          title: selectedLabel,
          // Single source of truth for trigger text. Do NOT also render a
          // custom label span — Hermes SelectValue already paints the
          // selected item's textValue/children (double text otherwise).
          children: jsx(SelectValue, {
            className: 'min-w-0 flex-1 truncate text-left tabular-nums',
            placeholder: selectedLabel,
          }),
        }),
        jsx(SelectContent, {
          className: 'max-h-72 border border-(--ui-border) bg-(--ui-bg-primary) shadow-lg',
          style: {
            minWidth: fullWidth
              ? '14rem'
              : `calc(${minCh.toFixed(1)}ch + 2.5rem)`,
          },
          children: items.map(opt =>
            jsx(
              SelectItem,
              {
                value: opt.value,
                textValue: opt.label,
                title: opt.label,
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
    const label = raw.label != null ? String(raw.label).trim() : ''
    if (label) return label
    return optionLabel(raw.value != null ? raw.value : '', t)
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

function prettyPixels(value) {
  const s = String(value || '')
  if (!s || s.toLowerCase() === 'auto') return s || 'auto'
  return s.replace(/x/gi, '×')
}

/** Clean size preset label: ratio first, then pixels. Always human-readable. */
function formatSizeLabel(meta, value, t) {
  const m = meta && typeof meta === 'object' ? meta : {}
  const px = prettyPixels(value)

  // YAML 1.1 sexagesimal trap: unquoted 16:9 becomes int 969. Treat pure
  // digit labels/keys as corrupt and fall back to ratio / known map.
  const ratioRaw = m.ratio != null ? String(m.ratio).trim() : ''
  const labelRaw = m.label != null ? String(m.label).trim() : ''
  const keyRaw = m.key != null ? String(m.key).trim() : ''
  const looksSexagesimal = s => /^\d+$/.test(String(s || ''))

  const knownRatio = {
    '1024x1024': '1:1',
    '1024x1536': '2:3',
    '1536x1024': '3:2',
    '1024x1365': '3:4',
    '1365x1024': '4:3',
    '1088x1920': '9:16',
    '1920x1088': '16:9',
    '2048x2048': '1:1',
    '2560x1440': '16:9',
    '1440x2560': '9:16',
    '3840x2160': '16:9',
    '2160x3840': '9:16',
    auto: 'auto',
  }
  const knownLabel = {
    '2048x2048': '1:1(2k)',
    '2560x1440': '16:9(2k)',
    '1440x2560': '9:16(2k)',
    '3840x2160': '16:9(4k)',
    '2160x3840': '9:16(4k)',
  }

  const ratio =
    ratioRaw && !looksSexagesimal(ratioRaw)
      ? ratioRaw
      : knownRatio[String(value)] || ''
  const key = keyRaw && !looksSexagesimal(keyRaw) && !/[:/]/.test(keyRaw) && !/^\d/.test(keyRaw)
    ? keyRaw
    : ''
  let label =
    labelRaw && !looksSexagesimal(labelRaw) ? labelRaw : knownLabel[String(value)] || ''

  // Named semantic keys only (square/portrait/…), never ratio-like "1:1".
  if (key && key.toLowerCase() !== 'auto') {
    const nameL = t(`ratios.${key}`)
    const base = nameL && nameL !== `ratios.${key}` ? nameL : key
    if (ratio && px && px.toLowerCase() !== 'auto') return `${base} ${ratio} (${px})`
    if (ratio) return `${base} ${ratio}`
    if (px) return `${base} (${px})`
    return base
  }

  const nice = label || ratio || ''
  if (nice && px && px.toLowerCase() !== 'auto') {
    // label already embeds pixels or is auto → keep
    if (nice.toLowerCase() === 'auto') return 'auto'
    if (nice.includes(String(value)) || /\d+[x×]\d+/i.test(nice)) return nice
    // e.g. "16:9" or "1:1(2k)" → "16:9 (1920×1088)"
    return `${nice} (${px})`
  }
  if (nice) return nice
  return px || String(value || '')
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
    if ((name === 'size' || spec.type === 'size') && Array.isArray(spec.presets) && spec.presets.length && !Array.isArray(spec.enum)) {
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
        options.push({ value, label: formatSizeLabel(m, value, t) })
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
          const opt = { value, label: optionLabel(v, t) }
          if (v && typeof v === 'object' && v.inject_label != null && String(v.inject_label).trim()) {
            opt.injectLabel = String(v.inject_label)
          }
          return opt
        })
        .filter(Boolean)
    }
    if (!options.length) continue
    const defaultValue = coerceOptionValue(
      spec.default != null && spec.default !== '' ? spec.default : options[0].value,
    ) || options[0].value
    fields.push({
      name,
      label: spec.display ? fieldLabel(spec.display, t) : fieldLabel(name, t),
      options,
      defaultValue,
      injects: Array.isArray(spec.injects) ? spec.injects.map(item => String(item)) : [],
      injectMode: spec.inject_mode === 'template' ? 'template' : '',
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


const SIZE_RATIO_HINTS = {
  '1254x1254': '1:1',
  '1086x1448': '3:4',
  '941x1672': '9:16',
  '1448x1086': '4:3',
  '1672x941': '16:9',
  '1024x1024': '1:1',
  '1024x1536': '2:3',
  '1536x1024': '3:2',
  '1024x1365': '3:4',
  '1365x1024': '4:3',
  '1088x1920': '9:16',
  '1920x1088': '16:9',
  '2048x2048': '1:1',
  '2560x1440': '16:9',
  '1440x2560': '9:16',
  '3840x2160': '16:9',
  '2160x3840': '9:16',
}

function gcd(a, b) {
  let x = Math.abs(a)
  let y = Math.abs(b)
  while (y) {
    const t = y
    y = x % y
    x = t
  }
  return x || 1
}

function constraintLinesFromFields(uiFields, form) {
  const templated = (uiFields || []).filter(field => field.injectMode === 'template')
  if (!templated.length) return null
  const lines = []
  for (const field of templated) {
    const selected = form ? form[field.name] : ''
    if (selected == null || selected === '') continue
    const opt = (field.options || []).find(item => String(item.value) === String(selected))
    const label = opt && opt.injectLabel
      ? String(opt.injectLabel)
      : opt
        ? String(opt.label || selected)
        : String(selected)
    const value = String(selected)
    for (const template of field.injects || []) {
      const line = fillInject(template, label, value)
      if (line) lines.push(line)
    }
  }
  return lines
}
function augmentPromptWithConstraints(prompt, params, isEdit) {
  const text = String(prompt || '').trim()
  if (!text) return text
  const p = params && typeof params === 'object' ? params : {}
  /** @type {string[]} */
  const lines = []

  const size = typeof p.size === 'string' ? p.size.trim() : ''
  if (size && size.toLowerCase() !== 'auto') {
    let ratio = SIZE_RATIO_HINTS[size] || ''
    if (!ratio && /x/i.test(size)) {
      const m = size.toLowerCase().match(/^(\d+)x(\d+)$/)
      if (m) {
        const w = Number(m[1])
        const h = Number(m[2])
        if (w > 0 && h > 0) {
          const g = gcd(w, h)
          ratio = `${w / g}:${h / g}`
        }
      }
    }
    if (ratio) {
      lines.push(
        `Aspect ratio must be ${ratio}. Target resolution approximately ${size} pixels (width x height).`,
      )
    } else {
      lines.push(`Target resolution approximately ${size} pixels (width x height).`)
    }
  }

  const ar = typeof p.aspect_ratio === 'string' ? p.aspect_ratio.trim() : ''
  if (ar && ar.includes(':') && !lines.some(x => x.includes('Aspect ratio'))) {
    lines.push(`Aspect ratio must be ${ar}.`)
  }

  const quality = typeof p.quality === 'string' ? p.quality.trim().toLowerCase() : ''
  if (quality) {
    if (quality === 'auto') {
      lines.push('Image quality: auto (choose appropriate detail automatically).')
    } else if (quality === 'low') {
      lines.push('Image quality: low (faster, less fine detail).')
    } else if (quality === 'medium') {
      lines.push('Image quality: medium.')
    } else if (quality === 'high') {
      lines.push('Image quality: high (maximum detail and sharpness).')
    } else {
      lines.push(`Image quality: ${quality}.`)
    }
  }

  const nRaw = p.n
  if (nRaw != null && nRaw !== '') {
    const n = Number(nRaw)
    if (Number.isFinite(n) && n >= 1) {
      if (n === 1) {
        lines.push('Generate exactly 1 image.')
      } else {
        lines.push(`Generate exactly ${Math.floor(n)} distinct image variations.`)
      }
    }
  }

  const bg = typeof p.background === 'string' ? p.background.trim().toLowerCase() : ''
  if (bg === 'transparent') {
    lines.push(
      'Background must be fully transparent with a real alpha channel. Do not paint any solid color backdrop.',
    )
  } else if (bg === 'opaque') {
    lines.push('Background must be fully opaque with no transparency.')
  }

  const fmt = typeof p.output_format === 'string' ? p.output_format.trim() : ''
  if (fmt) {
    lines.push(`Deliver the final image as ${fmt.toUpperCase()} format.`)
  }

  const mod = typeof p.moderation === 'string' ? p.moderation.trim().toLowerCase() : ''
  if (mod === 'low') {
    lines.push(
      'Apply a low/lenient safety filter; allow broader creative content within policy.',
    )
  }

  if (isEdit) {
    lines.push(
      'This is an edit of the provided source image(s). Preserve identity, composition, and details that are not explicitly changed by the user request.',
    )
  }

  if (!lines.length) return text
  const marker = '[Output constraints]'
  if (text.includes(marker)) return text
  return `${text}\n\n${marker}\n${lines.map(l => `- ${l}`).join('\n')}`
}

function readComposerPrompt() {
  try {
    const nodes = document.querySelectorAll('[data-slot="composer-rich-input"]')
    for (const el of nodes) {
      if (!(el instanceof HTMLElement)) continue
      const style = window.getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden') continue
      const text = (el.innerText || el.textContent || '').replace(/\u00a0/g, ' ').trim()
      if (text) return text.replace(/^\/create-image(?:\s+|$)/i, '').trim()
    }
  } catch {
    /* ignore */
  }
  return ''
}


async function pushOverrides(active, fields, injectEnabled, route, extra) {
  try {
    if (!active) {
      await restClient('/overrides', { method: 'DELETE' })
      return
    }
    const form = $form.get()
    const r = route && typeof route === 'object' ? route : lastRoute || {}
    /** @type {Record<string, unknown>} */
    const body = {
      active: true,
      prompt_constraints: Boolean(injectEnabled),
      provider: r.provider || undefined,
      model: r.model || undefined,
    }
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
    if (extra && typeof extra === 'object') {
      if (extra.direct === true) body.direct = true
      if (typeof extra.prompt === 'string' && extra.prompt.trim()) {
        body.prompt = extra.prompt.trim()
      }
      if (typeof extra.image_url === 'string' && extra.image_url.trim()) {
        body.image_url = extra.image_url.trim()
      }
      if (Array.isArray(extra.reference_image_urls) && extra.reference_image_urls.length) {
        body.reference_image_urls = extra.reference_image_urls
      }
      for (const key of ['size', 'quality', 'n', 'background', 'output_format', 'output_compression', 'moderation', 'aspect_ratio']) {
        if (extra[key] == null || extra[key] === '') continue
        if (key === 'n') {
          const n = Number(extra.n)
          if (Number.isFinite(n) && n >= 1) body.n = n
          continue
        }
        body[key] = extra[key]
      }
    }
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
/** Last inject toggle for middleware push. */
let lastInjectEnabled = false
/** Last selected provider+model for middleware push. */
let lastRoute = { provider: '', model: '', id: '' }

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

const endpointInputClass =
  'h-7 min-w-0 flex-1 rounded-md border border-(--ui-border) bg-(--ui-bg-primary)/40 px-2 text-[11px] text-(--ui-text-primary)'

const SLOT_ORDER = ['aspect_ratio', 'size', 'quality', 'n', 'background']
const SLOT_PRESETS = {
  aspect_ratio: ['1:1', '16:9', '9:16', '3:4', '4:3', '2:3', '3:2'],
  size: [],
  quality: ['low', 'medium', 'high'],
  n: ['1', '2', '4', '8'],
  background: ['opaque', 'transparent'],
}
const DEFAULT_INJECT = {
  aspect_ratio: 'Aspect ratio must be {label}.',
  size: 'Target resolution approximately {value} pixels (width x height).',
  quality: 'Image quality: {value}.',
  n: 'Generate exactly {value} image(s).',
  background: 'Background must be {value}.',
}

function fillInject(template, label, value) {
  return String(template || '').replaceAll('{label}', label).replaceAll('{value}', value).trim()
}

const DEFAULT_KEYS = {
  aspect_ratio: 'aspect_ratio',
  size: 'size',
  quality: 'quality',
  n: 'n',
  background: 'background',
}

function storedList(value) {
  return Array.isArray(value) ? value.map(String) : []
}

function rowsForSlot(slot, saved) {
  const list = Array.isArray(saved) ? saved : []
  const seen = new Set()
  const rows = []
  for (const preset of SLOT_PRESETS[slot]) {
    const hit = list.find(item => String(item && item.value != null ? item.value : item) === preset)
    rows.push({
      label: hit && hit.label != null ? String(hit.label) : preset,
      value: preset,
      enabled: Boolean(hit) && hit.enabled !== false,
    })
    seen.add(preset)
  }
  for (const item of list) {
    const value = String(item && item.value != null ? item.value : item || '').trim()
    if (!value || seen.has(value)) continue
    rows.push({
      label: String((item && item.label) || value),
      value,
      enabled: !item || item.enabled !== false,
    })
  }
  return rows
}

function savedOptions(saved) {
  return (Array.isArray(saved) ? saved : [])
    .map(item => ({
      label: String(item && item.label != null ? item.label : item && item.value != null ? item.value : ''),
      value: String(item && item.value != null ? item.value : '').trim(),
      enabled: !item || item.enabled !== false,
    }))
    .filter(opt => opt.value)
}

function modelFromApi(raw) {
  const fieldsIn = raw.fields && typeof raw.fields === 'object' ? raw.fields : null
  const fields = {}
  for (const slot of SLOT_ORDER) {
    let saved = fieldsIn && Array.isArray(fieldsIn[slot]?.options) ? fieldsIn[slot].options : null
    if (!fieldsIn) {
      if (slot === 'aspect_ratio') saved = storedList(raw.aspect_ratios).map(v => ({ label: v, value: v, enabled: true }))
      else if (slot === 'quality') saved = storedList(raw.qualities).map(v => ({ label: v, value: v, enabled: true }))
      else if (slot === 'n') saved = storedList(raw.counts).map(v => ({ label: v, value: v, enabled: true }))
      else if (slot === 'background' && raw.transparent) {
        saved = ['opaque', 'transparent'].map(v => ({ label: v, value: v, enabled: true }))
      } else saved = []
    }
    fields[slot] = {
      key: String((fieldsIn && fieldsIn[slot] && fieldsIn[slot].key) || DEFAULT_KEYS[slot]),
      inject: fieldsIn && fieldsIn[slot] && fieldsIn[slot].inject != null
        ? String(fieldsIn[slot].inject)
        : DEFAULT_INJECT[slot],
      options: fieldsIn && fieldsIn[slot]
        ? savedOptions(saved)
        : rowsForSlot(slot, saved || []),
    }
  }
  return {
    id: String(raw.id || ''),
    enabled: Boolean(raw.enabled),
    ratio_controls_size: Boolean(raw.ratio_controls_size),
    edit_body: raw.edit_body === 'json' ? 'json' : 'multipart',
    fields,
  }
}

function blankModel(id) {
  return modelFromApi({ id, enabled: false, fields: {} })
}

function EndpointSettings({ t, onChanged, onClose }) {
  const [rows, setRows] = useState([])
  const [draft, setDraft] = useState({ id: '', name: '', base_url: '', api_key: '' })
  const [boards, setBoards] = useState({})
  const [openModels, setOpenModels] = useState({})
  const [localError, setLocalError] = useState('')
  const [busy, setBusy] = useState('')

  const reload = useCallback(async () => {
    const data = await restClient('/endpoints', { method: 'GET' })
    const list = Array.isArray(data?.endpoints) ? data.endpoints : []
    setRows(list)
    setBoards(() => {
      const next = {}
      for (const row of list) {
        next[row.id] = (Array.isArray(row.models) ? row.models : []).map(modelFromApi)
      }
      return next
    })
  }, [])

  useEffect(() => {
    void reload().catch(err => setLocalError(err?.message || String(err)))
  }, [reload])

  const saveEndpoint = async () => {
    setBusy('save')
    setLocalError('')
    try {
      await restClient('/endpoints', {
        method: 'POST',
        body: {
          id: draft.id || undefined,
          name: draft.name,
          base_url: draft.base_url,
          api_key: draft.api_key || undefined,
        },
      })
      setDraft({ id: '', name: '', base_url: '', api_key: '' })
      await reload()
    } catch (err) {
      setLocalError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  const removeEndpoint = async id => {
    setBusy(id)
    setLocalError('')
    try {
      await restClient(`/endpoints/${encodeURIComponent(id)}`, { method: 'DELETE' })
      await reload()
      onChanged?.()
    } catch (err) {
      setLocalError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  const fetchModels = async id => {
    setBusy(`fetch:${id}`)
    setLocalError('')
    try {
      const data = await restClient(`/endpoints/${encodeURIComponent(id)}/models`, { method: 'POST' })
      const ids = Array.isArray(data?.models) ? data.models.map(String) : []
      setBoards(prev => {
        const cur = prev[id] || []
        const byId = new Map(cur.map(m => [m.id, m]))
        for (const modelId of ids) {
          if (!byId.has(modelId)) byId.set(modelId, blankModel(modelId))
        }
        return { ...prev, [id]: [...byId.values()] }
      })
    } catch (err) {
      setLocalError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  const editModels = async id => {
    setOpenModels(prev => ({ ...prev, [id]: true }))
    const row = rows.find(item => item.id === id)
    if (!row || !(row.models || []).length) await fetchModels(id)
  }

  const patchModel = (endpointId, modelId, partial) => {
    setBoards(prev => ({
      ...prev,
      [endpointId]: (prev[endpointId] || []).map(m => (m.id === modelId ? { ...m, ...partial } : m)),
    }))
  }

  const patchField = (endpointId, modelId, slot, partial) => {
    setBoards(prev => ({
      ...prev,
      [endpointId]: (prev[endpointId] || []).map(m => {
        if (m.id !== modelId) return m
        return { ...m, fields: { ...m.fields, [slot]: { ...m.fields[slot], ...partial } } }
      }),
    }))
  }

  const patchOption = (endpointId, modelId, slot, index, partial) => {
    setBoards(prev => ({
      ...prev,
      [endpointId]: (prev[endpointId] || []).map(m => {
        if (m.id !== modelId) return m
        const field = m.fields[slot]
        const options = field.options.map((opt, i) => (i === index ? { ...opt, ...partial } : opt))
        return { ...m, fields: { ...m.fields, [slot]: { ...field, options } } }
      }),
    }))
  }

  const blankOption = () => ({ label: '', value: '', enabled: true })

  const alignSize = (ratioOptions, sizeOptions) => {
    const next = sizeOptions.map(opt => ({ ...opt }))
    while (next.length < ratioOptions.length) next.push(blankOption())
    return next.slice(0, ratioOptions.length)
  }

  const removeOption = (endpointId, modelId, slot, index) => {
    setBoards(prev => ({
      ...prev,
      [endpointId]: (prev[endpointId] || []).map(m => {
        if (m.id !== modelId) return m
        const drop = list => list.filter((_, i) => i !== index)
        const fields = { ...m.fields, [slot]: { ...m.fields[slot], options: drop(m.fields[slot].options) } }
        if (m.ratio_controls_size && slot === 'aspect_ratio') {
          fields.size = { ...m.fields.size, options: drop(m.fields.size.options) }
        }
        return { ...m, fields }
      }),
    }))
  }

  const addOption = (endpointId, modelId, slot) => {
    setBoards(prev => ({
      ...prev,
      [endpointId]: (prev[endpointId] || []).map(m => {
        if (m.id !== modelId) return m
        const fields = {
          ...m.fields,
          [slot]: { ...m.fields[slot], options: [...m.fields[slot].options, blankOption()] },
        }
        if (m.ratio_controls_size && slot === 'aspect_ratio') {
          fields.size = { ...m.fields.size, options: [...m.fields.size.options, blankOption()] }
        }
        return { ...m, fields }
      }),
    }))
  }

  const saveModels = async id => {
    setBusy(`save:${id}`)
    setLocalError('')
    try {
      const models = (boards[id] || []).map(m => ({
        id: m.id,
        enabled: Boolean(m.enabled),
        ratio_controls_size: Boolean(m.ratio_controls_size),
        edit_body: m.edit_body === 'json' ? 'json' : 'multipart',
        fields: Object.fromEntries(SLOT_ORDER.map(slot => [slot, {
          key: String(m.fields[slot].key || DEFAULT_KEYS[slot]).trim() || DEFAULT_KEYS[slot],
          inject: String(m.fields[slot].inject ?? DEFAULT_INJECT[slot]),
          options: m.fields[slot].options
            .map(opt => ({
              label: String(opt.label || opt.value || '').trim(),
              value: String(opt.value || '').trim(),
              enabled: Boolean(opt.enabled),
            }))
            .filter(opt => opt.value),
        }])),
      }))
      for (const model of models) {
        if (!model.ratio_controls_size) continue
        const ratios = model.fields.aspect_ratio.options.filter(opt => opt.enabled)
        const sizes = model.fields.size.options.filter(opt => opt.enabled)
        if (ratios.length !== sizes.length) {
          setLocalError(t('settings.ratioSizeMismatch'))
          return
        }
      }
      await restClient(`/endpoints/${encodeURIComponent(id)}/models`, {
        method: 'PUT',
        body: { models },
      })
      await reload()
      onChanged?.()
      setOpenModels(prev => ({ ...prev, [id]: false }))
    } catch (err) {
      setLocalError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  const fieldEditor = (rowId, model, slot) => {
    const field = model.fields[slot]
    return jsxs('div', {
      className: 'mt-2',
      children: [
        jsxs('div', {
          className: 'flex items-center gap-2',
          children: [
            jsx('span', {
              className: 'w-14 shrink-0 text-[10px] text-(--ui-text-tertiary)',
              children: t(`labels.${slot}`),
            }),
            jsx('input', {
              className: endpointInputClass,
              value: field.key,
              'aria-label': t('settings.paramKey'),
              onChange: e => patchField(rowId, model.id, slot, { key: e.target.value }),
            }),
          ],
        }),
        field.options.map((opt, index) =>
          jsxs('div', {
            className: 'mt-1 flex items-center gap-1',
            children: [
              jsx('input', {
                type: 'checkbox',
                checked: Boolean(opt.enabled),
                onChange: e => patchOption(rowId, model.id, slot, index, { enabled: e.target.checked }),
              }),
              jsx('input', {
                className: endpointInputClass,
                value: opt.label,
                placeholder: t('settings.label'),
                onChange: e => patchOption(rowId, model.id, slot, index, { label: e.target.value }),
              }),
              jsx('input', {
                className: endpointInputClass,
                value: opt.value,
                placeholder: t('settings.value'),
                onChange: e => patchOption(rowId, model.id, slot, index, { value: e.target.value }),
              }),
              slot === 'size' && model.ratio_controls_size
                ? null
                : jsx('button', {
                    type: 'button',
                    className: 'shrink-0 text-[10px] text-red-400',
                    onClick: () => removeOption(rowId, model.id, slot, index),
                    children: t('settings.delete'),
                  }),
            ],
          }, `${slot}-${index}`),
        ),
        jsx('button', {
          type: 'button',
          className: 'mt-1 text-[10px] text-(--ui-text-secondary)',
          onClick: () => addOption(rowId, model.id, slot),
          children: t('settings.addOption'),
          style: slot === 'size' && model.ratio_controls_size ? { display: 'none' } : undefined,
        }),
        slot === 'aspect_ratio' && model.ratio_controls_size
          ? null
          : jsx('textarea', {
          className: 'mt-1 min-h-14 w-full rounded-md border border-(--ui-border) bg-(--ui-bg-primary)/40 px-2 py-1 text-[10px] text-(--ui-text-primary)',
          value: field.inject || '',
          placeholder: t('settings.injectHint'),
          onChange: e => patchField(rowId, model.id, slot, { inject: e.target.value }),
        }),
        slot === 'aspect_ratio' && model.ratio_controls_size
          ? null
          : jsx('div', {
          className: 'mt-1 whitespace-pre-wrap text-[10px] text-(--ui-text-tertiary)',
          children: (() => {
            const sample = field.options.find(opt => opt.enabled && opt.value) || field.options.find(opt => opt.value)
            if (!field.inject || !sample) return t('settings.injectEmpty')
            return fillInject(field.inject, sample.label || sample.value, sample.value)
          })(),
        }),
        slot === 'size'
          ? jsxs('label', {
              className: 'mt-1 flex items-center gap-1 text-[10px]',
              children: [
                jsx('input', {
                  type: 'checkbox',
                  checked: Boolean(model.ratio_controls_size),
                  onChange: e => {
                    const on = e.target.checked
                    setBoards(prev => ({
                      ...prev,
                      [rowId]: (prev[rowId] || []).map(item => {
                        if (item.id !== model.id) return item
                        if (!on) return { ...item, ratio_controls_size: false }
                        return {
                          ...item,
                          ratio_controls_size: true,
                          fields: {
                            ...item.fields,
                            size: {
                              ...item.fields.size,
                              options: alignSize(item.fields.aspect_ratio.options, item.fields.size.options),
                            },
                          },
                        }
                      }),
                    }))
                  },
                }),
                t('settings.ratioControlsSize'),
              ],
            })
          : null,
      ],
    }, slot)
  }

  return jsxs('div', {
    className: 'mt-2.5 flex flex-col gap-2',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between gap-2',
        children: [
          jsx('div', { className: 'text-[11px] font-medium text-(--ui-text-primary)', children: t('settings.title') }),
          jsx('button', {
            type: 'button',
            className: 'text-[11px] text-(--ui-text-secondary)',
            onClick: () => onClose?.(),
            children: t('actions.close'),
          }),
        ],
      }),
      jsxs('div', {
        className: 'flex flex-wrap items-center gap-2',
        children: [
          jsx('input', {
            className: endpointInputClass,
            placeholder: t('settings.name'),
            value: draft.name,
            onChange: e => setDraft({ ...draft, name: e.target.value }),
          }),
          jsx('input', {
            className: endpointInputClass,
            placeholder: t('settings.baseUrl'),
            value: draft.base_url,
            onChange: e => setDraft({ ...draft, base_url: e.target.value }),
          }),
          jsx('input', {
            className: endpointInputClass,
            type: 'password',
            autoComplete: 'off',
            placeholder: draft.id ? t('settings.keyKeep') : t('settings.key'),
            value: draft.api_key,
            onChange: e => setDraft({ ...draft, api_key: e.target.value }),
          }),
          jsx('button', {
            type: 'button',
            className: 'h-7 shrink-0 rounded-md bg-emerald-500/20 px-2 text-[11px] text-emerald-200',
            disabled: busy === 'save',
            onClick: () => void saveEndpoint(),
            children: t('settings.saveEndpoint'),
          }),
        ],
      }),
      rows.length
        ? rows.map(row =>
            jsxs(
              'div',
              {
                className: 'rounded-lg border border-(--ui-border) px-2 py-2',
                children: [
                  jsxs('div', {
                    className: 'flex flex-wrap items-center gap-2',
                    children: [
                      jsx('button', {
                        type: 'button',
                        className: 'min-w-0 flex-1 truncate text-left text-[11px] text-(--ui-text-primary)',
                        onClick: () =>
                          setDraft({ id: row.id, name: row.name || '', base_url: row.base_url || '', api_key: '' }),
                        children: `${row.name} · ${row.base_url}`,
                      }),
                      jsx('button', {
                        type: 'button',
                        className: 'text-[11px]',
                        disabled: Boolean(busy),
                        onClick: () => void editModels(row.id),
                        children: t('settings.editModels'),
                      }),
                      jsx('button', {
                        type: 'button',
                        className: 'text-[11px]',
                        disabled: Boolean(busy),
                        onClick: () => void saveModels(row.id),
                        children: t('settings.saveModels'),
                      }),
                      jsx('button', {
                        type: 'button',
                        className: 'text-[11px] text-red-400',
                        disabled: Boolean(busy),
                        onClick: () => void removeEndpoint(row.id),
                        children: t('settings.delete'),
                      }),
                    ],
                  }),
                  openModels[row.id]
                    ? jsx('div', {
                    className: 'max-h-80 overflow-y-auto',
                    children: (boards[row.id] || []).map(model =>
                    jsxs(
                      'div',
                      {
                        className: 'mt-2 border-t border-(--ui-border) pt-2',
                        children: [
                          jsxs('label', {
                            className: 'flex items-center gap-2 text-[11px]',
                            children: [
                              jsx('input', {
                                type: 'checkbox',
                                checked: Boolean(model.enabled),
                                onChange: e => patchModel(row.id, model.id, { enabled: e.target.checked }),
                              }),
                              model.id,
                            ],
                          }),
                          model.enabled
                            ? jsxs('label', {
                                className: 'mt-2 flex items-center gap-2 text-[10px] text-(--ui-text-tertiary)',
                                children: [
                                  jsx('span', { className: 'shrink-0', children: t('settings.editBody') }),
                                  jsx('select', {
                                    className: endpointInputClass,
                                    value: model.edit_body === 'json' ? 'json' : 'multipart',
                                    onChange: e => patchModel(row.id, model.id, { edit_body: e.target.value }),
                                    children: [
                                      jsx('option', { value: 'multipart', children: 'multipart' }, 'multipart'),
                                      jsx('option', { value: 'json', children: 'json' }, 'json'),
                                    ],
                                  }),
                                ],
                              })
                            : null,
                          model.enabled
                            ? jsxs('div', {
                                children: SLOT_ORDER.map(slot => fieldEditor(row.id, model, slot)),
                              })
                            : null,
                        ],
                      },
                      model.id,
                    ),
                  ),
                  })
                    : null,
                ],
              },
              row.id,
            ),
          )
        : jsx('div', {
            className: 'text-[11px] text-(--ui-text-tertiary)',
            children: t('settings.empty'),
          }),
      localError
        ? jsx('div', { className: 'break-all text-[11px] text-red-500', children: localError })
        : null,
    ],
  })
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
  const [injectEnabled, setInjectEnabled] = useState(false)
  const [composerText, setComposerText] = useState('')
  const [routeId, setRouteId] = useState('')
  const [catalog, setCatalog] = useState([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const injectTouched = useRef(false)

  const applyCapsData = useCallback(
    (data, { resetInject = false } = {}) => {
      setCapsPayload(data)
      const options = Array.isArray(data?.catalog)
        ? data.catalog
        : Array.isArray(data?.options)
          ? data.options
          : []
      if (options.length) setCatalog(options)

      const provider = String(data?.provider || '').trim()
      const model = String(data?.model || '').trim()
      const id =
        String(data?.id || '').trim() ||
        (provider && model ? `${provider}::${model}` : '')
      if (id) {
        setRouteId(id)
        lastRoute = { provider, model, id }
      }

      const params = data?.capabilities?.params || {}
      const nextFields = buildUiFields(params, t)
      setFields(nextFields)
      lastFields = nextFields

      const defaults = defaultsFromFields(nextFields)
      const prev = $form.get() || {}
      /** @type {Record<string, string>} */
      const merged = {}
      for (const f of nextFields) {
        const cur = prev[f.name]
        const ok = f.options.some(o => o.value === String(cur))
        // On route switch, prefer defaults for new field sets.
        merged[f.name] = ok && !resetInject ? String(cur) : f.defaultValue
      }
      // Always seed defaults for the active route.
      $form.set(Object.keys(merged).length ? merged : defaults)

      if (resetInject || !injectTouched.current) {
        const ov = data?.overrides?.prompt_constraints
        const cfg =
          data?.prompt_constraints_default ??
          data?.prompt_constraints ??
          data?.capabilities?.prompt_constraints
        const next = typeof ov === 'boolean' && !resetInject ? ov : Boolean(cfg)
        setInjectEnabled(next)
        lastInjectEnabled = next
        if (resetInject) injectTouched.current = false
      }
    },
    [t],
  )

  const loadCaps = useCallback(
    async (sel) => {
      setLoadingCaps(true)
      setError('')
      try {
        let path = '/capabilities'
        if (sel?.provider && sel?.model) {
          const q = new URLSearchParams({
            provider: sel.provider,
            model: sel.model,
          })
          if (sel.endpointId) q.set('endpoint_id', sel.endpointId)
          path = `/capabilities?${q.toString()}`
        }
        const data = await restClient(path, { method: 'GET' })
        applyCapsData(data, { resetInject: Boolean(sel) })
      } catch (err) {
        setCapsPayload(null)
        setFields([])
        lastFields = []
        setError(err?.message || String(err))
      } finally {
        setLoadingCaps(false)
      }
    },
    [applyCapsData],
  )

  useEffect(() => {
      if (!open) {
        injectTouched.current = false
        if (keepOverridesOnClose) {
          // Sent just now — leave panel overrides for image_generate.
          keepOverridesOnClose = false
          return
        }
        void pushOverrides(false, [], false, null)
        return
      }
      void loadCaps(null)
    }, [open, loadCaps])

  useEffect(() => {
    if (!open || !fields.length) return
    lastInjectEnabled = Boolean(injectEnabled)
    lastRoute = {
      provider: lastRoute.provider || String(capsPayload?.provider || ''),
      model: lastRoute.model || String(capsPayload?.model || ''),
      id: routeId || lastRoute.id || '',
    }
    void pushOverrides(true, fields, injectEnabled, lastRoute)
  }, [open, fields, form, injectEnabled, routeId, capsPayload])

  // Poll composer text for live preview while panel open.
  useEffect(() => {
    if (!open) return undefined
    const tick = () => {
      const live = readComposerPrompt()
      const seed = String($panel.get()?.seed || '').trim()
      setComposerText(live || seed || '')
    }
    tick()
    const id = window.setInterval(tick, 400)
    return () => window.clearInterval(id)
  }, [open])

  const routeOptions = useMemo(() => {
    const list = Array.isArray(catalog) && catalog.length
      ? catalog
      : Array.isArray(capsPayload?.catalog)
        ? capsPayload.catalog
        : []
    return list
      .map(it => {
        const provider = String(it?.provider || '').trim()
        const model = String(it?.model || '').trim()
        if (!provider || !model) return null
        const id = String(it?.id || `${provider}::${model}`)
        const display = String(it?.display || '').trim()
        const label = display || model
        return { value: id, label, provider, model, endpointId: String(it?.endpoint_id || '') }
      })
      .filter(Boolean)
  }, [catalog, capsPayload])

  const preview = useMemo(() => {
    if (!injectEnabled) {
      return { show: false, text: '', note: '' }
    }
    // Only show the constraint block that will be appended — not the full chat prompt.
    const marker = '[Output constraints]'
    const dummy = '__PROMPT__'
    const custom = constraintLinesFromFields(fields, form || {})
    if (custom) {
      if (!custom.length) return { show: true, text: '', note: t('inject.empty') }
      return {
        show: true,
        text: `[Output constraints]\n${custom.map(line => `- ${line}`).join('\n')}`,
        note: t('inject.onlyBlock'),
      }
    }
    const final = augmentPromptWithConstraints(dummy, form || {}, false)
    if (!final.includes(marker)) {
      return { show: true, text: '', note: t('inject.empty') }
    }
    const idx = final.indexOf(marker)
    const block = final.slice(idx).trim()
    return { show: true, text: block, note: t('inject.onlyBlock') }
  }, [form, fields, injectEnabled, t])

if (!open) return null

  const provider = capsPayload?.provider || lastRoute.provider || '—'
  const model = capsPayload?.model || lastRoute.model || '—'
  const ready = Boolean(
    capsPayload?.available ?? capsPayload?.ready ?? (capsPayload?.provider && capsPayload?.model),
  )

  const onRouteChange = v => {
    const id = String(v || '')
    const hit = routeOptions.find(o => o.value === id)
    if (!hit) return
    setRouteId(id)
    lastRoute = { provider: hit.provider, model: hit.model, id }
    injectTouched.current = false
    if (hit.endpointId) {
      void restClient('/active', {
        method: 'PUT',
        body: { endpoint_id: hit.endpointId, model: hit.model },
      }).catch(() => {})
    }
    void loadCaps({ provider: hit.provider, model: hit.model, endpointId: hit.endpointId })
  }

  const statusLine = [
    !ready && capsPayload ? t('status.notReady') : null,
    loadingCaps ? t('status.loading') : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return jsxs('div', {
    className: cn(
      'mb-2 w-full rounded-xl border border-(--ui-border)',
      'bg-(--ui-bg-secondary)/90 px-3 py-2.5',
      'text-xs text-(--ui-text-secondary) shadow-sm backdrop-blur',
    ),
    'data-create-image-bar': '1',
    children: [
      // Row 1: title + model + actions
      jsxs('div', {
        className: 'flex items-center gap-2',
        children: [
          jsxs('span', {
                      className: cn(
                        'inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1',
                        // Soft green pill — light weight, no heavy border.
                        'bg-emerald-500/15 text-emerald-300',
                        'text-[11px] font-medium tracking-normal',
                      ),
                      children: [
                        jsx(Codicon, {
                          name: 'symbol-color',
                          className: 'text-[0.8rem] text-emerald-400/90',
                        }),
                        jsx('span', { children: t('title') }),
                      ],
                    }),
          jsx('div', {
            className: 'min-w-0 flex-1',
            children: routeOptions.length
              ? jsx(EnumSelect, {
                  value: routeId || routeOptions[0].value,
                  options: routeOptions.map(o => ({ value: o.value, label: o.label })),
                  disabled: busy || loadingCaps,
                  onChange: onRouteChange,
                  fullWidth: true,
                })
              : jsx('div', {
                  className:
                    'flex h-8 items-center truncate rounded-md border border-(--ui-border) bg-(--ui-bg-primary)/40 px-2 text-[11px] text-(--ui-text-tertiary)',
                  children: `${provider} · ${model}`,
                }),
          }),
          statusLine
            ? jsx('span', {
                className: 'hidden shrink-0 text-[10px] text-(--ui-text-tertiary) sm:inline',
                children: statusLine,
              })
            : null,
          jsx(IconBtn, {
            title: t('actions.settings'),
            name: 'settings-gear',
            disabled: busy,
            onClick: () => setSettingsOpen(openNow => !openNow),
          }),
          jsx(IconBtn, {
            title: t('actions.refresh'),
            name: 'refresh',
            spinning: loadingCaps,
            disabled: loadingCaps || busy,
            onClick: () => {
              const hit = routeOptions.find(o => o.value === routeId)
              void loadCaps(
                hit
                  ? { provider: hit.provider, model: hit.model, endpointId: hit.endpointId }
                  : null,
              )
            },
          }),
          jsx(IconBtn, {
            title: t('actions.close'),
            name: 'close',
            disabled: busy,
            onClick: () => {
              injectTouched.current = false
              void pushOverrides(false, [], false, null)
              closePanel()
            },
          }),
        ],
      }),

      // Row 2: settings or params
      settingsOpen
        ? jsx(EndpointSettings, {
            t,
            onClose: () => setSettingsOpen(false),
            onChanged: () => {
              void loadCaps(null)
            },
          })
        : fields.length
        ? jsx('div', {
            className:
              'mt-2.5 flex flex-wrap items-end gap-x-3 gap-y-2',
            children: fields.map(f =>
              jsx(
                Field,
                {
                  label: f.label,
                  className:
                    f.name === 'size'
                      ? 'col-span-2 min-w-[14rem] sm:min-w-[16rem] sm:flex-1'
                      : 'min-w-[6rem] sm:min-w-[7rem]',
                  children: jsx(EnumSelect, {
                    value: form?.[f.name] ?? f.defaultValue,
                    options: f.options,
                    disabled: busy,
                    onChange: v => patchForm({ [f.name]: v }),
                    fullWidth: true,
                    minWidthCh: f.name === 'size' ? 18 : f.name === 'background' || f.name === 'quality' ? 7 : 4,
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

      // Row 3: inject toggle; preview only when checked (constraints block only)
      jsxs('div', {
        className:
          'mt-2.5 rounded-lg border border-(--ui-border) bg-(--ui-bg-primary)/35 px-2.5 py-2',
        children: [
          jsxs('label', {
            className: 'flex cursor-pointer select-none items-center gap-2',
            children: [
              jsx('input', {
                type: 'checkbox',
                className: 'h-3.5 w-3.5 shrink-0 accent-(--ui-accent, #3b82f6)',
                checked: Boolean(injectEnabled),
                disabled: busy,
                onChange: e => {
                  injectTouched.current = true
                  const next = Boolean(e?.target?.checked)
                  setInjectEnabled(next)
                  lastInjectEnabled = next
                },
              }),
              jsx('span', {
                className: 'text-[11px] font-medium text-(--ui-text-primary)',
                children: t('inject.label'),
              }),
              jsx('span', {
                className: 'min-w-0 flex-1 truncate text-[10px] text-(--ui-text-tertiary)',
                children: t('inject.hint'),
              }),
            ],
          }),
          preview.show
            ? jsxs('div', {
                className: 'mt-2',
                children: [
                  jsx('div', {
                    className:
                      'mb-1 flex items-center justify-between gap-2 text-[10px] font-medium text-(--ui-text-tertiary)',
                    children: [
                      jsx('span', { children: t('inject.preview') }),
                      preview.note
                        ? jsx('span', { className: 'font-normal', children: preview.note })
                        : null,
                    ],
                  }),
                  preview.text
                    ? jsx('pre', {
                        className: cn(
                          'm-0 max-h-40 overflow-auto whitespace-pre-wrap break-words',
                          'rounded-md border border-(--ui-border) bg-(--ui-bg-tertiary)/50',
                          'px-2.5 py-2 font-mono text-[11px] leading-5 text-(--ui-text-primary)',
                        ),
                        children: preview.text,
                      })
                    : jsx('div', {
                        className: 'text-[11px] text-(--ui-text-tertiary)',
                        children: t('inject.empty'),
                      }),
                ],
              })
            : null,
        ],
      }),

      error
        ? jsx('div', {
            className: 'mt-1.5 break-all text-[11px] text-red-500',
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
    'Image bar: pick provider+model, params reload live, inject preview, route overrides image_generate.',
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
      void pushOverrides(false, [], false, null)
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

          await pushOverrides(true, lastFields, lastInjectEnabled, lastRoute, {
            direct: true,
            ...args,
            prompt: String(args.prompt || text),
          })
          closePanel({ keepOverrides: true })
          const prompt = String(args.prompt || text)
          return {
            ...draft,
            text: prompt,
            displayText: prompt,
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
