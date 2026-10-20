import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { HardwareLabPanel } from './hardware-lab-panel'
import { hardwareLabMetric, parseHardwareLabReport, readHardwareLabReport } from './hardware-lab-report'

const fixture = { scope: 'simulation', sections: [
  { id: 'real_map', title: '真实场地图', status: 'passed', basis: '实测二维工作图，墙高为假设', summary: '仅走已知区域，保留未知格', cases: [
    { id: 'map-roundtrip', label: '实测区域往返', status: 'passed', reason: '原任务返回起点并停稳', metrics: { distance_m: 2.7, collision_steps: 0 } },
  ] },
  { id: 'new_base', title: '新底盘', status: 'failed', basis: '官方底盘模型与同一 MuJoCo', summary: '新底盘保持独立验收', cases: [
    { id: 'base-turn', label: '底盘转弯', status: 'failed', reason: '车体无法满足该门口净空', metrics: { clearance_m: -.02 } },
  ] },
  { id: 'suction', title: '负压与爬壁', status: 'incomplete', basis: '压力与摩擦简化模型', summary: '密封泄漏模型待补齐', cases: [
    { id: 'fan-loss', label: '风机失效', status: 'passed', reason: '负压下降后模型发生滑移', metrics: { pressure_pa: 0, slip: true } },
  ] },
] }

afterEach(() => vi.unstubAllGlobals())

