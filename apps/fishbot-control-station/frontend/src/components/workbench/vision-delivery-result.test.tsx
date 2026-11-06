import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import summary from '../../../public/workbench/j100-vision-result.json'
import { VisionDeliveryResult } from './vision-delivery-result'

describe('visual delivery result', () => {
  it('does not certify an unrecognized source kind as audited historical evidence', () => {
    const html = renderToStaticMarkup(<VisionDeliveryResult initialResult={{ ...summary, evidence_kind: 'editable-unknown' }} />)
    expect(html).toContain('来源待确认'); expect(html).not.toContain('已审历史摘要')
  })
  it('shows the actual selected result and missing material without sending commands', () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    try {
      const html = renderToStaticMarkup(<VisionDeliveryResult initialResult={summary} />)
      expect(html).toContain('J100 视觉配送'); expect(html).toContain('49.90 s')
      expect(html).toContain('3.11 cm'); expect(html).toContain('312 / 226')
      expect(html).toContain('位置回放尚未载入'); expect(html).toContain('已审历史摘要')
      expect(html).not.toContain('<video'); expect(html).not.toContain('/coop-api/start')
      expect(fetcher).not.toHaveBeenCalled()
    } finally { vi.unstubAllGlobals() }
  })
})
