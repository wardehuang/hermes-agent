import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('user layout presets', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.resetModules()
  })

  async function setup() {
    const model = await import('./model')
    const store = await import('./store')
    const panes = await import('@/store/panes')
    const presets = await import('./presets')
    const { registry } = await import('@/contrib/registry')

    const tree = model.split('row', [model.group(['files']), model.group(['workspace'])], [1, 4])

    store.$layoutTree.set(tree)
    panes.ensurePaneRegistered('files', { open: true })
    panes.ensurePaneRegistered('sessions', { open: true })
    panes.ensurePaneRegistered('workspace', { open: true })

    return { model, panes, presets, registry, store, tree }
  }

  it('restores dragged sidebar widths when reapplying a saved layout', async () => {
    const { panes, presets, registry } = await setup()

    panes.setPaneWidthOverride('files', 420)
    panes.setPaneWidthOverride('sessions', 280)

    presets.saveCurrentLayoutAs('Wide rails')

    panes.setPaneWidthOverride('files', 160)
    panes.setPaneWidthOverride('sessions', 160)

    const id = 'user-wide-rails'
    const entry = registry.getArea(presets.LAYOUTS_AREA).find(c => c.id === id)

    expect(entry).toBeDefined()
    presets.applyLayoutPreset(id, entry!.data as import('./model').LayoutNode)

    expect(panes.getPaneStateSnapshot('files')?.widthOverride).toBe(420)
    expect(panes.getPaneStateSnapshot('sessions')?.widthOverride).toBe(280)
  })

  it('does not restore sizes for a zone-editor save that omitted paneSizes', async () => {
    const { panes, presets, tree } = await setup()

    panes.setPaneWidthOverride('files', 420)

    const id = presets.saveLayoutPresetTree('Grid only', tree)

    expect(id).toBe('user-grid-only')
    panes.setPaneWidthOverride('files', 160)
    presets.applyLayoutPreset(id!, tree)

    expect(panes.getPaneStateSnapshot('files')?.widthOverride).toBeUndefined()
  })

  it('clears live overrides when applying a bundled preset', async () => {
    const { panes, presets, tree } = await setup()

    panes.setPaneWidthOverride('files', 420)
    presets.applyLayoutPreset('coding', tree)

    expect(panes.getPaneStateSnapshot('files')?.widthOverride).toBeUndefined()
  })
})
