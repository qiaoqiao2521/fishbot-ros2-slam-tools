import { useState } from 'react'
import { FileUp, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardTitle } from '@/components/ui/card'
import {
  parseSceneValidationReport, readLatestSceneValidationReport, readLocalSceneValidationReport,
  sceneValidationValue, type AcceptanceResult, type BusinessResult, type SceneValidationReport,
} from './scene-validation-report'
import './scene-validation-panel.css'

const businessLabels: Record<BusinessResult, string> = { route_completed: '往返完成', route_incomplete: '往返未完成', delivered: '已交付', undelivered: '未交付', unknown: '待确认' }
const acceptanceLabels: Record<AcceptanceResult, string> = { passed: '通过', failed: '未通过', incomplete: '待补齐' }
const navigationExpectedLabels: Record<string, string> = { delivered: '完成往返', route_completed: '完成往返', canceled: '正确取消', blocked: '禁路正确拒绝' }

export function SceneValidationPanel({ initialReport }: { initialReport?: unknown }) {
  const [report, setReport] = useState<SceneValidationReport | null>(() => initialReport === undefined ? null : parseSceneValidationReport(initialReport))
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function readReport(reader: () => Promise<SceneValidationReport>, successMessage: string) {
    setLoading(true)
    setError('')
    try {
      setReport(await reader())
      setMessage(successMessage)
    } catch (cause) {
      setError(cause instanceof SyntaxError ? 'JSON 无法解析，请修正文件后重新导入。已有报告继续保留。'
        : cause instanceof Error ? cause.message : '报告读取失败，请重试或导入本地 JSON。')
    } finally {
      setLoading(false)
    }
  }

  return <Card className="scene-validation-panel" aria-labelledby="scene-validation-heading">
    <div className="scene-validation-heading">
      <div><CardTitle id="scene-validation-heading">场景业务验证</CardTitle><p>分别查看业务结果与案例验收。读取报告不会启动或重放机器人任务。</p></div>
      <div className="scene-validation-actions">
        <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void readReport(() => readLatestSceneValidationReport(), '已读取最新报告。')}><RefreshCw size={14} aria-hidden="true" />{loading ? '正在读取' : '读取最新报告'}</Button>
        <label className={`scene-validation-import${loading ? ' scene-validation-import-disabled' : ''}`}><FileUp size={14} aria-hidden="true" />导入 JSON
          <input type="file" accept=".json,application/json" disabled={loading} aria-label="导入场景业务验证 JSON" onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (file) void readReport(() => readLocalSceneValidationReport(file), `已导入 ${file.name}。`)
          }} />
        </label>
      </div>
    </div>
    {message && <p className="scene-validation-feedback" role="status">{message}</p>}
    {error && <p className="scene-validation-error" role="alert">{error}</p>}
    {!report ? <p className="scene-validation-empty">尚未读取报告。可以读取最近一次仿真结果，或导入经过人工编辑的 JSON。</p> : <>
      <dl className="scene-validation-source">
        <div><dt>报告来源</dt><dd>{report.source.label}<span>{report.scope === 'simulation' ? '仿真验证' : `范围：${report.scope}`}</span></dd></div>
        <div><dt>场景依据</dt><dd>{report.source.basis === 'synthetic_reference' ? '合成参考场景，尚未现场实测' : report.source.basis}</dd></div>
        <div><dt>补全与假设</dt><dd>{report.source.assumptionCells}</dd></div>
        <div><dt>雷达配置</dt><dd>{report.lidarProfile}</dd></div>
      </dl>
      {report.businessScope === 'navigation_roundtrip' && <p className="scene-validation-explanation">本轮验证路线，不包含货物交接与收货签收。</p>}
      {report.warnings.length > 0 && <div className="scene-validation-warnings" role="status"><strong>报告提示</strong><ul>{report.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
      <p className="scene-validation-explanation">“验收通过”表示符合该案例预期。禁路拒绝或正确取消时，{report.businessScope === 'navigation_roundtrip' ? '往返仍可能未完成' : '业务仍可能未交付'}。</p>
      {report.cases.length === 0 ? <p className="scene-validation-empty">当前报告没有案例。保留已有来源信息，补齐 cases 后可重新导入。</p> : <table className="scene-validation-table">
        <caption>场景业务案例，共 {report.cases.length} 条</caption>
        <thead><tr><th scope="col">案例 / 预期</th><th scope="col">业务结果</th><th scope="col">案例验收</th><th scope="col">原因与指标</th></tr></thead>
        <tbody>{report.cases.map((item, index) => <tr key={`${index}-${item.id}`} data-scene-case-id={item.id}>
          <td data-label="案例 / 预期"><strong>{item.label}</strong><span className="scene-validation-expected">{report.businessScope === 'navigation_roundtrip' ? navigationExpectedLabels[item.expected] ?? item.expected : item.expected}</span></td>
          <td data-label="业务结果"><span className={`scene-validation-result scene-validation-business-${item.businessResult}`}>{businessLabels[item.businessResult]}</span></td>
          <td data-label="案例验收"><span className={`scene-validation-result scene-validation-acceptance-${item.acceptanceResult}`}>{acceptanceLabels[item.acceptanceResult]}</span></td>
          <td data-label="原因与指标"><p>{item.reason}</p><details><summary>展开原任务与主要指标</summary>
            <dl className="scene-validation-metrics"><div><dt>案例 ID</dt><dd>{item.id}</dd></div><div><dt>原任务 UUID</dt><dd>{item.taskId}</dd></div><div><dt>原生动作 UUID</dt><dd>{item.nativeGoalId}</dd></div><div><dt>原生动作状态</dt><dd>{item.nativeStatus}</dd></div>
              {Object.entries(item.metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{sceneValidationValue(value)}</dd></div>)}
            </dl>
          </details></td>
        </tr>)}</tbody>
      </table>}
      <p className="scene-validation-scope-note">此处展示仿真业务验证，不代表真机或 sim-to-real 已通过。</p>
    </>}
  </Card>
}
