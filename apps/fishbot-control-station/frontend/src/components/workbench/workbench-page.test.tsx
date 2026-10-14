import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkbenchPage, WorkbenchVisualCases } from './workbench-page'
import { workbenchSnapshot } from '@/lib/workbench-catalog'
import type { ServiceId } from '@/lib/workbench-catalog'
import type { ServiceState } from '@/lib/workbench-services'

const serviceFixture = vi.hoisted(() => ({
  services: {
    spatiallm: { status: 'unchecked', message: '尚未检查场景编辑器', checkedAt: null },
    video: { status: 'unchecked', message: '尚未检查视频复核台', checkedAt: null },
  } as Record<ServiceId, ServiceState>,
  checking: false, refresh: vi.fn(),
}))
vi.mock('@/hooks/use-workbench-services', () => ({ useWorkbenchServices: () => serviceFixture }))

afterEach(() => {
  vi.unstubAllGlobals()
  serviceFixture.services.spatiallm = { status: 'unchecked', message: '尚未检查场景编辑器', checkedAt: null }
  serviceFixture.services.video = { status: 'unchecked', message: '尚未检查视频复核台', checkedAt: null }
  serviceFixture.checking = false
  serviceFixture.refresh.mockClear()
})
function render(hostname = '127.0.0.1') {
  vi.stubGlobal('window', { location: { hostname } })
  return renderToStaticMarkup(<WorkbenchPage onNavigate={vi.fn()} />)
}

describe('workbench frozen evidence page', () => {
  it('renders all six capabilities with task flow, boundaries and the frozen snapshot source', () => {
    const html = render()
    expect(html).toContain('成果工作台')
    for (const item of workbenchSnapshot.capabilities) {
      expect(html).toContain(`data-capability="${item.id}"`)
      expect(html).toContain(item.title)
      expect(html).toContain(item.boundary)
    }
    expect(html).toContain('准备空间'); expect(html).toContain('配置地图与规则')
    expect(html).toContain('执行停靠与运输'); expect(html).toContain('分析过程')
    expect(html).toContain(workbenchSnapshot.snapshotLabel)
    expect(html).toContain(`dateTime="${workbenchSnapshot.updatedAt}"`)
    expect(html).toContain(workbenchSnapshot.sourceRevision)
    expect(html).toContain('href="/workbench/recent-results.json"')
    expect(html).not.toContain('file://'); expect(html).not.toContain('/coop-api/start')
    expect(serviceFixture.refresh).not.toHaveBeenCalled()
  })

  it('keeps all 56 original cases separate from the three supplemental workflow cases', () => {
    const html = render()
    expect((html.match(/data-case-id=/g) || []).length).toBe(56)
    expect((html.match(/data-workflow-case-id=/g) || []).length).toBe(3)
    expect(html).toContain('严格验收尚未全部通过')
    expect(html).toContain('此结果不补齐原56例中的11项失败')
    expect(html).toContain('短停靠 34 / 完整运输 4')
    expect(html).toContain('确认原动作终态与停车，不算任务完成')
    for (const item of workbenchSnapshot.visual.cases) {
      expect(html).toContain(`data-case-id="${item.id}"`)
      expect(html).toContain(item.scoreSha256)
      if (item.reason) expect(html).toContain(item.reason)
    }
  })

  it.each([
    ['all', 56], ['failed', 11], ['completed', 38], ['safe-cancel', 7],
  ] as const)('renders the %s case filter from the original inventory', (filter, expected) => {
    const html = renderToStaticMarkup(<WorkbenchVisualCases filter={filter} onFilterChange={vi.fn()} />)
    expect((html.match(/data-case-id=/g) || []).length).toBe(expected)
    expect(html).toContain(`显示 ${expected} 条案例`)
    if (filter !== 'all') {
      const statuses = [...html.matchAll(/data-case-status="([^"]+)"/g)].map((match) => match[1])
      expect(statuses.every((item) => item === filter)).toBe(true)
    }
  })

  it('does not claim an unchecked local tool is online or expose its active link', () => {
    const html = render()
    expect(html).toContain('尚未检查场景编辑器'); expect(html).toContain('尚未检查视频复核台')
    expect(html).toContain('data-service-status="unchecked"')
    expect(html).not.toContain(`href="${workbenchSnapshot.services.spatiallm.url}"`)
    expect(html).not.toContain(`href="${workbenchSnapshot.services.video.url}"`)
  })

  it('opens only a positively checked local tool in a separate protected tab', () => {
    serviceFixture.services.spatiallm = { status: 'available', message: '场景编辑器已核对可用', checkedAt: 1000 }
    serviceFixture.services.video = { status: 'unexpected', message: '端口返回了不同工具', checkedAt: 1000 }
    const html = render('localhost')
    expect(html).toContain(`href="${workbenchSnapshot.services.spatiallm.url}"`)
    expect(html).toContain('target="_blank" rel="noopener noreferrer"')
    expect(html).not.toContain(`href="${workbenchSnapshot.services.video.url}"`)
    expect(html).toContain('端口返回了不同工具')
  })

  it('shows failed checks without presenting stale local tools as available', () => {
    serviceFixture.services.spatiallm = { status: 'unavailable', message: '场景编辑器未运行', checkedAt: 1000 }
    serviceFixture.services.video = { status: 'checking', message: '正在核对视频复核台', checkedAt: null }
    serviceFixture.checking = true
    const html = render()
    expect(html).toContain('场景编辑器未运行'); expect(html).toContain('正在检查本机工具')
    expect(html).not.toContain(`href="${workbenchSnapshot.services.spatiallm.url}"`)
    expect(html).not.toContain(`href="${workbenchSnapshot.services.video.url}"`)
  })

  it('withholds local tool URLs on remote hosts even when a stored check was available', () => {
    serviceFixture.services.spatiallm = { status: 'available', message: '场景编辑器已核对可用', checkedAt: 1000 }
    serviceFixture.services.video = { status: 'available', message: '视频复核台已核对可用', checkedAt: 1000 }
    const html = render('192.168.0.101')
    expect(html).toContain('需在工作台电脑打开')
    expect(html).toContain('手机的本机地址指向手机自身')
    expect(html).not.toContain(`href="${workbenchSnapshot.services.spatiallm.url}"`)
    expect(html).not.toContain(`href="${workbenchSnapshot.services.video.url}"`)
    expect(html).toContain('href="/workbench/recent-results.json"')
    expect(serviceFixture.refresh).not.toHaveBeenCalled()
  })

  it('supports server rendering without a browser or automatic tool checks', () => {
    const html = renderToStaticMarkup(<WorkbenchPage onNavigate={vi.fn()} />)
    expect(html).toContain('成果工作台')
    expect(html).toContain('需在工作台电脑打开')
    expect(serviceFixture.refresh).not.toHaveBeenCalled()
  })
})
