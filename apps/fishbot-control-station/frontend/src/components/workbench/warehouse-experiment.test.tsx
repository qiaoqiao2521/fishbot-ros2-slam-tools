import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import catalog from '../../../public/workbench/delivery-results.json'
import result from '../../../public/workbench/f2-warehouse-v3-result.json'
import timing from '../../../public/workbench/f2-warehouse-v3/timing.json'
import capture from '../../../public/workbench/f2-warehouse-v3/sensor-experience.json'
import native from '../../../public/workbench/f2-warehouse-v3/native-lidar-consumer.json'
import chain from '../../../public/workbench/f2-warehouse-v3/visual-chain.json'
import videoIndex from '../../../public/workbench/f2-warehouse-v3/video-frame-index.json'
import { parseVisualEvidence } from '@/lib/visual-evidence'
import { VisualEvidencePanel } from './visual-evidence-panel'

describe('actual warehouse v3 failed experiment', () => {
  it('keeps four historical groups and the v2 workshop failure independent', () => {
    expect(catalog.groups).toHaveLength(4)
    expect(catalog.experiments.map(item => item.id)).toContain('f2-workshop-v2')
    expect(catalog.experiments.find(item => item.id === 'f2-warehouse-v3')?.source).toBe('/workbench/f2-warehouse-v3-result.json')
    expect(result.orders[0].passed).toBe(false)
    expect(timing.source_run_id).toBe(result.run_id)
    expect(timing.cases[0].task_id).toBe(result.orders[0].task_id)
  })
  it('keeps a curated actual-frame index with the original episode and count', () => {
    expect(result.assets.video_index).toBe('/workbench/f2-warehouse-v3/video-frame-index.json')
    expect(videoIndex.frame_count).toBe(260); expect(videoIndex.frames).toHaveLength(260)
    expect(videoIndex.new_execution).toBe(false); expect(videoIndex.rescored).toBe(false)
    expect(Object.keys(videoIndex.frames[0]).sort()).toEqual(['episode_id', 'scene_id', 'sim_s', 'source_s', 'video_frame'])
    expect(videoIndex.frames[0].episode_id).toBe(result.provenance.episode_id)
  })
  it('shows the real empty visual chain with compile timeout rather than invented model input', () => {
    expect(chain.entries).toEqual([]); expect(chain.run_id).toBe(result.run_id)
    const events = parseVisualEvidence(chain).queries[0].stages
    expect(events.some(e => e.stage === 'rig_model_compile_started')).toBe(true)
    expect(events.some(e => ['rgbd_render_started', 'official_inference_request_started'].includes(e.stage))).toBe(false)
    expect(events.find(e => e.stage === 'query_deadline_reached')?.elapsed).toBeCloseTo(30.010198287, 6)
    const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl="/workbench/f2-warehouse-v3/visual-chain.json" initialReport={chain} expectedRunId={result.run_id} taskId={result.orders[0].task_id} />)
    expect(html).toContain('不能把服务加载当作实际模型调用')
    expect(html).toContain('机械臂模型编译开始'); expect(html).toContain('原30秒到期')
    expect(html).not.toContain('<img'); expect(html).not.toContain('所选抓取候选</h3>')
  })
  it('preserves real MID scan and native interface evidence without exclusive causal claims', () => {
    expect(capture.sensor.scan_pattern).toBe('livox_mid360_csv_stride5')
    expect(capture.sensor.horizontal_samples).toBe(4000); expect(capture.sensor.lines).toBe(1)
    expect(capture.frames).toHaveLength(6)
    expect(capture.frames.every(frame => frame.identity.episode_id === result.provenance.episode_id)).toBe(true)
    expect(native.pointcloud.width).toBe(4000); expect(native.evidence.low_obstacle_has_3d_returns).toBe(true)
    expect(result.orders[0].component_summary).toContain('静态collision_map')
    expect(result.warnings.join(' ')).toContain('不做3D排他归因或逐消息ACK')
  })
})
