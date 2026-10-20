import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SceneValidationPanel } from './scene-validation-panel'
import { parseSceneValidationReport, readLatestSceneValidationReport, readLocalSceneValidationReport } from './scene-validation-report'

const fixture = {
  schema_version: 1, scope: 'simulation', business_scope: 'navigation_roundtrip',
  source: { label: '窄口往返对照', basis: '来自工作地图；边界区域待现场复测', assumption_cells: ['北侧缺失区域'] },
  lidar: { profile: '二维雷达基线' },
  cases: [{ id: 'blocked', label: '禁路正确拒绝', expected: 'blocked', business_result: 'route_incomplete', acceptance_result: 'passed', reason: '虚拟墙截断路径', task_id: 'original-task', native_goal_id: 'original-goal', native_status: 5, metrics: { stop_distance_m: 0.3 } }],
}

afterEach(() => vi.unstubAllGlobals())

describe('scene business validation panel', () => {
  it('separates route completion from case acceptance and preserves old delivery reports', () => {
    const html = renderToStaticMarkup(<SceneValidationPanel initialReport={{ ...fixture, source: { ...fixture.source, basis: 'synthetic_reference' }, cases: [...fixture.cases, { label: '正常往返', expected: 'delivered', business_result: 'route_completed', acceptance_result: 'passed' }] }} />)
    expect(html).toContain('scene-validation-business-route_incomplete">往返未完成')
    expect(html).toContain('scene-validation-business-route_completed">往返完成')
    expect(html).toContain('scene-validation-acceptance-passed">通过')
    expect(html).not.toContain('scene-validation-business-delivered">已交付')
    expect(html).toContain('本轮验证路线，不包含货物交接与收货签收')
    expect(html).toContain('合成参考场景，尚未现场实测')
    expect(html).toContain('scene-validation-expected">完成往返')
    expect(html).not.toContain('scene-validation-expected">delivered')
    expect(html).toContain('虚拟墙截断路径')
    expect(html).toContain('original-task'); expect(html).toContain('original-goal')
    expect(html).toContain('stop_distance_m'); expect(html).toContain('0.3')
    expect(html).toContain('北侧缺失区域')
    const legacy = renderToStaticMarkup(<SceneValidationPanel initialReport={{ ...fixture, business_scope: undefined, cases: [{ ...fixture.cases[0], business_result: 'undelivered' }, { label: '旧运输结果', business_result: 'delivered', acceptance_result: 'passed' }] }} />)
    expect(legacy).toContain('scene-validation-business-undelivered">未交付')
    expect(legacy).toContain('scene-validation-business-delivered">已交付')
    expect(legacy).not.toContain('本轮验证路线，不包含货物交接与收货签收')
  })

  it('keeps optional metadata and unknown results editable rather than failing the report', () => {
    const report = parseSceneValidationReport({ cases: [{ label: '缺元数据案例' }] })
    expect(report.source.label).toBe('来源未标明')
    expect(report.cases[0]).toMatchObject({ businessResult: 'unknown', acceptanceResult: 'incomplete', taskId: '未提供' })
    expect(report.warnings.length).toBeGreaterThan(0)
    const html = renderToStaticMarkup(<SceneValidationPanel initialReport={{ cases: [{ label: '缺元数据案例' }] }} />)
    expect(html).toContain('待确认'); expect(html).toContain('待补齐')
    expect(html).toContain('报告提示'); expect(html).toContain('来源未标明')
  })

  it('preserves the good case after a malformed case and accepts newer report metadata with a warning', () => {
    const report = parseSceneValidationReport({ ...fixture, schema_version: 2, cases: [null, fixture.cases[0]] })
    expect(report.cases).toHaveLength(2)
    expect(report.cases[0]).toMatchObject({ businessResult: 'unknown', acceptanceResult: 'incomplete' })
    expect(report.cases[1]).toMatchObject({ id: 'blocked', acceptanceResult: 'passed' })
    expect(report.warnings.some((warning) => warning.includes('版本'))).toBe(true)
    expect(report.warnings.some((warning) => warning.includes('其余案例仍可查看'))).toBe(true)
  })

  it('does not request a report or send motion when initially rendered', () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const html = renderToStaticMarkup(<SceneValidationPanel />)
    expect(html).toContain('尚未读取报告')
    expect(html).toContain('读取最新报告'); expect(html).toContain('导入场景业务验证 JSON')
    expect(fetcher).not.toHaveBeenCalled()
    expect(html).not.toContain('/coop-api/start'); expect(html).not.toContain('/cmd_vel')
  })

  it('explicitly reads the report with only a GET and no motion write', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(fixture)))
    const report = await readLatestSceneValidationReport(fetcher)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith('/scene-validation/report', { method: 'GET', cache: 'no-store' })
    expect(report.businessScope).toBe('navigation_roundtrip')
    expect(report.cases[0].businessResult).toBe('route_incomplete')
  })

  it('imports local edited JSON without making network requests', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const report = await readLocalSceneValidationReport({ text: async () => JSON.stringify({ ...fixture, cases: [...fixture.cases, { label: '人工补充案例' }] }) })
    expect(report.cases).toHaveLength(2)
    expect(report.cases[1].label).toBe('人工补充案例')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('reports transport or invalid JSON failures without requesting fallback robot actions', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response('', { status: 404 }))
    await expect(readLatestSceneValidationReport(fetcher)).rejects.toThrow('HTTP 404')
    expect(fetcher).toHaveBeenCalledTimes(1)
    await expect(readLocalSceneValidationReport({ text: async () => '{broken' })).rejects.toBeInstanceOf(SyntaxError)
  })
})
