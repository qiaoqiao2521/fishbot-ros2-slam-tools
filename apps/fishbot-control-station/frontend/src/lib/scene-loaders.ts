import { BufferGeometry, Material, Object3D, Texture } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { PCDLoader } from 'three/addons/loaders/PCDLoader.js'
import URDFLoader from 'urdf-loader'
import { SCENE_ASSET_BYTES, SCENE_POINT_LIMIT, type SceneAssetFormat, type ScenePoints } from './scene-contract'

const textDecoder = new TextDecoder('utf-8', { fatal: true })
function validBytes(bytes: ArrayBuffer): void {
  if (!bytes.byteLength || bytes.byteLength > SCENE_ASSET_BYTES) throw new Error('文件为空或超过 8 MiB 上限。')
}
function finiteGeometry(root: Object3D): void {
  let vertices = 0
  root.traverse((object) => {
    const geometry = (object as Object3D & { geometry?: BufferGeometry }).geometry
    const position = geometry?.getAttribute('position')
    if (!position) return
    vertices += position.count
    if (vertices > 250000) throw new Error('模型超过 25 万顶点上限。')
    for (let i = 0; i < position.array.length; ++i) {
      if (!Number.isFinite(position.array[i]) || Math.abs(Number(position.array[i])) > 1e6) throw new Error('模型含无效坐标。')
    }
  })
  if (!vertices) throw new Error('模型不含可显示的几何。')
}

/** No remote mesh/resource fetch. External multi-file bundles need a future asset manifest. */
function validateGltf(json: unknown): void {
  if (!json || typeof json !== 'object') throw new Error('GLTF JSON 格式错误。')
  const value = json as { buffers?: Array<{ uri?: string; byteLength?: number }>; images?: Array<{ uri?: string }>; extensionsRequired?: string[]; accessors?: unknown }
  if (value.images !== undefined && (!Array.isArray(value.images) || value.images.length > 0)) throw new Error('当前不加载 GLTF 图片或纹理；像素预算尚未配置。')
  if (value.extensionsRequired?.some((name) => /draco|meshopt|basisu/i.test(name))) throw new Error('此压缩扩展尚未配置解码器。')
  // Accessors without a bufferView can allocate a zero-filled array from count
  // alone. Inspect these declarations before the official parser allocates any.
  if (value.accessors !== undefined && (!Array.isArray(value.accessors) || value.accessors.length > 1024)) throw new Error('GLTF 属性声明必须为不超过 1024 项的数组。')
  const widths: Record<string, number> = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT2: 4, MAT3: 9, MAT4: 16 }
  const sizes: Record<number, number> = { 5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4 }
  let declaredBytes = 0
  for (const item of (value.accessors ?? []) as unknown[]) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('GLTF 属性声明格式错误。')
    const accessor = item as { count?: unknown; type?: unknown; componentType?: unknown }
    if (typeof accessor.count !== 'number' || !Number.isSafeInteger(accessor.count) || accessor.count < 1 || accessor.count > 250000
      || typeof accessor.type !== 'string' || !Object.hasOwn(widths, accessor.type)
      || typeof accessor.componentType !== 'number' || !Object.hasOwn(sizes, accessor.componentType)) throw new Error('GLTF 属性声明无效或超过 25 万元素上限。')
    declaredBytes += accessor.count * widths[accessor.type] * sizes[accessor.componentType]
    if (declaredBytes > SCENE_ASSET_BYTES) throw new Error('GLTF 属性声明展开后超过 8 MiB 上限。')
  }
  const resources = [...(value.buffers ?? []), ...(value.images ?? [])]
  for (const resource of resources) {
    if (resource.uri && (!/^data:[a-z0-9/+.-]*;base64,[a-zA-Z0-9+/=\s]*$/.test(resource.uri) || resource.uri.length > SCENE_ASSET_BYTES)) {
      throw new Error('当前只接受内嵌资源；不会请求外部模型、图片或网格。')
    }
  }
  if ((value.buffers ?? []).reduce((sum, b) => sum + (b.byteLength ?? 0), 0) > SCENE_ASSET_BYTES) throw new Error('GLTF 缓冲超过 8 MiB 上限。')
}

