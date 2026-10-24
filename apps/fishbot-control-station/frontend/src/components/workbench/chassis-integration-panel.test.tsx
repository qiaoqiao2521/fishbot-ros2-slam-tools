import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ChassisIntegrationPanel } from './chassis-integration-panel'

describe('shared chassis entry', () => {
  it('keeps the merged serial chassis distinct from accepted MuJoCo transport models', () => {
    const navigate = vi.fn()
    const html = renderToStaticMarkup(<ChassisIntegrationPanel onNavigate={navigate} />)
    for (const id of ['fishbot', 'jackal_j100', 'robot_base_mecanum']) expect(html).toContain(`data-chassis="${id}"`)
    expect(html).toContain('ROS 底盘已合并 · 仿真模型待接入')
    expect(html).toContain('伪终端验证不代表实车或完整运输')
    expect(html).toContain('./fishbot.sh mecanum info')
    expect(html).not.toContain('/coop-api/start')
    expect(navigate).not.toHaveBeenCalled()
  })
})
