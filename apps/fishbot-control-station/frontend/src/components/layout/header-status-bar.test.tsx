import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HeaderStatusBar } from '@/components/layout/header-status-bar'

const fixture = vi.hoisted(() => ({ usingFallbackData: false, mode: 'live' }))
vi.mock('@/store/station-store', () => ({ useStationStore: () => ({
  usingFallbackData: fixture.usingFallbackData,
  connection: { mode: fixture.mode, controlBridge: { connected: true, telemetryOnline: true },
    laserBridge: { connected: true, telemetryOnline: true } },
}) }))
afterEach(() => { fixture.usingFallbackData = false; fixture.mode = 'live' })

describe('station connection source boundaries', () => {
  it('does not present a fallback connection as live when another resource has hydrated', () => {
    fixture.mode = 'fallback'
    const html = renderToStaticMarkup(<HeaderStatusBar />)
    expect(html).toContain('本地兜底快照'); expect(html).toContain('示例')
    expect(html).not.toContain('已连接'); expect(html).not.toContain('有数据')
  })
  it('labels offline telemetry as simulated even when bridge snapshot flags are true', () => {
    fixture.mode = 'offline'
    const html = renderToStaticMarkup(<HeaderStatusBar />)
    expect(html).toContain('离线开发模式'); expect(html).toContain('模拟遥测')
    expect(html).not.toContain('已连接'); expect(html).not.toContain('有数据')
  })
  it('describes ROS reports without claiming a physical robot is online', () => {
    const html = renderToStaticMarkup(<HeaderStatusBar />)
    expect(html).toContain('ROS 话题链路'); expect(html).toContain('最近桥接报告')
    expect(html).toContain('不判定实体在线'); expect(html).not.toContain('实机链路')
  })
})
