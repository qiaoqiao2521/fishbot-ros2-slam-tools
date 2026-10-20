import { useState } from 'react'
import { RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardTitle } from '@/components/ui/card'
import './hardware-lab-panel.css'

import { parseHardwareLabReport, readHardwareLabReport, type HardwareLabReport, hardwareLabMetric } from './hardware-lab-report'

const statusLabels = { passed: '通过', failed: '未通过', incomplete: '待补齐' }

export function HardwareLabPanel({ initialReport }: { initialReport?: unknown }) {
  const [report, setReport] = useState<HardwareLabReport | null>(() => initialReport === undefined ? null : parseHardwareLabReport(initialReport))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function readReport() {
    setLoading(true)
    setError('')
    try {
      setReport(await readHardwareLabReport(report))
      setMessage('已读取本次实验报告。')
    } catch (cause) {
      setError(cause instanceof SyntaxError ? '实验报告 JSON 无法解析。已有报告继续保留，修正文件后可重新读取。'
        : cause instanceof Error ? cause.message : '实验报告暂时无法读取。已有报告继续保留。')
    } finally {
      setLoading(false)
    }
  }

  return <Card className="hardware-lab-panel" aria-labelledby="hardware-lab-heading">
    <div className="hardware-lab-heading">
      <div><CardTitle id="hardware-lab-heading">场景与硬件实验</CardTitle><p>查看实测地图、新底盘与负压实验的独立结果。</p></div>
      <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void readReport()}><RefreshCw size={14} aria-hidden="true" />{loading ? '正在读取实验报告' : '读取实验报告'}</Button>
    </div>
    <p className="hardware-lab-boundary">三项分别验收，不代表组合爬壁运输或真机通过。读取报告不会启动机器人。</p>
    {message && <p className="hardware-lab-message" role="status">{message}</p>}
    {error && <p className="hardware-lab-error" role="alert">{error}</p>}
    {!report ? <p className="hardware-lab-empty">尚未读取实验报告。点击“读取实验报告”查看保留的实际案例。</p> : <>
      {report.warnings.length > 0 && <div className="hardware-lab-warnings" role="status"><strong>报告提示</strong><ul>{report.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
      <div className="hardware-lab-sections">{report.sections.map((section) => <section className={`hardware-lab-section hardware-lab-section-${section.id}`} key={section.id} aria-labelledby={`hardware-lab-${section.id}`}>
        <div className="hardware-lab-section-title"><h3 id={`hardware-lab-${section.id}`}>{section.title}</h3><span className={`hardware-lab-status hardware-lab-status-${section.status}`}>{statusLabels[section.status]}</span></div>
        <p className="hardware-lab-summary">{section.summary}</p>
        <p className="hardware-lab-basis"><span>依据</span>{section.basis}</p>
        {section.retained && <p className="hardware-lab-retained">包含上次读取的证据，本次缺失部分尚未更新。</p>}
        {section.cases.length === 0 ? <p className="hardware-lab-case-empty">该分项尚无案例。</p> : <ul className="hardware-lab-cases">{section.cases.map((item, index) => <li key={`${index}-${item.id}`} data-hardware-case-id={item.id}>
          <div className="hardware-lab-case-title"><strong>{item.label}</strong><span className={`hardware-lab-status hardware-lab-status-${item.status}`}>{statusLabels[item.status]}</span></div>
          <p>{item.reason}</p>
          <details><summary>查看案例指标</summary><dl><div><dt>案例 ID</dt><dd>{item.id}</dd></div>{Object.entries(item.metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{hardwareLabMetric(value)}</dd></div>)}</dl></details>
        </li>)}</ul>}
      </section>)}</div>
    </>}
  </Card>
}
