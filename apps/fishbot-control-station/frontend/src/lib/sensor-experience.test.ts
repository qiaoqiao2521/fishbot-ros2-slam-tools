import { describe, expect, it, vi } from 'vitest'
import { angularPoint, boxAngularEdges, decodeSensorFrame, parseSensorExperience, parseSensorFrame, sameSensorIdentity, sensorFrameAsset, readSensorFrame } from './sensor-experience'
const identity = { scene_sha256: 'scene-ui', manifest_sha256: 'manifest-ui', episode_id: 'episode-ui', sequence: '42' }
describe('same-source sensor evidence', () => {
  it('resolves only same-origin public frame references', () => {
    expect(sensorFrameAsset('frame-0.json', '/workbench/sensor-a/sensor-experience.json')).toBe('/workbench/sensor-a/frame-0.json')
    expect(sensorFrameAsset('../other/frame.json', '/workbench/sensor-a/sensor-experience.json')).toBeNull()
    expect(sensorFrameAsset('https://elsewhere/frame.json', '/workbench/sensor-a/sensor-experience.json')).toBeNull()
  })
  it('keeps source nanoseconds exact instead of rounding them through JavaScript Number', () => {
    const frame = decodeSensorFrame('{"source_stamp_ns":1793936548924879304,"actual_tf":{"source_stamp_ns":1793936548924879304}}')
    expect(frame.sourceNs).toBe('1793936548924879304')
    expect(frame.actualTf?.sourceNs).toBe('1793936548924879304')
    expect(parseSensorFrame({ source_stamp_ns: Number('1793936548924879304') }).sourceNs).toBe('')
  })
  it('requires actual per-frame identities rather than selecting a nearby episode', () => {
    expect(sameSensorIdentity(identity, identity)).toBe(true)
    expect(sameSensorIdentity(identity, { ...identity, episode_id: 'old-episode' })).toBe(false)
    expect(sameSensorIdentity(identity, { ...identity, sequence: '' })).toBe(false)
    const report = parseSensorExperience({ schema: 'fishbot.sensor-experience.v1', read_only: true, new_execution: false, rescored: false, frames: [{ url: 'frame-0.json', identity }], actual_subscribers: [{ node: '/local_costmap/local_costmap', type: 'sensor_msgs/msg/PointCloud2' }] }, '/workbench/sensor-a/sensor-experience.json')
    expect(report.confirmedReadOnly).toBe(true); expect(report.runId).toBe('')
    expect(report.frames[0].identity).toEqual(identity)
  })
  it('projects observed coordinates directly and breaks seam-crossing box edges', () => {
    expect(angularPoint([1, 0, 0])).toEqual([360, 160])
    expect(angularPoint([0, 0, 0])).toBeNull()
    const corners: [number, number, number][] = []
    for (const x of [-2, -1]) for (const y of [-.1, .1]) for (const z of [-.1, .1]) corners.push([x, y, z])
    const lines = boxAngularEdges(corners)
    expect(lines.wrapped).toBeGreaterThan(0)
    expect(lines.edges.every(line => Math.abs(line.from[0] - line.to[0]) <= 360)).toBe(true)
  })
  it('warns per unavailable frame without write requests', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 404 }); vi.stubGlobal('fetch', fetcher)
    try {
      await expect(readSensorFrame('/workbench/sensor-a/frame-0.json')).rejects.toThrow('HTTP 404')
      expect(fetcher).toHaveBeenCalledWith('/workbench/sensor-a/frame-0.json', expect.objectContaining({ method: 'GET' }))
    } finally { vi.unstubAllGlobals() }
  })
})