/** Count opening markup before either XML DOM or native primitive allocation.
 * This is only a conservative budget guard; DOMParser remains the XML parser.
 */
function boundUrdfMarkup(source: string): void {
  let total = 0
  const count: Record<string, number> = { visual: 0, geometry: 0, material: 0 }
  const limit: Record<string, number> = { visual: 128, geometry: 128, material: 256 }
  const tags = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<([a-z_][\w:.-]*)(?=[\s/>])/gi
  for (const match of source.matchAll(tags)) {
    if (!match[1]) continue
    if (++total > 4096) throw new Error('URDF 结构超过 4096 个元素上限。')
    const tag = match[1].toLowerCase()
    if (Object.hasOwn(count, tag) && ++count[tag] > limit[tag]) throw new Error(`URDF 结构超过 ${limit[tag]} 个 ${tag} 上限。`)
  }
}

export async function parseSceneModel(format: Exclude<SceneAssetFormat, 'pcd'>, bytes: ArrayBuffer): Promise<Object3D> {
  validBytes(bytes)
  let root: Object3D
  if (format === 'urdf') {
    const source = textDecoder.decode(bytes)
    if (/<!DOCTYPE|<!ENTITY/i.test(source) || /<mesh\b/i.test(source)) throw new Error('当前 URDF 仅支持内嵌基础几何；外部网格需要已登记的资产清单。')
    if (/<texture\b/i.test(source)) throw new Error('当前不加载 URDF 纹理；外部资源与像素预算尚未配置。')
    boundUrdfMarkup(source)
    if (typeof DOMParser === 'undefined') throw new Error('URDF 加载需要浏览器 XML 解析器。')
    const xml = new DOMParser().parseFromString(source, 'application/xml')
    if (xml.querySelector('parsererror') || xml.documentElement.tagName !== 'robot') throw new Error('URDF XML 格式错误。')
    if (xml.querySelectorAll('link').length > 128 || xml.querySelectorAll('joint').length > 128) throw new Error('URDF 超过 128 个连杆或关节上限。')
    const loader = new URDFLoader()
    loader.parseCollision = false; loader.parseVisual = true
    loader.loadMeshCb = () => { throw new Error('未登记的外部网格被拒绝。') }
    root = loader.parse(xml)
  } else {
    let source: string | ArrayBuffer = bytes
    if (format === 'gltf') { source = textDecoder.decode(bytes); validateGltf(JSON.parse(source)) }
    else {
      if (bytes.byteLength < 20) throw new Error('GLB 文件头不完整。')
      const data = new DataView(bytes)
      if (data.getUint32(0, true) !== 0x46546c67 || data.getUint32(4, true) !== 2 || data.getUint32(8, true) !== bytes.byteLength
        || data.getUint32(16, true) !== 0x4e4f534a || data.getUint32(12, true) > bytes.byteLength - 20) throw new Error('GLB 文件头或长度错误。')
      validateGltf(JSON.parse(textDecoder.decode(new Uint8Array(bytes, 20, data.getUint32(12, true)))))
    }
    root = (await new GLTFLoader().parseAsync(source, '')).scene
  }
  try { finiteGeometry(root); return root }
  catch (error) { disposeSceneObject(root); throw error }
}

