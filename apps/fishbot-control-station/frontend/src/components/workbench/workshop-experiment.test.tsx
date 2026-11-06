import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import catalog from '../../../public/workbench/delivery-results.json'
import result from '../../../public/workbench/f2-workshop-v2-result.json'
import timing from '../../../public/workbench/f2-workshop-v2/timing.json'
import replay from '../../../public/workbench/f2-workshop-v2/replay.json'
import capture from '../../../public/workbench/f2-workshop-v2/sensor-experience.json'
import videoIndex from '../../../public/workbench/f2-workshop-v2/video-frame-index.json'
import { DeliveryResultsGallery } from './delivery-results-gallery'
import { VisionDeliveryResult } from './vision-delivery-result'

describe('actual workshop failure record', () => {
  it('adds an independent experiment without replacing four accepted configurations', () => {
    expect(catalog.groups).toHaveLength(4)
    expect(catalog.experiments.find(item => item.id === 'f2-workshop-v2')?.source).toBe('/workbench/f2-workshop-v2-result.json')
    const html = renderToStaticMarkup(<DeliveryResultsGallery />)
    expect(html.match(/data-result-group=/g)).toHaveLength(4)
    expect(html).toContain('data-result-experiment="f2-workshop-v2"')
    expect(html).toContain('不自动算作完整配送')
  })
  it('offers a curated media index instead of publishing the raw recording log', () => {
    expect(result.assets.video_index).toBe('/workbench/f2-workshop-v2/video-frame-index.json')
    expect(videoIndex.frame_count).toBe(151); expect(videoIndex.frames).toHaveLength(151)
    expect(videoIndex.new_execution).toBe(false); expect(videoIndex.rescored).toBe(false)
    expect(Object.keys(videoIndex.frames[0]).sort()).toEqual(['episode_id', 'scene_id', 'sim_s', 'source_s', 'video_frame'])
    expect(videoIndex.frames[0].episode_id).toBe(result.provenance.episode_id)
  })
  it('binds actual run, task and episode without turning reception into transport success', () => {
    const order = result.orders[0]
    expect(order.passed).toBe(false); expect(order.route_seconds).toBeNull()
    expect(result.reset_count).toBe(0)
    expect(timing.source_run_id).toBe(result.run_id)
    expect(timing.cases[0].task_id).toBe(order.task_id)
    expect(timing.cases[0].original_verdict.original_score_passed).toBe(false)
    expect(replay.runs[0].task_id).toBe(order.task_id)
    expect(replay.runs[0].frames.length).toBeGreaterThan(0)
    expect(capture.frames).toHaveLength(6)
    expect(capture.frames.every(frame => frame.identity.episode_id === result.provenance.episode_id)).toBe(true)
    expect(capture.sensor.lines).toBe(16)
    expect(result.assets).not.toHaveProperty('visual_chain')
    const html = renderToStaticMarkup(<VisionDeliveryResult initialResult={result} />)
    expect(html).toContain('原评分未通过'); expect(html).toContain('A未派发')
    expect(html).not.toContain('独立业务评分通过')
  })
})
