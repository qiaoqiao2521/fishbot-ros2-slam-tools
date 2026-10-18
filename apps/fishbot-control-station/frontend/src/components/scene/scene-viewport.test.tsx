import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockNavigation, mockPerception } from '@/lib/mock-station'
import { SceneViewport } from './scene-viewport'

const hooks = vi.hoisted(() => ({ active: false, cursor: 0, refCursor: 0, values: [] as unknown[],
  refs: [] as Array<{ current: unknown }>, effects: [] as Array<() => (() => void) | undefined>,
  failRenderer: false, setup: null as null | (() => void), cancelled: false }))
vi.mock('react', async (original) => {
  const actual = await original<typeof import('react')>()
  return { ...actual,
    useRef: (current: unknown) => {
      if (!hooks.active) return actual.useRef(current)
      const index = hooks.refCursor++
      return hooks.refs[index] ??= { current }
    },
    useEffect: (effect: () => (() => void) | undefined, dependencies: unknown[]) => {
      if (hooks.active) hooks.effects.push(effect)
      else actual.useEffect(effect, dependencies)
    },
    useState: (initial: unknown) => {
      if (!hooks.active) return actual.useState(initial)
      const index = hooks.cursor++
      if (index >= hooks.values.length) hooks.values[index] = typeof initial === 'function' ? initial() : initial
      return [hooks.values[index], (value: unknown) => {
        hooks.values[index] = typeof value === 'function' ? value(hooks.values[index]) : value
      }]
    },
  }
})
vi.mock('@/lib/scene-setup', () => ({ scheduleSceneSetup: (start: () => void) => {
  hooks.setup = () => { if (!hooks.cancelled) start() }
  return () => { hooks.cancelled = true }
} }))
vi.mock('./scene-renderer', () => ({ SceneRenderer: class {
  constructor() { if (hooks.failRenderer) throw new Error('isolated WebGL creation failure') }
  update() {} fit() {} dispose() {} setModel() {} setAsset() {}
} }))
vi.mock('@/lib/scene-loaders', () => ({ parseSceneModel: async () => ({}), disposeSceneObject() {} }))
afterEach(() => {
  hooks.active = false; hooks.cursor = 0; hooks.refCursor = 0; hooks.values = []; hooks.refs = []; hooks.effects = []
  hooks.failRenderer = false; hooks.setup = null; hooks.cancelled = false
})
const props = { navigation: mockNavigation, scan: mockPerception.scan, source: { key: null, live: false, label: '离线样例' } }
function controlledRender() {
  hooks.cursor = 0; hooks.refCursor = 0; hooks.effects = []
  return renderToStaticMarkup(<SceneViewport {...props} />)
}

describe('3D workbench source labels and first-frame preparation', () => {
  it('starts with a visible preparation stage and source identity before building full controls', () => {
    const html = renderToStaticMarkup(<SceneViewport {...props} />)
    expect(html).toContain('离线样例'); expect(html).toContain('三维只读'); expect(html).toContain('正在准备三维场景')
    expect(html).toContain('aria-busy="true"'); expect(html).toContain('scene-webgl')
    expect(html).not.toContain('scene-tools'); expect(html).not.toContain('任务成功')
  })
  it.each([false, true])('expands complete controls after deferred setup, including renderer failure=%s', (failRenderer) => {
    hooks.active = true; hooks.failRenderer = failRenderer
    expect(controlledRender()).not.toContain('scene-tools')
    // SSR has no DOM commit. Attach only the host ref used by the isolated effect.
    hooks.refs[0].current = { dataset: {} }
    const cleanups = hooks.effects.map(effect => effect())
    expect(controlledRender()).not.toContain('scene-tools')
    expect(hooks.setup).not.toBeNull(); hooks.setup!()
    const html = controlledRender()
    expect(html).toContain('scene-tools'); expect(html).toContain('重建视图')
    expect(html).toContain('SO101 官方模型（未打包）'); expect(html).toContain('简化预览')
    expect(html).toContain('历史或未核实'); expect(html).toContain('无定位时不拿里程计代替')
    expect(html).toContain('aria-busy="false"')
    if (failRenderer) expect(html).toContain('浏览器未能创建 WebGL')
    for (const cleanup of cleanups) cleanup?.()
  })
  it('makes a hidden view explicit without rendering a canvas or claiming a paused task', () => {
    const html = renderToStaticMarkup(<SceneViewport {...props} active={false} />)
    expect(html).toContain('三维渲染已暂停'); expect(html).toContain('原任务继续'); expect(html).not.toContain('scene-webgl')
  })
})
