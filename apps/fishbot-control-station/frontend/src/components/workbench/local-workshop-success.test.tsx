import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import result from '../../../public/workbench/f2-workshop-local-193522-result.json'
import components from '../../../public/workbench/f2-workshop-local-193522/original-components.json'
import timing from '../../../public/workbench/f2-workshop-local-193522/timing.json'
import replay from '../../../public/workbench/f2-workshop-local-193522/replay.json'
import sensor from '../../../public/workbench/f2-workshop-local-193522/sensor/sensor-experience.json'
import catalog from '../../../public/workbench/delivery-results.json'
import scoreContract from '../../../public/workbench/f2-workshop-local-193522/score-contract-summary.json'
import { parseVisionResult } from '@/lib/vision-delivery'
import { VisionDeliveryResult } from './vision-delivery-result'

describe('actual workshop F named business success with original legacy marker retained', () => {
  it('imports the original two passed ideal tasks, same episode and zero resets', () => {
    expect(result.run_id).toBe('f5791fca-7354-4db3-bf35-7c80ff9e9497')
    expect(result.orders.map(o => o.passed)).toEqual([true, true]); expect(result.observation_mode).toBe('ideal')
    expect(result.reset_count).toBe(0); expect(components.original_whole_task_passed).toBe(true)
    expect(components.orders.every(o => o.episode_id === result.provenance.episode_ids[0])).toBe(true)
    expect(result.orders.map(o => o.route_seconds)).toEqual([23.902024271999835, 20.313312582002254])
    expect('visual_chain' in result.assets).toBe(false); expect(result.model).toContain('ideal')
  })
  it('preserves A original_k_passed false alongside true named physical/business scores without rescoring', () => {
    const parsed = parseVisionResult(result), a = parsed.orders[1]
    expect(a.passed).toBe(true); expect(a.originalKPassed).toBe(false)
    expect(a.namedIndependentPassed).toBe(true); expect(a.namedKPassed).toBe(true)
    expect(components.orders[1].original_k_passed).toBe(false)
    expect(timing.cases[1].original_verdict.original_k_passed).toBe(false)
    expect(timing.cases[1].original_verdict.original_score_passed).toBe(true)
    // UI-only projection of actual A to the first visible order, not published evidence.
    const html = renderToStaticMarkup(<VisionDeliveryResult initialResult={{ ...result, orders: [result.orders[1]] }} />)
    expect(html).toContain('原评分口径保留'); expect(html).toContain('命名独立验收：通过')
    expect(html).toContain('original_k_passed'); expect(html).toContain('未通过')
    expect(html).toContain('整单结果仍按原命名／业务验收')
  })
  it('joins the actual task timing/replay and limits16-line sensor evidence to captured startup frames', () => {
    expect(timing.source_run_id).toBe(result.run_id); expect(timing.original_run_passed).toBe(true)
    expect(timing.new_execution).toBe(false); expect(timing.rescored).toBe(false)
    expect(replay.runs.map(r => r.task_id)).toEqual(result.orders.map(o => o.task_id))
    expect(replay.runs.every(r => r.frames.length > 0)).toBe(true)
    expect(sensor.sensor.lines).toBe(16); expect(sensor.frames).toHaveLength(6)
    expect(sensor.tf).toEqual({ requested: 6, matched_source: 5, failed: 1 })
    expect(result.warnings.join(' ')).toContain('启动阶段')
  })
  it('retains D/E failures, partial warehouse and separate actual visual warehouse success', () => {
    expect(catalog.groups).toHaveLength(4)
    for (const id of ['f2-workshop-local-185131', 'f2-workshop-local-190615', 'f2-workshop-local-193522', 'f2-warehouse-local-175145', 'f2-warehouse-local-183948']) expect(catalog.experiments.some(c => c.id === id)).toBe(true)
  })
  it('links verified original parts while retaining the derived-UI appendix boundary and exact audit', () => {
    expect(result.archive_verified).toBe(true); expect(result.provenance.raw_backup.confirmed).toBe(true)
    expect(result.provenance.raw_backup.verified_parts).toBe(2)
    expect(result.provenance.derived_ui_archive_status).toBe('verified_final_appendix')
    expect(parseVisionResult(result).scoreReceiptUrl).toBe(result.assets.score_receipt)
    expect(scoreContract.orders[1].legacy_primary_k_passed).toBe(false)
    expect(scoreContract.orders[1].named_original_k_passed).toBe(true)
    expect(scoreContract.orders.every(o => o.source_nonadvance_count === 0 && o.guard_trip_samples === 0)).toBe(true)
    expect(scoreContract.source_gap_boundary).toContain('.36s source gap')
    expect(scoreContract.new_physics_steps).toBe(0); expect(scoreContract.new_scoring_implementation).toBe(false)
  })
  it('labels an intended folder as pending instead of claiming it already restores this run', () => {
    const html = renderToStaticMarkup(<VisionDeliveryResult initialResult={{ ...result, archive_verified: false }} />)
    expect(html).toContain('打开预定归档文件夹（待读回）')
  })
})
