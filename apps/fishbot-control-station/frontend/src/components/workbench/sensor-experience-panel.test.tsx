import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { SensorExperiencePanel } from './sensor-experience-panel'
// Isolated UI fixture; no public frame or task acceptance is generated.
const identity = { scene_sha256: 'ui-scene', manifest_sha256: 'ui-manifest', episode_id: 'ui-episode', sequence: '42' }
const report = { schema: 'fishbot.sensor-experience.v1', read_only: true, new_execution: false, rescored: false, status: 'complete', frame_id: 'lidar3d_link', truth_to_control: false, sensor: { scan_pattern: 'livox_mid360_csv_stride5', lines: 1, horizontal_samples: 4000, rate_hz: 10, angular_downsample: 5 }, frames: [{ url: 'frame-0.json', identity, source_s: 12.4, valid_points: 1 }], actual_subscribers: [{ node: '/global_costmap/global_costmap', type: 'sensor_msgs/msg/PointCloud2' }], message_counts: { pointcloud: 10, physics: 12 }, tf: { requested: 1, matched_source: 1, failed: 0 } }
const frame = { identity, source_s: 12.4, source_stamp_ns: '12400000000', frame_id: 'lidar3d_link', truth_to_control: false, observed: { source: 'actual_received_PointCloud2', topic: '/sensors/lidar3d/points', points: [[1, 0, .1]], valid_points: 1, width: 4000, height: 1 }, truth: { frame_id: 'lidar3d_link', reference_only: true, boxes: [{ id: 'ui-box', vertices: [[1, -1, -1], [1, -1, 1], [1, 1, -1], [1, 1, 1], [2, -1, -1], [2, -1, 1], [2, 1, -1], [2, 1, 1]] }] }, actual_tf: null }
describe('sensor experience panel', () => {
  it('shows exact-source panorama and consumer evidence without manufacturing a run identity', () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    try {
      const html = renderToStaticMarkup(<SensorExperiencePanel sourceUrl="/workbench/sensor-a/sensor-experience.json" initialReport={report} initialFrame={frame} expectedRunId="actual-task-run" />)
      expect(html).toContain('该采集报告未绑定 run_id'); expect(html).toContain('12400000000')
      expect(html).toContain('同一源帧的点云与真值全景投影'); expect(html).toContain('/global_costmap/global_costmap')
      expect(html).toContain('订阅发现不等于逐消息消费ACK'); expect(html).toContain('不通过车体真值补TF')
      expect(html).not.toContain('/coop-api/start'); expect(fetcher).not.toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })
  it('puts the real view before long identities and explains known TF failures without losing originals', () => {
    const original = 'Same-source map TF unavailable: Lookup would require extrapolation into the past. Requested time 2.100000 but earliest data 2.900000'
    const html = renderToStaticMarkup(<SensorExperiencePanel sourceUrl="/workbench/sensor-a/sensor-experience.json" initialReport={{ ...report, warnings: [original, 'unknown warning stays original'], tf: { requested: 6, matched_source: 5, failed: 1 }, frames: [{ ...report.frames[0], source_s: 12.40000000000081 }] }} initialFrame={frame} />)
    expect(html).toContain('部分帧未取得对应时刻 map TF，未以真值补齐')
    expect(html).toContain('原始TF采集原因（1项）'); expect(html).toContain(original)
    expect(html).toContain('unknown warning stays original'); expect(html).toContain('源 12.400s')
    expect(html).not.toContain('12.40000000000081s')
    expect(html.indexOf('class="sensor-panorama"')).toBeLessThan(html.indexOf('class="sensor-experience-identity"'))
    expect(html.indexOf('class="sensor-source-details"')).toBeLessThan(html.indexOf('12400000000'))
    expect(html).toContain('&quot;matched_source&quot;:5'); expect(html).toContain('&quot;failed&quot;:1')
  })
  it('does not overlay frames from a different sequence', () => {
    const html = renderToStaticMarkup(<SensorExperiencePanel sourceUrl="/workbench/sensor-a/sensor-experience.json" initialReport={report} initialFrame={{ ...frame, identity: { ...identity, sequence: '43' } }} />)
    expect(html).toContain('当前帧不参与叠加'); expect(html).not.toContain('class="sensor-panorama"')
  })
  it('keeps actual points while declining a mismatched truth coordinate frame', () => {
    const html = renderToStaticMarkup(<SensorExperiencePanel sourceUrl="/workbench/sensor-a/sensor-experience.json" initialReport={report} initialFrame={{ ...frame, truth: { ...frame.truth, frame_id: 'other_sensor' } }} />)
    expect(html).toContain('仅显示实际点云'); expect(html).toContain('<circle')
    expect(html).toContain('disabled=""')
  })
})