describe('hardware lab panel', () => {
  it('initially makes zero requests and exposes only an explicit report read', () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const html = renderToStaticMarkup(<HardwareLabPanel />)
    expect(fetcher).not.toHaveBeenCalled()
    expect(html).toContain('尚未读取实验报告')
    expect(html).toContain('读取实验报告')
    expect(html).toContain('三项分别验收，不代表组合爬壁运输或真机通过')
    expect(html).not.toContain('/cmd_vel')
    expect(html).not.toContain('/coop-api/start')
  })

  it('shows three independent results, concrete reasons and expandable original metrics', () => {
    const html = renderToStaticMarkup(<HardwareLabPanel initialReport={fixture} />)
    expect(html).toContain('hardware-lab-status-passed">通过')
    expect(html).toContain('hardware-lab-status-failed">未通过')
    expect(html).toContain('hardware-lab-status-incomplete">待补齐')
    expect(html).toContain('车体无法满足该门口净空')
    expect(html).toContain('压力与摩擦简化模型')
    expect(html).toContain('<details><summary>查看案例指标</summary>')
    expect(html).toContain('distance_m')
    expect(html).toContain('2.7')
    expect(html).toContain('map-roundtrip')
    expect(html).not.toContain('全部通过')
    expect(html).not.toContain('<video')
  })

  it('shows a manually played recording only for the ground-to-wall suction case', () => {
    const transition = { ...fixture.sections[2], cases: [{ id: 'ground_to_wall', label: '整车转墙', status: 'failed', reason: '试验未满足停车条件', metrics: {} }] }
    const html = renderToStaticMarkup(<HardwareLabPanel initialReport={{ ...fixture, sections: [...fixture.sections.slice(0, 2), transition] }} />)
    expect(html).toContain('src="/hardware-lab/transition.mp4"')
    expect(html).toContain('controls=""')
    expect(html).toContain('preload="none"')
    expect(html).not.toContain('autoPlay')
    expect(html).not.toContain('autoplay')
    expect(html).toContain('不代表 Jackal J100 或真机已具备该能力')
    expect(html).toContain('理想吸附基准')
    expect(html).toContain('试验未满足停车条件')
    const unrelated = renderToStaticMarkup(<HardwareLabPanel initialReport={{ ...fixture, sections: [{ ...fixture.sections[0], cases: transition.cases }, ...fixture.sections.slice(1)] }} />)
    expect(unrelated).not.toContain('<video')
  })

  it('keeps the ideal recording beside a distinct failed hardware candidate and its no-pump result', () => {
    const suction = { ...fixture.sections[2], status: 'failed', cases: [
      { id: 'ground_to_wall', label: '理想整车转墙', status: 'passed', reason: '理想密封基准完成', metrics: {} },
      { id: 'ground_to_wall_hardware', label: '含载荷转墙候选', status: 'failed', reason: '裙边泄漏后未完成转墙', metrics: { payload_kg: 2.0 } },
      { id: 'pump_off_hardware', label: '同载荷无泵对照', status: 'passed', reason: '负控未完成转墙，符合预期', metrics: { task_motion_success: false } },
    ] }
    const html = renderToStaticMarkup(<HardwareLabPanel initialReport={{ ...fixture, sections: [...fixture.sections.slice(0, 2), suction] }} />)
    expect(html.match(/<video /g)).toHaveLength(2)
    expect(html).toContain('src="/hardware-lab/transition.mp4"')
    expect(html).toContain('src="/hardware-lab/transition-hardware.mp4"')
    expect(html).toContain('理想吸附基准')
    expect(html).toContain('泵阀载荷与固定裙边间隙')
    expect(html).toContain('失败案例不代表上墙成功')
    expect(html).toContain('裙边泄漏后未完成转墙')
    expect(html).toContain('pump_off_hardware')
    expect(html).toContain('task_motion_success')
    expect(html).not.toContain('autoplay')
    const hardwareOnly = renderToStaticMarkup(<HardwareLabPanel initialReport={{ ...fixture, sections: [...fixture.sections.slice(0, 2), { ...suction, cases: suction.cases.slice(1) }] }} />)
    expect(hardwareOnly).toContain('src="/hardware-lab/transition-hardware.mp4"')
    expect(hardwareOnly).not.toContain('src="/hardware-lab/transition.mp4"')
  })

  it('only GETs the fixed report endpoint once and keeps future metadata compatible', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ ...fixture, future_field: 'editable' })))
    const report = await readHardwareLabReport(null, fetcher)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith('/hardware-lab/report', { method: 'GET', cache: 'no-store' })
    expect(report.sections).toHaveLength(3)
    expect(report.sections[0].cases[0].metrics.distance_m).toBe(2.7)
    expect(report.warnings).toHaveLength(0)
  })

  it('retains previous evidence when a section or its cases are missing and marks that evidence historical', () => {
    const previous = parseHardwareLabReport(fixture)
    const next = parseHardwareLabReport({ scope: 'simulation', sections: [
      { ...fixture.sections[0], summary: '本次已更新', cases: undefined },
    ] }, previous)
    expect(next.sections[0].summary).toBe('本次已更新')
    expect(next.sections[0].cases).toEqual(previous.sections[0].cases)
    expect(next.sections[0].status).toBe('incomplete')
    expect(next.sections[1].cases).toEqual(previous.sections[1].cases)
    expect(next.sections.every((section) => section.retained)).toBe(true)
    expect(next.warnings.some((warning) => warning.includes('沿用上次'))).toBe(true)
    const missing = parseHardwareLabReport({}, previous)
    expect(missing.sections[0].cases[0].id).toBe('map-roundtrip')
    expect(missing.warnings.some((warning) => warning.includes('sections'))).toBe(true)
  })

  it('downgrades passed headings with absent, empty, failed or incomplete current cases while keeping siblings', () => {
    for (const cases of [undefined, null, []]) {
      const report = parseHardwareLabReport({ ...fixture, sections: [{ ...fixture.sections[0], cases }, ...fixture.sections.slice(1)] })
      expect(report.sections[0].status).toBe('incomplete')
      expect(report.sections[1].status).toBe('failed')
      expect(report.sections[2].status).toBe('incomplete')
      expect(report.warnings.some((warning) => warning.includes('缺少有效案例'))).toBe(true)
    }
    for (const status of ['failed', 'incomplete'] as const) {
      const report = parseHardwareLabReport({ ...fixture, sections: [{ ...fixture.sections[0], cases: [{ ...fixture.sections[0].cases[0], status }] }, ...fixture.sections.slice(1)] })
      expect(report.sections[0].status).toBe(status)
      expect(report.sections[0].cases[0].status).toBe(status)
      expect(report.sections[1].cases[0].id).toBe('base-turn')
      expect(report.warnings.some((warning) => warning.includes('分项“通过”已改为'))).toBe(true)
    }
    const previous = parseHardwareLabReport(fixture)
    const partial = parseHardwareLabReport({ scope: 'simulation', sections: [] }, previous)
    expect(partial.sections[0].status).toBe('passed')
    expect(partial.sections[0].retained).toBe(true)
    expect(partial.sections[0].cases[0].id).toBe('map-roundtrip')
  })

  it('warns and continues after malformed sections or cases without claiming absent evidence passed', () => {
    const report = parseHardwareLabReport({ scope: 'future-scope', sections: [
      null, { id: 'unknown-section' }, { ...fixture.sections[0], status: 'optimistic', cases: [null, fixture.sections[0].cases[0]] },
    ] })
    expect(report.sections[0].status).toBe('incomplete')
    expect(report.sections[0].cases[0].status).toBe('incomplete')
    expect(report.sections[0].cases[1].id).toBe('map-roundtrip')
    expect(report.sections[1].cases).toEqual([])
    expect(report.warnings.some((warning) => warning.includes('其余分项仍可查看'))).toBe(true)
    expect(report.warnings.some((warning) => warning.includes('不能据此判断真机'))).toBe(true)
    expect(() => parseHardwareLabReport(null)).toThrow('已有报告继续保留')
  })

  it('surfaces failed reads without modifying or retrying the previous report', async () => {
    const previous = parseHardwareLabReport(fixture)
    const before = JSON.stringify(previous)
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 404 }))
    await expect(readHardwareLabReport(previous, fetcher)).rejects.toThrow('HTTP 404')
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(previous)).toBe(before)
    const broken = vi.fn<typeof fetch>().mockResolvedValue(new Response('{broken'))
    await expect(readHardwareLabReport(previous, broken)).rejects.toBeInstanceOf(SyntaxError)
    expect(JSON.stringify(previous)).toBe(before)
  })

  it('renders long editable values safely and handles unusual metric types', () => {
    expect(hardwareLabMetric(false)).toBe('否')
    expect(hardwareLabMetric(null)).toBe('未提供')
    expect(hardwareLabMetric(Number.POSITIVE_INFINITY)).toBe('非有限数值')
    expect(hardwareLabMetric({ force_n: 3 })).toBe('{"force_n":3}')
    const cycle: Record<string, unknown> = {}
    cycle.self = cycle
    expect(hardwareLabMetric(cycle)).toBe('无法显示该指标')
    const html = renderToStaticMarkup(<HardwareLabPanel initialReport={{ ...fixture, sections: [{ ...fixture.sections[0], summary: '<script>unsafe</script>' }] }} />)
    expect(html).toContain('&lt;script&gt;unsafe&lt;/script&gt;')
    expect(html).not.toContain('<script>unsafe</script>')
  })
})
