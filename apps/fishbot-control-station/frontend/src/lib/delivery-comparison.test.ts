import { describe, expect, it } from 'vitest'
import { commonAnchors, distribution, parseDeliveryComparison, readComparison, replayFrame, replayPath } from './delivery-comparison'
import { resolveAppRoute } from './app-route'

const fixture = () => ({ schema: 'fishbot.delivery-comparison.v1', read_only: true, rescored: false,
  same_checkpoint_id: true, same_scene_geometry: true, view_bounds_xy: [-3, -4, 2, 1], scene: {},
  runs: [{ id: 'run', label: 'baseline', task_id: 'task', episode_id: 'episode', scope: 'route', group: 'baseline',
    original_verdict: { original_score_passed: false }, anchors: { route: 100 }, route: { elapsed_s: 120.02, budget_s: 120 },
    spans: [{ layer: 'native', label: 'Nav2', goal_id: 'native-original', terminal_status: 5 }],
    frames: [100, 100.1, 100.5].map((time, i) => ({ source_s: time, sequence: i + 1, stage: 'delivery',
      gap_before: i === 2, car: [4 + i, -2, 0], quaternion: [1, 0, 0, 0], cargo: [4 + i, -2, .2], arm_q6: [0, 0, 0, 0, 0, 0] })) }] })

describe('recorded delivery comparison', () => {
  it('keeps source coordinates, original failure and the dedicated read-only route', () => {
    const value = parseDeliveryComparison(fixture())
    expect(value.runs[0].passed).toBe(false)
    expect(value.runs[0].nativeActions[0]).toEqual({ label: 'Nav2', uuid: 'native-original', status: 5 })
    expect(replayFrame(value.runs[0], .1, 'route')?.car?.[0]).toBe(5)
    expect(replayPath(value.runs[0])).toBe('M4,2 L5,2 M6,2')
    expect(resolveAppRoute('/regression')).toBe('regression')
    expect(commonAnchors(value.runs)).toEqual(['route'])
  })
  it('does not hold or interpolate across a missing source interval', () => {
    const run = parseDeliveryComparison(fixture()).runs[0]
    expect(replayFrame(run, .3, 'route')).toBeNull()
    expect(replayFrame(run, .5, 'route')?.sequence).toBe(3)
    expect(replayFrame(run, -1, 'route')).toBeNull()
    expect(replayFrame(run, .1, 'missing-anchor')).toBeNull()
  })
  it('skips a malformed sample and starts the next path segment explicitly', () => {
    const input = fixture(); input.runs[0].frames[1].source_s = 99
    const result = parseDeliveryComparison(input)
    expect(result.runs[0].frames).toHaveLength(2)
    expect(result.runs[0].warnings.some(s => s.includes('展示不完整'))).toBe(true)
    expect(replayPath(result.runs[0])).toBe('M4,2 M6,2')
  })
  it('keeps failures and missing values distinct in distributions', () => {
    expect(distribution([120.02, 80, null, 100])).toEqual({ n: 3, missing: 1, min: 80, max: 120.02, p25: 80, median: 100, p75: 120.02, p95: 120.02 })
    expect(distribution([]).median).toBeNull()
  })
  it('retains recognizable fields in an editable partial report', async () => {
    const value = parseDeliveryComparison({ runs: [null, { id: 'partial' }] })
    expect(value.runs).toHaveLength(1)
    expect(value.warnings.length).toBeGreaterThan(0)
    expect(value.runs[0].passed).toBeNull()
    await expect(readComparison({ size: 9 * 1024 * 1024, text: async () => '{}' })).rejects.toThrow('8 MiB')
  })
})
