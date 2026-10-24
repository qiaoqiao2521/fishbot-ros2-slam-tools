import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import snapshot from '../../../public/workbench/delivery-timing.json'
import { DeliveryTimingPanel } from './delivery-timing-panel'

describe('delivery timing panel', () => {
  it('renders real budgets, gap disclosures and historical boundaries without starting an operation', () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    try {
      const html = renderToStaticMarkup(<DeliveryTimingPanel initialReport={snapshot} />)
      expect(html).toContain('119.794 s'); expect(html).toContain('0.206 s')
      expect(html).toContain('历史仿真导入 · 未新执行或重评分')
      expect(html).toContain('物理采样缺口'); expect(html).toContain('控制器计算 / 消费回执')
      expect(html).toContain('0.80 s'); expect(html).toContain('未归因区间')
      expect(html).not.toContain('/coop-api/start'); expect(html).not.toContain('file://')
      expect(fetcher).not.toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })

  it('keeps missing metrics unknown and an explicitly failed score failed', () => {
    const html = renderToStaticMarkup(<DeliveryTimingPanel initialReport={{ cases: [{ id: 'failure', original_verdict: { original_score_passed: false } }] }} />)
    expect(html).toContain('未通过'); expect(html).toContain('缺少起点时间')
    expect(html).not.toContain('0.000 s'); expect(html).toContain('来源边界待确认')
  })
})
