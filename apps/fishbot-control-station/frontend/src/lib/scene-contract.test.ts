import { describe, expect, it } from 'vitest'
import { mockPerception, mockNavigation } from '@/lib/mock-station'
import { SCENE_MODELS, SCENE_POINT_LIMIT, sceneScanPoints, sceneMapPath, sceneMapPose, sceneAssetFormat } from './scene-contract'

describe('3D read-only input contract', () => {
  it('keeps the real LaserScan sensor frame and receipt clock without inventing a source timestamp', () => {
    const scan = { ...structuredClone(mockPerception).scan, ready: true, frameId: 'laser_link', lastUpdate: '2026-10-18T10:00:00Z',
      samplePoints: [{ x: 1, y: 2, angleRad: 0, rangeMeters: 3 }] }
    const result = sceneScanPoints(scan)
    expect([...result.positions]).toEqual([1, 2, 0]); expect(result.frameId).toBe('laser_link')
    expect(result.receivedAt).toBe(scan.lastUpdate); expect(result.sourceStamp).toBeNull(); expect(result.kind).toBe('laser_scan_2d')
    expect(scan.samplePoints[0]).toEqual({ x: 1, y: 2, angleRad: 0, rangeMeters: 3 })
  })
  it('bounds displayed points and rejects non-finite or oversized input', () => {
    const scan = { ...structuredClone(mockPerception).scan, ready: true, frameId: 'laser_link',
      samplePoints: Array.from({ length: 10000 }, (_, i) => ({ x: i, y: 0, angleRad: 0, rangeMeters: i })) }
    expect(sceneScanPoints(scan).pointCount).toBeLessThanOrEqual(SCENE_POINT_LIMIT)
    expect(() => sceneScanPoints({ ...scan, samplePoints: [{ ...scan.samplePoints[0], x: NaN }] })).toThrow('无效')
    expect(() => sceneScanPoints({ ...scan, samplePoints: Array(65537).fill(scan.samplePoints[0]) })).toThrow('上限')
  })
  it('requires a map-frame path and actual localization; never replaces missing AMCL with odometry', () => {
    const navigation = structuredClone(mockNavigation)
    navigation.path = { ready: true, frameId: 'map', points: [{ x: 2, y: -1 }, { x: 3, y: 2 }], poseCount: 2, lastUpdate: null, statusMessage: '' }
    expect([...sceneMapPath(navigation)]).toEqual([2, -1, expect.closeTo(.015), 3, 2, expect.closeTo(.015)])
    expect(sceneMapPath({ ...navigation, path: { ...navigation.path, frameId: 'odom' } })).toHaveLength(0)
    expect(sceneMapPose({ ...navigation, localization: { ...navigation.localization, ready: false } })).toBeNull()
    expect(sceneMapPose({ ...navigation, localization: { ...navigation.localization, ready: true, x: 1, y: 2, yaw: .4 } })).toEqual({ x: 1, y: 2, yaw: .4 })
  })
  it('keeps path endpoints while bounding large observations, and rejects invalid paths', () => {
    const navigation = structuredClone(mockNavigation)
    navigation.path = { ready: true, frameId: 'map', points: Array.from({ length: 5000 }, (_, i) => ({ x: i, y: 0 })), poseCount: 5000, lastUpdate: null, statusMessage: '' }
    const p = sceneMapPath(navigation)
    expect(p.length / 3).toBeLessThanOrEqual(2000); expect([...p.slice(-3)]).toEqual([4999, 0, expect.closeTo(.015)])
    expect(() => sceneMapPath({ ...navigation, path: { ...navigation.path!, points: [{ x: Infinity, y: 0 }] } })).toThrow('无效')
  })
  it('declares preview geometry and unavailable SO101 honestly', () => {
    expect(SCENE_MODELS.find((m) => m.id === 'fishbot-preview')).toMatchObject({ available: true, license: 'Project-authored', units: 'm', up: '+Z' })
    expect(SCENE_MODELS.find((m) => m.id === 'so101-official')).toMatchObject({ available: false, license: 'Apache-2.0', capabilities: [] })
    expect(sceneAssetFormat('robot.GLB')).toBe('glb'); expect(() => sceneAssetFormat('robot.zip')).toThrow('请选择')
  })
})
