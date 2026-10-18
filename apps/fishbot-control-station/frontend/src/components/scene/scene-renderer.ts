import { AmbientLight, AxesHelper, Box3, BufferAttribute, BufferGeometry, Color, DirectionalLight,
  GridHelper, Group, Line, LineBasicMaterial, Object3D, PerspectiveCamera, Points, PointsMaterial,
  Scene, Vector3, WebGLRenderer } from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { disposeSceneObject } from '@/lib/scene-loaders'
import type { ScenePoints } from '@/lib/scene-contract'

export type SceneViewMode = 'map' | 'scan' | 'asset'
export type SceneRenderData = { mode: SceneViewMode; path: Float32Array; pose: { x: number; y: number; yaw: number } | null; points: ScenePoints | null }
export type SceneStartupTiming = { firstDrawMs: number | null; firstModelDrawMs: number | null }

/** ROS map is right-handed, metres and Z-up. Never apply the SVG Y-down heading flip. */
export function applyScenePose(object: Object3D, pose: SceneRenderData['pose']): void {
  object.visible = pose !== null
  if (pose) { object.position.set(pose.x, pose.y, 0); object.rotation.set(0, 0, pose.yaw) }
}

/** On-demand WebGL only. No state polling, task owner, action client or retrying commands. */
export class SceneRenderer {
  private host: HTMLElement
  private renderer: WebGLRenderer
  private scene = new Scene()
  private camera = new PerspectiveCamera(48, 1, .01, 10000000)
  private controls: OrbitControls
  private content = new Group()
  private model: Object3D | null = null
  private asset: Object3D | null = null
  private points: Points<BufferGeometry, PointsMaterial> | null = null
  private path: Line<BufferGeometry, LineBasicMaterial> | null = null
  private resize: ResizeObserver
  private animation: number | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private lastDraw = -Infinity
  private disposed = false
  private lost = false
  private mode: SceneViewMode = 'map'
  private renderCount = 0
  private requestedAt: number
  private firstDrawMs: number | null = null
  private firstModelDrawMs: number | null = null
  private onFirstDraw: (value: SceneStartupTiming) => void
  private onLost: () => void
  private onRestored: () => void

