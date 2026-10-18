import { describe, expect, it, vi } from 'vitest'
import { BoxGeometry, Group, Mesh, MeshBasicMaterial } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { FISHBOT_PREVIEW_URDF, SCENE_ASSET_BYTES } from './scene-contract'
import { disposeSceneObject, parseSceneModel, parseScenePcd } from './scene-loaders'

const bytes = (value: string) => new TextEncoder().encode(value).buffer
function pcd(count: number, payload: string, encoding = 'ascii') {
  return bytes(`VERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH ${count}\nHEIGHT 1\nPOINTS ${count}\nDATA ${encoding}\n${payload}`)
}
function triangleGlb() {
  const positions = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0])
  const json = JSON.stringify({ asset: { version: '2.0' }, buffers: [{ byteLength: positions.byteLength }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: positions.byteLength }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 3, type: 'VEC3', min: [0, 0, 0], max: [1, 1, 0] }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0 } }] }], nodes: [{ mesh: 0 }], scenes: [{ nodes: [0] }], scene: 0 })
  const encoded = new TextEncoder().encode(json.padEnd(Math.ceil(json.length / 4) * 4, ' '))
  const buffer = new ArrayBuffer(12 + 8 + encoded.length + 8 + positions.byteLength), header = new DataView(buffer)
  header.setUint32(0, 0x46546c67, true); header.setUint32(4, 2, true); header.setUint32(8, buffer.byteLength, true)
  header.setUint32(12, encoded.length, true); header.setUint32(16, 0x4e4f534a, true); new Uint8Array(buffer, 20, encoded.length).set(encoded)
  header.setUint32(20 + encoded.length, positions.byteLength, true); header.setUint32(24 + encoded.length, 0x004e4942, true)
  new Uint8Array(buffer, 28 + encoded.length).set(new Uint8Array(positions.buffer))
  return buffer
}
describe('official bounded scene loaders', () => {
  it('decodes real PCD coordinates through the official loader', () => {
    const result = parseScenePcd(pcd(2, '1 2 3\n-1 -2 -3\n'))
    expect([...result.positions]).toEqual([1, 2, 3, -1, -2, -3]); expect(result.kind).toBe('pcd_file')
    expect(result.sourceStamp).toBeNull(); expect(result.frameId).toContain('未声明')
  })
  it('bounds PCD output and rejects invalid, oversized, missing, or deceptive count declarations', () => {
    const result = parseScenePcd(pcd(5000, Array.from({ length: 5000 }, (_, i) => `${i} 0 0`).join('\n') + '\n'))
    expect(result.pointCount).toBeLessThanOrEqual(4096)
    expect(() => parseScenePcd(pcd(2, 'NaN 0 0\n0 0 0\n'))).toThrow('无效')
    expect(() => parseScenePcd(pcd(100001, ''))).toThrow('100000')
    expect(() => parseScenePcd(pcd(2, '1 2 3\n'))).toThrow('不一致')
    expect(() => parseScenePcd(new ArrayBuffer(SCENE_ASSET_BYTES + 1))).toThrow('8 MiB')
  })
  it('rejects compressed allocation bombs before the official decompressor runs', () => {
    const prefix = pcd(1, '', 'binary_compressed'), combined = new Uint8Array(prefix.byteLength + 8)
    combined.set(new Uint8Array(prefix)); new DataView(combined.buffer).setUint32(prefix.byteLength + 4, 0x7fffffff, true)
    expect(() => parseScenePcd(combined.buffer)).toThrow('压缩块')
  })
  it('loads a real embedded triangle GLB via GLTFLoader without requesting external resources', async () => {
    const root = await parseSceneModel('glb', triangleGlb())
    expect(root.children[0]).toBeInstanceOf(Mesh); expect((root.children[0] as Mesh).geometry.getAttribute('position').count).toBe(3)
    disposeSceneObject(root)
  })
  it('explicitly refuses external meshes, URLs, broken GLB lengths, and empty input', async () => {
    await expect(parseSceneModel('urdf', bytes('<robot><link><visual><geometry><mesh filename="http://example.test/a.stl"/></geometry></visual></link></robot>'))).rejects.toThrow('资产清单')
    await expect(parseSceneModel('gltf', bytes(JSON.stringify({ asset: { version: '2.0' }, buffers: [{ uri: 'https://example.test/b.bin', byteLength: 10 }] })))).rejects.toThrow('内嵌')
    await expect(parseSceneModel('gltf', bytes('{'))).rejects.toThrow()
    const bad = triangleGlb(); new DataView(bad).setUint32(8, 1, true)
    await expect(parseSceneModel('glb', bad)).rejects.toThrow('长度')
    await expect(parseSceneModel('urdf', new ArrayBuffer(0))).rejects.toThrow('为空')
  })
  it('rejects URDF texture requests and GLTF image decoding before official loaders can allocate pixels or fetch', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch')
    try {
      await expect(parseSceneModel('urdf', bytes('<robot name="test"><material name="image"><texture filename="https://example.test/a.png"/></material><link name="base"/></robot>'))).rejects.toThrow('不加载 URDF 纹理')
      await expect(parseSceneModel('urdf', bytes('<robot name="test"><material name="image"><texture filename="data:image/png;base64,AAAA"/></material><link name="base"/></robot>'))).rejects.toThrow('不加载 URDF 纹理')
      await expect(parseSceneModel('gltf', bytes(JSON.stringify({ asset: { version: '2.0' }, images: [{ uri: 'data:image/png;base64,AAAA' }] })))).rejects.toThrow('像素预算')
      await expect(parseSceneModel('gltf', bytes(JSON.stringify({ asset: { version: '2.0' }, images: [{ bufferView: 0, mimeType: 'image/png' }] })))).rejects.toThrow('像素预算')
      expect(fetcher).not.toHaveBeenCalled()
    } finally { fetcher.mockRestore() }
  })
  it('rejects many small URDF primitives and materials before XML or native geometry allocation', async () => {
    // A stage marker prevents this regression test from allocating a DOM or
    // native geometry even if a malicious structure bypasses its budget.
    const xml = vi.fn(() => { throw new Error('XML parser stage marker') })
    vi.stubGlobal('DOMParser', xml)
    try {
      const fixtures = [
        `<robot name="bounded"><link name="base">${'<visual/>'.repeat(129)}</link></robot>`,
        `<robot name="bounded"><link name="base"><visual>${'<geometry><sphere radius="1"/></geometry>'.repeat(129)}</visual></link></robot>`,
        `<robot name="bounded">${'<material name="m"/>'.repeat(257)}<link name="base"/></robot>`,
        `<robot name="bounded"><link name="base"/>${'<extra/>'.repeat(4096)}</robot>`,
      ]
      for (const source of fixtures) {
        expect(bytes(source).byteLength).toBeLessThan(65536)
        await expect(parseSceneModel('urdf', bytes(source))).rejects.toThrow('URDF 结构超过')
      }
      expect(xml).not.toHaveBeenCalled()
      await expect(parseSceneModel('urdf', bytes(FISHBOT_PREVIEW_URDF))).rejects.toThrow('XML parser stage marker')
      expect(xml).toHaveBeenCalledOnce()
    } finally { vi.unstubAllGlobals() }
  })
  it('rejects tiny GLTF accessor allocation declarations before invoking the official parser', async () => {
    // The parser is stubbed only in this rejection test: a regression cannot
    // accidentally allocate the billion-element array used by the declaration.
    const parser = vi.spyOn(GLTFLoader.prototype, 'parseAsync').mockRejectedValue(new Error('Unsafe parser reached'))
    try {
      const envelope = (accessors: unknown) => bytes(JSON.stringify({ asset: { version: '2.0' }, accessors }))
      for (const accessor of [
        { count: 1e9, componentType: 5126, type: 'VEC3' },
        { count: 1e9, componentType: 5126, type: 'VEC3', bufferView: 0 },
        { count: '1000000000', componentType: 5126, type: 'VEC3' },
        { count: -1, componentType: 5126, type: 'VEC3' },
        { count: 3, componentType: 5126, type: 'constructor' },
      ]) {
        const source = envelope([accessor]); expect(source.byteLength).toBeLessThan(256)
        await expect(parseSceneModel('gltf', source)).rejects.toThrow('属性声明')
      }
      await expect(parseSceneModel('gltf', envelope([{ count: 250000, componentType: 5126, type: 'MAT4' }]))).rejects.toThrow('8 MiB')
      await expect(parseSceneModel('gltf', envelope(Array.from({ length: 4 }, () => ({ count: 200000, componentType: 5126, type: 'VEC3' }))))).rejects.toThrow('8 MiB')
      await expect(parseSceneModel('gltf', envelope({ count: 1 }))).rejects.toThrow('属性声明')
      expect(parser).not.toHaveBeenCalled()
    } finally { parser.mockRestore() }
  })
  it('disposes shared geometries and materials once and detaches the object', () => {
    const geometry = new BoxGeometry(), material = new MeshBasicMaterial(), g = vi.spyOn(geometry, 'dispose'), m = vi.spyOn(material, 'dispose')
    const root = new Group(), parent = new Group(); root.add(new Mesh(geometry, material), new Mesh(geometry, material)); parent.add(root)
    disposeSceneObject(root); expect(g).toHaveBeenCalledOnce(); expect(m).toHaveBeenCalledOnce(); expect(parent.children).toHaveLength(0)
  })
})
