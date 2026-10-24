import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ChassisIntegrationPanel } from './chassis-integration-panel'

describe('shared chassis entry', () => {
  it('shows contact and full delivery evidence with their actual observation scope', () => {
    const navigate = vi.fn()
    const html = renderToStaticMarkup(<ChassisIntegrationPanel onNavigate={navigate} />)
    for (const id of ['fishbot', 'jackal_j100', 'robot_base_mecanum']) expect(html).toContain(`data-chassis="${id}"`)
    expect(html).toContain('原生滚子接触 · 同一 MuJoCo 环境')
    expect(html).toContain('开放通道 B→A 完整配送 2/2')
    expect(html).toContain('2D 回归与 3D 雷达均已分别通过')
    expect(html).toContain('理想工位观测与停车保护辅助')
    expect(html).toContain('自主横移导航仍待验收')
    expect(html).toContain('./fishbot.sh mecanum info')
    expect(html).not.toContain('/coop-api/start')
    expect(navigate).not.toHaveBeenCalled()
  })
})
