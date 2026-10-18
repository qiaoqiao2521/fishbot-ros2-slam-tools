import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoxGeometry, Group, Line, Mesh, MeshBasicMaterial, Points, type Material, type Scene } from 'three'
import { applyScenePose, SceneRenderer } from './scene-renderer'

const calls = vi.hoisted(() => ({ draw: vi.fn(), dispose: vi.fn(), controlsDispose: vi.fn(), canvases: [] as EventTarget[] }))
vi.mock('three', async (original) => {
  const actual = await original<typeof import('three')>()
  return { ...actual, WebGLRenderer: class {
    domElement = Object.assign(new EventTarget(), { setAttribute: vi.fn(), remove: vi.fn() })
    info = { memory: { geometries: 0, textures: 0 } }
    constructor() { calls.canvases.push(this.domElement) }
    setPixelRatio() {} setSize() {} render = calls.draw; dispose = calls.dispose
  } }
})
vi.mock('three/addons/controls/OrbitControls.js', async () => {
  const { Vector3 } = await import('three')
  return { OrbitControls: class { target = new Vector3(); enableDamping = false; addEventListener() {} update() {} dispose = calls.controlsDispose } }
})
beforeEach(() => {
  vi.useFakeTimers(); calls.draw.mockClear(); calls.dispose.mockClear(); calls.controlsDispose.mockClear(); calls.canvases.length = 0
  vi.stubGlobal('window', { devicePixelRatio: 1 })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 0))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
const host = () => ({ append: vi.fn(), clientWidth: 800, clientHeight: 500, dataset: {} }) as unknown as HTMLElement