  constructor(host: HTMLElement, onLost: () => void, onRestored: () => void,
    onFirstDraw: (value: SceneStartupTiming) => void = () => {}, requestedAt = performance.now()) {
    this.host = host; this.onLost = onLost; this.onRestored = onRestored
    this.requestedAt = requestedAt; this.onFirstDraw = onFirstDraw
    if (typeof ResizeObserver === 'undefined') throw new Error('浏览器缺少 ResizeObserver。')
    const renderer = new WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'low-power' })
    this.renderer = renderer
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.domElement.setAttribute('aria-label', '三维只读视图；拖动旋转，滚轮缩放')
    renderer.domElement.setAttribute('role', 'img')
    host.append(renderer.domElement)
    renderer.domElement.addEventListener('webglcontextlost', this.contextLost)
    renderer.domElement.addEventListener('webglcontextrestored', this.contextRestored)
    this.scene.background = new Color('#f0f4f8')
    this.scene.add(new AmbientLight(0xffffff, 2))
    const light = new DirectionalLight(0xffffff, 2); light.position.set(4, -3, 8); this.scene.add(light)
    const grid = new GridHelper(20, 40, 0xa9b8ca, 0xd6dfe9); grid.rotation.x = Math.PI / 2; grid.position.z = -.01
    this.scene.add(grid, new AxesHelper(.5), this.content)
    this.camera.up.set(0, 0, 1); this.camera.position.set(2, -3, 3)
    this.controls = new OrbitControls(this.camera, renderer.domElement)
    this.controls.enableDamping = false; this.controls.target.set(0, 0, 0)
    this.controls.addEventListener('change', this.invalidate)
    this.resize = new ResizeObserver(this.measure); this.resize.observe(host)
    this.measure()
  }
  private measure = () => {
    if (this.disposed || this.lost) return
    const width = Math.max(1, this.host.clientWidth), height = Math.max(1, this.host.clientHeight)
    this.camera.aspect = width / height; this.camera.updateProjectionMatrix()
    this.renderer.setSize(width, height); this.invalidate()
  }
  private contextLost = (event: Event) => {
    event.preventDefault(); this.lost = true
    if (this.animation !== null) cancelAnimationFrame(this.animation)
    if (this.timer !== null) clearTimeout(this.timer)
    this.animation = null; this.timer = null; this.metrics(); this.onLost()
  }
  private contextRestored = () => { if (!this.disposed) this.onRestored() }
  private invalidate = () => {
    if (this.disposed || this.lost || this.animation !== null || this.timer !== null) return
    this.timer = setTimeout(() => {
      this.timer = null
      this.animation = requestAnimationFrame(() => {
        this.animation = null
        if (!this.disposed && !this.lost) {
          this.renderer.render(this.scene, this.camera); this.lastDraw = performance.now(); ++this.renderCount
          let changed = false
          if (this.firstDrawMs === null) { this.firstDrawMs = this.lastDraw - this.requestedAt; changed = true }
          if (this.firstModelDrawMs === null && this.model?.visible && this.mode === 'map') { this.firstModelDrawMs = this.lastDraw - this.requestedAt; changed = true }
          if (changed) this.onFirstDraw({ firstDrawMs: this.firstDrawMs, firstModelDrawMs: this.firstModelDrawMs })
          this.metrics()
        }
      })
    }, Math.max(0, 50 - (performance.now() - this.lastDraw)))
    this.metrics()
  }
  setModel(model: Object3D): void { if (this.model) disposeSceneObject(this.model); this.model = model; this.content.add(model); this.invalidate() }
  setAsset(asset: Object3D | null): void {
    if (this.asset && this.asset !== asset) disposeSceneObject(this.asset)
    this.asset = asset
    if (asset) this.content.add(asset)
    this.invalidate()
  }
  update(data: SceneRenderData): void {
    if (this.disposed) return
    const changedMode = this.mode !== data.mode
    this.mode = data.mode
    if (this.model) { applyScenePose(this.model, data.pose); this.model.visible = data.mode === 'map' && !!data.pose }
    if (this.asset) this.asset.visible = data.mode === 'asset'
    // Keep materials alive across frames and modes. Disposing the last material
    // also releases its WebGL program and makes the next frame compile again.
    const showPoints = !!data.points && (data.mode === 'scan' || (data.mode === 'asset' && data.points.kind === 'pcd_file'))
    if (showPoints && data.points) {
      if (!this.points) {
        this.points = new Points(new BufferGeometry(), new PointsMaterial({ size: .045, color: 0x157ab5, sizeAttenuation: true }))
        this.content.add(this.points)
      }
      const colors = data.points.colors
      this.updateGeometry(this.points.geometry, data.points.positions, colors)
      const vertexColors = !!colors
      if (this.points.material.vertexColors !== vertexColors) {
        this.points.material.vertexColors = vertexColors; this.points.material.needsUpdate = true
      }
      this.points.material.color.setHex(vertexColors ? 0xffffff : 0x157ab5)
    }
    if (this.points) this.points.visible = showPoints
    const showPath = data.mode === 'map' && data.path.length >= 6
    if (showPath) {
      if (!this.path) {
        this.path = new Line(new BufferGeometry(), new LineBasicMaterial({ color: 0xd88916 }))
        this.content.add(this.path)
      }
      this.updateGeometry(this.path.geometry, data.path)
    }
    if (this.path) this.path.visible = showPath
    if (changedMode) this.fit()
    this.invalidate(); this.metrics()
  }
  private updateGeometry(geometry: BufferGeometry, positions: Float32Array, colors?: Float32Array): void {
    const values = { position: positions, ...(colors ? { color: colors } : {}) }
    // Three cannot resize GPU attributes. Release the old GPU buffers before a
    // rare size/color-layout change, while retaining this object's material and
    // shader program. Same-layout live frames only upload changed coordinates.
    if (Object.entries(geometry.attributes).some(([name, attribute]) =>
      !(name in values) || attribute.array.length !== values[name as keyof typeof values]?.length)) geometry.dispose()
    for (const [name, array] of Object.entries(values)) {
      const existing = geometry.getAttribute(name)
      if (existing instanceof BufferAttribute && existing.array.length === array.length) {
        existing.array.set(array); existing.needsUpdate = true
      } else geometry.setAttribute(name, new BufferAttribute(array.slice(), 3))
    }
    if (!colors) geometry.deleteAttribute('color')
    // Live coordinates invalidate both the render culling and fit-view bounds.
    geometry.boundingSphere = null; geometry.boundingBox = null
  }
  fit(): void {
    const box = new Box3()
    for (const object of [this.model, this.asset, this.points, this.path]) if (object?.visible) box.expandByObject(object)
    const center = box.isEmpty() ? new Vector3() : box.getCenter(new Vector3())
    const extent = box.isEmpty() ? 2 : Math.max(.25, box.getSize(new Vector3()).length())
    this.controls.target.copy(center); this.camera.position.copy(center).add(new Vector3(extent, -extent * 1.3, extent))
    this.controls.update(); this.invalidate()
  }
  /** DOM metrics are local rendering diagnostics, never a ROS consumption receipt. */
  metrics() {
    const value = { renderCount: this.renderCount, scheduled: this.animation !== null || this.timer !== null, disposed: this.disposed,
      contextLost: this.lost, points: this.points?.visible ? this.points.geometry.getAttribute('position')?.count ?? 0 : 0,
      firstDrawMs: this.firstDrawMs, firstModelDrawMs: this.firstModelDrawMs,
      pathPoints: this.path?.visible ? this.path.geometry.getAttribute('position')?.count ?? 0 : 0,
      geometries: this.renderer.info.memory.geometries, textures: this.renderer.info.memory.textures }
    for (const [key, item] of Object.entries(value)) this.host.dataset[`scene${key[0].toUpperCase()}${key.slice(1)}`] = String(item)
    return value
  }
  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    if (this.animation !== null) cancelAnimationFrame(this.animation)
    if (this.timer !== null) clearTimeout(this.timer)
    this.resize.disconnect(); this.controls.dispose()
    this.renderer.domElement.removeEventListener('webglcontextlost', this.contextLost)
    this.renderer.domElement.removeEventListener('webglcontextrestored', this.contextRestored)
    disposeSceneObject(this.scene); this.scene.clear(); this.content.clear()
    this.model = null; this.asset = null; this.points = null; this.path = null
    this.renderer.dispose(); this.renderer.domElement.remove(); this.animation = null; this.timer = null; this.metrics()
  }
}
