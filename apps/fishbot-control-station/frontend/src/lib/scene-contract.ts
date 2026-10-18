import type { LaserScanSnapshot, NavigationSnapshot } from '@/types/station'

export const SCENE_POINT_LIMIT = 4096
export const SCENE_PATH_LIMIT = 2000
export const SCENE_ASSET_BYTES = 8 * 1024 * 1024
export type SceneSource = { key: string | null; live: boolean; label: string }
export type ScenePoints = {
  positions: Float32Array
  colors?: Float32Array
  pointCount: number
  offeredCount: number
  frameId: string
  receivedAt: string | null
  sourceStamp: null
  kind: 'laser_scan_2d' | 'pcd_file'
}
export type SceneAssetFormat = 'urdf' | 'gltf' | 'glb' | 'pcd'
export type SceneModelRecord = {
  id: string; label: string; format: 'urdf'; units: 'm'; up: '+Z'; rootFrame: string
  license: string; source: string; available: boolean; capabilities: readonly string[]
  rootTranslationM: readonly number[]; rootRotationXyzw: readonly number[]; jointNames: readonly string[]
}

/** Availability describes bundled assets, not the existence of a simulator model. */
export const SCENE_MODELS: readonly SceneModelRecord[] = Object.freeze([
  Object.freeze({ id: 'fishbot-preview', label: 'FishBot 简化预览', format: 'urdf', units: 'm', up: '+Z',
    rootFrame: 'base_footprint', license: 'Project-authored', source: '本项目自写几何；不复制 FishROS 描述',
    available: true, capabilities: Object.freeze(['primitive_visual', 'localized_pose']),
    rootTranslationM: Object.freeze([0, 0, 0]), rootRotationXyzw: Object.freeze([0, 0, 0, 1]), jointNames: Object.freeze([]) }),
  Object.freeze({ id: 'so101-official', label: 'SO101 官方模型（未打包）', format: 'urdf', units: 'm', up: '+Z',
    rootFrame: 'base_link', license: 'Apache-2.0', source: 'https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation/SO101',
    available: false, capabilities: Object.freeze([]), rootTranslationM: Object.freeze([0, 0, 0]),
    rootRotationXyzw: Object.freeze([0, 0, 0, 1]), jointNames: Object.freeze(['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper']) }),
])

/** Original low-detail drawing only. This is neither collision geometry nor a physics model. */
export const FISHBOT_PREVIEW_URDF = `<?xml version="1.0"?>
<robot name="fishbot_project_preview">
  <material name="body"><color rgba="0.15 0.36 0.68 1"/></material>
  <material name="wheel"><color rgba="0.12 0.16 0.22 1"/></material>
  <material name="heading"><color rgba="1 0.63 0.16 1"/></material>
  <link name="base_footprint"/>
  <link name="preview_body"><visual><geometry><box size="0.20 0.17 0.09"/></geometry><material name="body"/></visual></link>
  <joint name="preview_body_mount" type="fixed"><parent link="base_footprint"/><child link="preview_body"/><origin xyz="0 0 0.09"/></joint>
  <link name="preview_heading"><visual><geometry><box size="0.055 0.07 0.015"/></geometry><material name="heading"/></visual></link>
  <joint name="preview_heading_mount" type="fixed"><parent link="preview_body"/><child link="preview_heading"/><origin xyz="0.09 0 0.055"/></joint>
  <link name="preview_left_wheel"><visual><origin rpy="1.57079632679 0 0"/><geometry><cylinder radius="0.035" length="0.025"/></geometry><material name="wheel"/></visual></link>
  <joint name="preview_left_mount" type="fixed"><parent link="base_footprint"/><child link="preview_left_wheel"/><origin xyz="0 0.10 0.035"/></joint>
  <link name="preview_right_wheel"><visual><origin rpy="1.57079632679 0 0"/><geometry><cylinder radius="0.035" length="0.025"/></geometry><material name="wheel"/></visual></link>
  <joint name="preview_right_mount" type="fixed"><parent link="base_footprint"/><child link="preview_right_wheel"/><origin xyz="0 -0.10 0.035"/></joint>
</robot>`

function finite(value: number): boolean { return Number.isFinite(value) && Math.abs(value) <= 1e6 }

/** Preserve the actual scan frame. Missing laser->base TF is never guessed. */
export function sceneScanPoints(scan: LaserScanSnapshot): ScenePoints {
  if (!scan.ready || !scan.frameId || scan.frameId.length > 256) throw new Error('激光帧身份或数据未就绪。')
  if (!Array.isArray(scan.samplePoints) || !scan.samplePoints.length || scan.samplePoints.length > 65536) throw new Error('激光输入为空或超过点数上限。')
  if (!scan.samplePoints.every((p) => finite(p.x) && finite(p.y))) throw new Error('激光坐标含无效值。')
  const stride = Math.max(1, Math.ceil(scan.samplePoints.length / SCENE_POINT_LIMIT))
  const count = Math.ceil(scan.samplePoints.length / stride)
  const positions = new Float32Array(count * 3)
  for (let i = 0, j = 0; i < scan.samplePoints.length; i += stride, j += 3) {
    positions[j] = scan.samplePoints[i].x; positions[j + 1] = scan.samplePoints[i].y
  }
  return { positions, pointCount: count, offeredCount: scan.samplePoints.length, frameId: scan.frameId,
    receivedAt: scan.lastUpdate || null, sourceStamp: null, kind: 'laser_scan_2d' }
}

export function sceneMapPath(navigation: NavigationSnapshot): Float32Array {
  const path = navigation.path
  if (!path?.ready || path.frameId !== 'map') return new Float32Array()
  if (!Array.isArray(path.points) || path.points.length > 65536 || !path.points.every((p) => finite(p.x) && finite(p.y))) {
    throw new Error('路径坐标无效或超过点数上限。')
  }
  const count = Math.min(path.points.length, SCENE_PATH_LIMIT)
  const indices = Array.from({ length: count }, (_, i) => count <= 1 ? 0 : Math.floor(i * (path.points.length - 1) / (count - 1)))
  const positions = new Float32Array(indices.length * 3)
  indices.forEach((index, i) => { positions[i * 3] = path.points[index].x; positions[i * 3 + 1] = path.points[index].y; positions[i * 3 + 2] = .015 })
  return positions
}

export function sceneMapPose(navigation: NavigationSnapshot): { x: number; y: number; yaw: number } | null {
  const p = navigation.localization
  if (!p.ready || ![p.x, p.y, p.yaw].every(finite)) return null
  return { x: p.x, y: p.y, yaw: p.yaw }
}

export function sceneAssetFormat(name: string): SceneAssetFormat {
  const format = name.toLowerCase().split('.').pop()
  if (format !== 'urdf' && format !== 'gltf' && format !== 'glb' && format !== 'pcd') throw new Error('请选择 URDF、GLTF、GLB 或 PCD 文件。')
  return format
}
