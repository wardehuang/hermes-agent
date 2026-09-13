import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('coding layout editor slot', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.resetModules()
  })

  afterEach(() => {
    vi.resetModules()
  })

  async function setup() {
    const tree = await import('@/components/pane-shell/tree/store')
    const model = await import('@/components/pane-shell/tree/model')
    const { registry } = await import('@/contrib/registry')

    registry.register({
      id: 'workspace',
      area: 'panes',
      title: 'chat',
      data: { placement: 'main', uncloseable: true },
      render: () => null
    })
    registry.register({
      id: tree.EDITOR_PANE_ID,
      area: 'panes',
      title: 'editor',
      data: { autoAdopt: false, minWidth: '22vw', placement: 'main', uncloseable: true },
      render: () => null
    })
    registry.register({
      id: 'terminal',
      area: 'panes',
      title: 'terminal',
      data: { placement: 'bottom' },
      render: () => null
    })
    registry.register({
      id: 'files',
      area: 'panes',
      title: 'files',
      data: { placement: 'right' },
      render: () => null
    })
    registry.register({
      id: 'review',
      area: 'panes',
      title: 'review',
      data: { placement: 'right' },
      render: () => null
    })
    registry.register({
      id: 'sessions',
      area: 'panes',
      title: 'sessions',
      data: { hideOnly: true, placement: 'left' },
      render: () => null
    })

    const defaultTree = model.split(
      'row',
      [
        model.group(['sessions'], { id: 'grp-sessions' }),
        model.group(['workspace'], { id: 'grp-main' }),
        model.split(
          'column',
          [model.group(['files'], { id: 'grp-files' }), model.group(['terminal'], { id: 'grp-terminal' })],
          [1.6, 1],
          'spl-right'
        )
      ],
      [1, 3.4, 1.25],
      'spl-root'
    )

    const codingTree = model.split(
      'row',
      [
        model.split(
          'column',
          [model.group(['files'], { id: 'grp-files' }), model.group(['review'], { id: 'grp-review' })],
          [2, 1],
          'spl-coding-left'
        ),
        model.split(
          'row',
          [
            model.split(
              'column',
              [
                model.group([tree.EDITOR_PANE_ID], { id: 'grp-editor' }),
                model.group(['terminal'], { id: 'grp-terminal' })
              ],
              [2.2, 1],
              'spl-coding-center'
            ),
            model.group(['workspace'], { id: 'grp-main' })
          ],
          [2.4, 1.4],
          'spl-coding-main'
        ),
        model.group(['sessions'], { id: 'grp-sessions' })
      ],
      [1, 4.4, 1],
      'spl-coding-root'
    )

    tree.declareDefaultTree(defaultTree)

    return { codingTree, defaultTree, model, registry, tree }
  }

  it('keeps the editor slot when the terminal is dismissed', async () => {
    const { codingTree, model, tree } = await setup()

    tree.applyTree(codingTree, 'coding')
    tree.dismissTreePane('terminal')

    const root = tree.$layoutTree.get()!

    expect(model.allPaneIds(root)).toContain(tree.EDITOR_PANE_ID)
    expect(model.allPaneIds(root)).toContain('workspace')
    expect(model.allPaneIds(root)).not.toContain('terminal')
    expect(model.findGroupOfPane(root, tree.EDITOR_PANE_ID)?.minimized).toBeFalsy()
    expect(tree.treeSideOfPane(tree.EDITOR_PANE_ID)).toBeNull()
  })

  it('collapsing the terminal zone does not minimize the editor', async () => {
    const { codingTree, model, tree } = await setup()

    tree.applyTree(codingTree, 'coding')
    tree.setPaneCollapsed('terminal', true)

    const root = tree.$layoutTree.get()!

    expect(model.findGroupOfPane(root, 'terminal')?.minimized).toBe(true)
    expect(model.findGroupOfPane(root, tree.EDITOR_PANE_ID)?.minimized).toBeFalsy()
    expect(model.findGroupOfPane(root, tree.EDITOR_PANE_ID)?.id).not.toBe(model.findGroupOfPane(root, 'terminal')?.id)
  })

  it('does not adopt the editor slot into Default', async () => {
    const { codingTree, defaultTree, model, tree } = await setup()

    tree.applyTree(codingTree, 'coding')
    expect(model.allPaneIds(tree.$layoutTree.get()!)).toContain(tree.EDITOR_PANE_ID)

    tree.applyTree(defaultTree, 'default')
    expect(model.allPaneIds(tree.$layoutTree.get()!)).not.toContain(tree.EDITOR_PANE_ID)
  })

  it('rehomes preview tiles into the editor slot when applying Coding', async () => {
    const { codingTree, defaultTree, model, registry, tree } = await setup()

    tree.declareDefaultTree(defaultTree)
    registry.register({
      id: 'preview-tile:file:/tmp/a.ts',
      area: 'panes',
      title: 'a.ts',
      data: { dock: { pane: 'workspace', pos: 'right' }, placement: 'main' },
      render: () => null
    })
    tree.watchContributedPanes()

    expect(model.findGroupOfPane(tree.$layoutTree.get()!, 'preview-tile:file:/tmp/a.ts')).toBeTruthy()
    expect(model.findGroupOfPane(tree.$layoutTree.get()!, tree.EDITOR_PANE_ID)).toBeNull()

    tree.applyTree(codingTree, 'coding')

    const editorGroup = model.findGroupOfPane(tree.$layoutTree.get()!, tree.EDITOR_PANE_ID)

    expect(editorGroup?.panes).toContain('preview-tile:file:/tmp/a.ts')
    expect(editorGroup?.panes).toContain(tree.EDITOR_PANE_ID)
  })

  it('does not live-adopt the editor into a tree that does not name it', async () => {
    const { defaultTree, model, tree } = await setup()

    tree.declareDefaultTree(defaultTree)
    tree.watchContributedPanes()

    expect(model.allPaneIds(tree.$layoutTree.get()!)).not.toContain(tree.EDITOR_PANE_ID)
  })
})