/** Bounds inspection only; the official PCDLoader performs every field/data decode. */
export function parseScenePcd(bytes: ArrayBuffer): ScenePoints {
  validBytes(bytes)
  const prefix = new TextDecoder().decode(new Uint8Array(bytes, 0, Math.min(bytes.byteLength, 8192)))
  const data = /^DATA[ \t]+(ascii|binary|binary_compressed)[ \t]*\r?\n/im.exec(prefix)
  if (!data) throw new Error('PCD 头部缺失、过长或 DATA 编码不受支持。')
  const header = prefix.slice(0, data.index)
  const count = /^POINTS\s+(\d+)\s*$/im.exec(header)
  if (!count || Number(count[1]) < 1 || Number(count[1]) > 100000) throw new Error('PCD 必须声明 1 至 100000 个点。')
  const fields = /^FIELDS\s+(.+)$/im.exec(header)?.[1].trim().split(/\s+/)
  const sizes = /^SIZE\s+(.+)$/im.exec(header)?.[1].trim().split(/\s+/).map(Number)
  const counts = /^COUNT\s+(.+)$/im.exec(header)?.[1].trim().split(/\s+/).map(Number)
  if (!fields || fields.length > 16 || !['x', 'y', 'z'].every((name) => fields.includes(name))
    || !sizes || sizes.length !== fields.length || !sizes.every((size) => [1, 2, 4, 8].includes(size))
    || (counts && (counts.length !== fields.length || !counts.every((n) => n === 1)))) throw new Error('PCD 字段或大小声明无效；当前只支持各字段 COUNT=1。')
  const estimated = Number(count[1]) * sizes.reduce((sum, size, i) => sum + size * (counts?.[i] ?? 1), 0)
  if (estimated > SCENE_ASSET_BYTES) throw new Error('PCD 解压后的字段超过 8 MiB 上限。')
  const headerLength = new TextEncoder().encode(prefix.slice(0, data.index + data[0].length)).byteLength
  if (data[1].toLowerCase() === 'ascii') {
    // Count rows before the official loader allocates position arrays.
    const body = textDecoder.decode(bytes.slice(headerLength))
    if (body.split('\n').filter((line) => line.length > 0).length !== Number(count[1])) throw new Error('PCD 点数与声明不一致。')
  }
  if (data[1].toLowerCase() === 'binary_compressed') {
    if (bytes.byteLength - headerLength < 8) throw new Error('PCD 压缩块长度缺失。')
    const length = new DataView(bytes, headerLength, 8)
    if (length.getUint32(0, true) > bytes.byteLength - headerLength - 8
      || length.getUint32(1 * 4, true) !== estimated) throw new Error('PCD 压缩块声明与预算不一致。')
  }
  const points = new PCDLoader().parse(bytes)
  try {
    const position = points.geometry.getAttribute('position'), color = points.geometry.getAttribute('color')
    if (!position || position.count !== Number(count[1])) throw new Error('PCD 点数与声明不一致。')
    const stride = Math.max(1, Math.ceil(position.count / SCENE_POINT_LIMIT)), rendered = Math.ceil(position.count / stride)
    const positions = new Float32Array(rendered * 3), colors = color ? new Float32Array(rendered * 3) : undefined
    for (let i = 0, out = 0; i < position.count; ++i) {
      const values = [position.getX(i), position.getY(i), position.getZ(i)]
      if (!values.every((n) => Number.isFinite(n) && Math.abs(n) <= 1e6)) throw new Error('PCD 含无效坐标。')
      if (i % stride === 0) {
        positions.set(values, out * 3)
        if (colors && color) {
          const rgb = [color.getX(i), color.getY(i), color.getZ(i)]
          if (!rgb.every((n) => Number.isFinite(n) && n >= 0 && n <= 1)) throw new Error('PCD 含无效颜色。')
          colors.set(rgb, out * 3)
        }
        ++out
      }
    }
    return { positions, ...(colors ? { colors } : {}), pointCount: rendered, offeredCount: position.count,
      frameId: '文件原始坐标（未声明单位或 ROS frame）', receivedAt: null, sourceStamp: null, kind: 'pcd_file' }
  } finally { disposeSceneObject(points) }
}

export function disposeSceneObject(root: Object3D): void {
  const geometries = new Set<BufferGeometry>(), materials = new Set<Material>(), textures = new Set<Texture>()
  root.traverse((object) => {
    const mesh = object as Object3D & { geometry?: BufferGeometry; material?: Material | Material[] }
    if (mesh.geometry) geometries.add(mesh.geometry)
    for (const material of Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []) {
      materials.add(material)
      for (const value of Object.values(material)) if (value instanceof Texture) textures.add(value)
    }
  })
  geometries.forEach((value) => value.dispose()); materials.forEach((value) => value.dispose()); textures.forEach((value) => value.dispose())
  root.removeFromParent()
}