describe('render-only WebGL lifecycle (GPU adapter isolated)', () => {
  it('uses ROS Z-up heading directly and hides unavailable localization', () => {
    const object = new Group(); applyScenePose(object, { x: 2, y: -3, yaw: Math.PI / 2 })
    expect(object.position.toArray()).toEqual([2, -3, 0]); expect(object.rotation.z).toBeCloseTo(Math.PI / 2)
    applyScenePose(object, null); expect(object.visible).toBe(false)
  })
  it('coalesces render requests, exposes bounded diagnostics and releases all view resources', () => {
    const target = host(), renderer = new SceneRenderer(target, vi.fn(), vi.fn())
    const model = new Group(); model.add(new Mesh(new BoxGeometry(), new MeshBasicMaterial())); renderer.setModel(model)
    const update = { mode: 'scan' as const, pose: null, path: new Float32Array(),
      points: { positions: new Float32Array([1, 2, 0]), pointCount: 1, offeredCount: 1, kind: 'laser_scan_2d' as const, frameId: 'laser_link', receivedAt: null, sourceStamp: null } }
    renderer.update(update); renderer.update(update); renderer.update(update)
    expect(renderer.metrics()).toMatchObject({ scheduled: true, points: 1, disposed: false })
    vi.advanceTimersByTime(2); expect(calls.draw).toHaveBeenCalledOnce()
    expect(target.dataset.sceneRenderCount).toBe('1')
    renderer.dispose(); renderer.dispose(); vi.runAllTimers()
    expect(calls.dispose).toHaveBeenCalledOnce(); expect(calls.controlsDispose).toHaveBeenCalledOnce()
    expect(renderer.metrics()).toMatchObject({ disposed: true, scheduled: false }); expect(calls.draw).toHaveBeenCalledOnce()
  })
  it('updates moving scan buffers without releasing materials or retaining stale culling bounds', () => {
    const renderer = new SceneRenderer(host(), vi.fn(), vi.fn())
    const scan = (positions: number[]) => ({ mode: 'scan' as const, pose: null, path: new Float32Array(),
      points: { positions: new Float32Array(positions), pointCount: positions.length / 3, offeredCount: positions.length / 3,
        kind: 'laser_scan_2d' as const, frameId: 'laser_link', receivedAt: null, sourceStamp: null } })
    renderer.update(scan([1, 2, 0])); vi.advanceTimersByTime(2)
    const scene = calls.draw.mock.calls[0][0] as Scene
    let points: Points | undefined
    scene.traverse(object => { if (object instanceof Points) points = object })
    expect(points).toBeDefined()
    const object = points!, geometry = object.geometry, material = object.material, position = geometry.getAttribute('position')
    const geometryDispose = vi.spyOn(geometry, 'dispose'), materialDispose = vi.spyOn(material as Material, 'dispose')
    geometry.computeBoundingSphere(); geometry.computeBoundingBox()
    renderer.update(scan([21, 22, 0]))
    expect(object.geometry).toBe(geometry); expect(object.material).toBe(material)
    expect(geometry.getAttribute('position')).toBe(position)
    expect(Array.from(position.array)).toEqual([21, 22, 0])
    expect(geometry.boundingSphere).toBeNull(); expect(geometry.boundingBox).toBeNull()
    renderer.update({ mode: 'map', pose: null, path: new Float32Array(), points: null })
    expect(object.visible).toBe(false); expect(renderer.metrics().points).toBe(0)
    expect(geometryDispose).not.toHaveBeenCalled(); expect(materialDispose).not.toHaveBeenCalled()
    renderer.update(scan([3, 4, 0, 5, 6, 0]))
    expect(object.visible).toBe(true); expect(object.geometry).toBe(geometry); expect(object.material).toBe(material)
    expect(geometry.getAttribute('position').count).toBe(2)
    expect(geometryDispose).toHaveBeenCalledOnce(); expect(materialDispose).not.toHaveBeenCalled()
    renderer.dispose()
    expect(geometryDispose).toHaveBeenCalledTimes(2); expect(materialDispose).toHaveBeenCalledOnce()
  })
  it('keeps one path material across map updates and scan switches, then releases it once', () => {
    const renderer = new SceneRenderer(host(), vi.fn(), vi.fn())
    const update = (path: number[], mode: 'map' | 'scan' = 'map') => renderer.update({ mode, pose: null, points: null, path: new Float32Array(path) })
    update([0, 0, 0, 1, 1, 0]); vi.advanceTimersByTime(2)
    const scene = calls.draw.mock.calls[0][0] as Scene
    let line: Line | undefined
    scene.traverse(object => { if (object.type === 'Line') line = object as Line })
    expect(line).toBeDefined()
    const object = line!, material = object.material, geometry = object.geometry, position = geometry.getAttribute('position')
    const materialDispose = vi.spyOn(material as Material, 'dispose')
    update([2, 3, 0, 4, 5, 0]); expect(geometry.getAttribute('position')).toBe(position)
    expect(Array.from(position.array)).toEqual([2, 3, 0, 4, 5, 0])
    update([], 'scan'); expect(object.visible).toBe(false); expect(renderer.metrics().pathPoints).toBe(0)
    update([0, 0, 0, 1, 1, 0, 2, 2, 0]); expect(object.visible).toBe(true)
    expect(object.material).toBe(material); expect(object.geometry).toBe(geometry)
    expect(geometry.getAttribute('position').count).toBe(3); expect(materialDispose).not.toHaveBeenCalled()
    renderer.dispose(); expect(materialDispose).toHaveBeenCalledOnce()
  })
  it('releases a removed color GPU attribute before detaching it while retaining the point material', () => {
    const renderer = new SceneRenderer(host(), vi.fn(), vi.fn())
    const point = { positions: new Float32Array([1, 2, 0]), colors: new Float32Array([1, 0, 0]),
      pointCount: 1, offeredCount: 1, kind: 'pcd_file' as const, frameId: 'file', receivedAt: null, sourceStamp: null }
    renderer.update({ mode: 'asset', pose: null, points: point, path: new Float32Array() }); vi.advanceTimersByTime(2)
    let points: Points | undefined
    ;(calls.draw.mock.calls[0][0] as Scene).traverse(object => { if (object instanceof Points) points = object })
    const object = points!, material = object.material, geometry = object.geometry
    const releasing = vi.fn(() => expect(geometry.hasAttribute('color')).toBe(true))
    geometry.addEventListener('dispose', releasing)
    renderer.update({ mode: 'asset', pose: null, points: { ...point, colors: undefined }, path: new Float32Array() })
    expect(releasing).toHaveBeenCalledOnce(); geometry.removeEventListener('dispose', releasing)
    expect(geometry.hasAttribute('color')).toBe(false); expect(object.material).toBe(material)
    renderer.dispose()
  })
  it('reports context loss and restore without reconstructing a business owner or drawing lost data', () => {
    const lost = vi.fn(), restored = vi.fn(), renderer = new SceneRenderer(host(), lost, restored)
    calls.canvases[0].dispatchEvent(new Event('webglcontextlost', { cancelable: true })); vi.runAllTimers()
    expect(lost).toHaveBeenCalledOnce(); expect(calls.draw).not.toHaveBeenCalled(); expect(renderer.metrics().contextLost).toBe(true)
    calls.canvases[0].dispatchEvent(new Event('webglcontextrestored')); expect(restored).toHaveBeenCalledOnce()
    renderer.dispose(); calls.canvases[0].dispatchEvent(new Event('webglcontextrestored')); expect(restored).toHaveBeenCalledOnce()
  })
  it('records feedback-independent scene and visible-model first draw times', () => {
    const timing = vi.fn(), requestedAt = performance.now() - 700
    const renderer = new SceneRenderer(host(), vi.fn(), vi.fn(), timing, requestedAt)
    renderer.setModel(new Mesh(new BoxGeometry(), new MeshBasicMaterial()))
    renderer.update({ mode: 'map', pose: { x: 1, y: 2, yaw: 0 }, points: null, path: new Float32Array() })
    expect(timing).not.toHaveBeenCalled(); vi.advanceTimersByTime(2)
    expect(timing).toHaveBeenCalledOnce()
    expect(timing.mock.calls[0][0].firstDrawMs).toBeGreaterThanOrEqual(700)
    expect(timing.mock.calls[0][0].firstModelDrawMs).toBeGreaterThanOrEqual(700)
    renderer.dispose()
  })
})
