import { useState } from 'react'
import { ArrowUpRight, Box, Camera, Check, FileDown, FlaskConical, Map, RefreshCw, Truck, Video } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardTitle } from '@/components/ui/card'
import type { VoiceController } from '@/lib/voice'
import { VoicePanel } from '@/components/voice/voice-panel'
import { useWorkbenchServices } from '@/hooks/use-workbench-services'
import type { AppRoute } from '@/lib/app-route'
import {
  caseStatusLabels, isWorkbenchLocalHost, selectVisualCases, workbenchSnapshot,
  type Capability, type CaseFilter, type ServiceId,
} from '@/lib/workbench-catalog'
import type { ServiceState } from '@/lib/workbench-services'
import { toolEntry } from '@/lib/workbench-tool-entry'
import './workbench.css'

const flow = [
  { id: 'spatiallm', title: '准备空间', description: '把室内结构变成可编辑场景', icon: Box },
  { id: 'navigation', title: '配置地图与规则', description: '选路线，明确可走与禁行区域', icon: Map },
  { id: 'transport', title: '执行停靠与运输', description: '小车与固定机械臂完成交接', icon: Truck },
  { id: 'video', title: '分析过程', description: '查看候选事件，保留人工复核', icon: Video },
] as const

function CapabilityAction({ capability, onNavigate, services, local }: {
  capability: Capability; onNavigate: (route: AppRoute) => void
  services: Record<ServiceId, ServiceState>; local: boolean
}) {
  const action = capability.action
  if ('route' in action) return <Button type="button" size="sm" variant="outline" onClick={() => onNavigate(action.route)}>{action.label}</Button>
  if ('href' in action) return <Button asChild size="sm" variant="outline"><a href={action.href} target="_blank" rel="noopener noreferrer">{action.label}<ArrowUpRight size={13} aria-hidden="true" /></a></Button>
  const service = services[action.service]
  const entry = toolEntry(action.service)
  const available = local && service.status === 'available' && entry !== null
  return <div className="workbench-tool-action" data-service={action.service} data-service-status={local ? service.status : 'remote-host'}>
    {available ? <Button asChild size="sm" variant="outline"><a href={entry} target="_blank" rel="noopener noreferrer">{action.label}<ArrowUpRight size={13} aria-hidden="true" /></a></Button>
      : <Button type="button" size="sm" variant="outline" disabled>{action.label}</Button>}
    <p className="workbench-service-message" role="status">{local ? service.message : '需在工作台电脑打开；手机的本机地址指向手机自身。'}</p>
    {local && service.checkedAt !== null && <small className="workbench-service-message">检查于 {new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(service.checkedAt)}，可重新检查</small>}
  </div>
}

function CapabilityContent({ capability, onNavigate, services, local }: {
  capability: Capability; onNavigate: (route: AppRoute) => void
  services: Record<ServiceId, ServiceState>; local: boolean
}) {
  return <div className="workbench-capability" id={`workbench-capability-${capability.id}`} data-capability={capability.id}>
    <span className={`workbench-status workbench-status-${capability.status}`}>{capability.statusLabel}</span>
    <h3>{capability.title}</h3>
    <p className="workbench-capability-summary">{capability.summary}</p>
    <ul className="workbench-highlights">{capability.highlights.map((highlight) => <li key={highlight}><Check size={12} aria-hidden="true" />{highlight}</li>)}</ul>
    <p className="workbench-boundary">{capability.boundary}</p>
    <div className="workbench-capability-actions">
      <CapabilityAction capability={capability} onNavigate={onNavigate} services={services} local={local} />
      <a className="workbench-evidence-link" href={capability.evidenceUrl} target="_blank" rel="noopener noreferrer">来源与验收<ArrowUpRight size={12} aria-hidden="true" /></a>
    </div>
  </div>
}

const filters: { key: CaseFilter; label: string; count: number }[] = [
  { key: 'all', label: '全部', count: workbenchSnapshot.visual.total },
  { key: 'failed', label: '未通过', count: workbenchSnapshot.visual.failed },
  { key: 'completed', label: '任务完成', count: workbenchSnapshot.visual.completed },
  { key: 'safe-cancel', label: '正确取消', count: workbenchSnapshot.visual.safeCanceled },
]

export function WorkbenchVisualCases({ filter, onFilterChange }: { filter: CaseFilter; onFilterChange: (filter: CaseFilter) => void }) {
  const cases = selectVisualCases(filter)
  return <div className="workbench-case-browser">
    <div className="workbench-case-toolbar">
      <div className="workbench-case-filters" role="group" aria-label="筛选原56例验收">
        {filters.map((item) => <button type="button" key={item.key} onClick={() => onFilterChange(item.key)} aria-pressed={filter === item.key}>{item.label}<span>{item.count}</span></button>)}
      </div>
      <span className="workbench-case-count" role="status">显示 {cases.length} 条案例</span>
    </div>
    <div className="workbench-case-table-wrap">
      <table className="workbench-case-table">
        <caption className="workbench-sr-only">原56例视觉停靠与完整运输验收明细</caption>
        <thead><tr><th scope="col">案例 / 阶段</th><th scope="col">结果</th><th scope="col">原始原因与评分来源</th></tr></thead>
        <tbody>{cases.map((item) => <tr key={item.id} data-case-id={item.id} data-case-status={item.status}>
          <td className="workbench-case-identity"><strong>{item.label}</strong><span>{item.stage}</span></td>
          <td className="workbench-case-result"><span className={`workbench-outcome workbench-outcome-${item.status}`}>{caseStatusLabels[item.status]}</span></td>
          <td className="workbench-case-reason"><p>{item.reason || (item.status === 'completed' ? '原独立评分记录为任务完成。' : '原独立评分确认正确取消，未计为任务完成。')}</p><details><summary>案例与评分文件指纹</summary><code>{item.id}</code><code>{item.scoreSha256}</code></details></td>
        </tr>)}</tbody>
      </table>
    </div>
  </div>
}

export function WorkbenchPage({ onNavigate, voiceController }: { onNavigate: (route: AppRoute) => void; voiceController?: VoiceController }) {
  const [filter, setFilter] = useState<CaseFilter>('all')
  const { services, checking, refresh } = useWorkbenchServices()
  const local = typeof window !== 'undefined' && isWorkbenchLocalHost(window.location.hostname)
  const snapshot = workbenchSnapshot
  const supporting = snapshot.capabilities.filter((item) => item.id === 'vision' || item.id === 'arena')

  return <main className="station-dashboard workbench-page">
    <header className="station-page-heading workbench-heading">
      <div><h1>成果工作台</h1><p>从空间准备到运输交接，集中查看最近可用的能力与验收。</p></div>
      <div className="workbench-heading-actions">
        <a className="workbench-download" href="#workbench-voice">语音任务</a>
        <a className="workbench-download" href="/workbench/recent-results.json" download="fishbot-recent-results.json"><FileDown size={15} aria-hidden="true" />下载验收快照</a>
      </div>
    </header>

    <div className="workbench-snapshot-note"><span>{snapshot.snapshotLabel}</span><time dateTime={snapshot.updatedAt}>更新于 {snapshot.updatedAt}</time><small>整理范围：{snapshot.period}。当前运行状态到各操作页查看。</small></div>

    <nav className="workbench-quick-links" aria-label="能力快捷入口">
      {snapshot.capabilities.map((item) => <a key={item.id} href={`#workbench-capability-${item.id}`}>{item.title}</a>)}
    </nav>

    <section className="workbench-flow-section" aria-labelledby="workbench-flow-heading">
      <div className="workbench-section-heading"><div><h2 id="workbench-flow-heading">从空间到运输，入口放在一起</h2><p>各工具保留自己的操作与验收；打开操作页后，再显式开始任务。</p></div>
        <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={!local || checking}><RefreshCw size={14} aria-hidden="true" />{checking ? '正在检查本机工具' : '检查本机工具'}</Button>
      </div>
      <ol className="workbench-flow">{flow.map((step, index) => {
        const capability = snapshot.capabilities.find((item) => item.id === step.id)
        if (!capability) return null
        return <li key={step.id} className="workbench-flow-step">
          <div className="workbench-step-heading"><span className="workbench-step-number">{index + 1}</span><step.icon size={20} aria-hidden="true" /><div><h2>{step.title}</h2><p>{step.description}</p></div></div>
          <CapabilityContent capability={capability} onNavigate={onNavigate} services={services} local={local} />
        </li>
      })}</ol>
      {!local && <p className="workbench-local-note">本机编辑器和视频复核台需在运行工作台的电脑打开。这里的快照、报告与工作区导航仍可查看。</p>}
    </section>

    <VoicePanel controller={voiceController} />

    <section className="workbench-supporting" aria-labelledby="workbench-supporting-heading">
      <div className="workbench-section-heading"><div><h2 id="workbench-supporting-heading">验证与反馈</h2><p>停靠感知补相对位姿；组合评测用固定条件检验策略。两者保留各自验收边界。</p></div></div>
      <div className="workbench-supporting-list">{supporting.map((capability) => <div key={capability.id} className="workbench-supporting-row"><div className="workbench-supporting-icon">{capability.id === 'vision' ? <Camera size={21} aria-hidden="true" /> : <FlaskConical size={21} aria-hidden="true" />}</div><CapabilityContent capability={capability} onNavigate={onNavigate} services={services} local={local} /></div>)}</div>
    </section>

    <Card className="workbench-acceptance" aria-labelledby="workbench-acceptance-heading">
      <div className="workbench-section-heading"><div><CardTitle id="workbench-acceptance-heading">独立验收</CardTitle><p>观测质量、原生动作终态和物理任务评分分别记录；网页状态不替代验收。</p></div></div>
      <div className="workbench-panel-heading"><div><h3>原视觉停靠面板 · {snapshot.visual.total} 例</h3><p>{snapshot.visual.shortCount} 次短停靠，{snapshot.visual.fullCount} 次完整运输。正常场景与故障场景分别判定。</p></div><span className="workbench-status workbench-status-partial">严格验收尚未全部通过</span></div>
      <dl className="workbench-verdict-summary">
        <div><dt>任务完成</dt><dd>{snapshot.visual.completed}<span>短停靠 {snapshot.visual.shortCompleted} / 完整运输 {snapshot.visual.fullCompleted}</span></dd></div>
        <div><dt>正确取消</dt><dd>{snapshot.visual.safeCanceled}<span>确认原动作终态与停车，不算任务完成</span></dd></div>
        <div><dt>未通过</dt><dd>{snapshot.visual.failed}<span>保留全部失败，原评分门槛保持</span></dd></div>
      </dl>
      <p className="workbench-acceptance-note">父 / 候选同源码的第二轮是复现；留出数据未用于调参。下方列出全部原案例。</p>
      <details className="workbench-case-details">
        <summary>查看56案例明细与11项未通过原因</summary>
        <WorkbenchVisualCases filter={filter} onFilterChange={setFilter} />
      </details>

      <section className="workbench-workflow-results" aria-labelledby="workbench-workflow-results-heading">
        <div className="workbench-panel-heading"><div><h3 id="workbench-workflow-results-heading">新增同桥作业面板 · {snapshot.workflow.total} 例</h3><p>一次运动取消，恢复后完成两件运输。使用 ideal 工位观测。</p></div><span className="workbench-status workbench-status-verified">该面板独立评分通过</span></div>
        <p className="workbench-acceptance-note">{snapshot.workflow.completed} 次完整运输、{snapshot.workflow.safeCanceled} 次正确取消。此结果不补齐原56例中的11项失败，也不代表纯视觉精度或真机能力。</p>
        <ol className="workbench-workflow-cases">{snapshot.workflow.cases.map((item) => <li key={item.id} data-workflow-case-id={item.id}>
          <div><h4>{item.title}</h4><span className={`workbench-outcome workbench-outcome-${item.outcome}`}>{caseStatusLabels[item.outcome]}</span></div>
          <p>{item.durationSeconds.toFixed(1)} 秒{item.cargoDistanceMeters === null ? ' · 取消后独立确认停稳' : ` · 同一货物运输 ${item.cargoDistanceMeters.toFixed(3)} 米`}</p>
          <details><summary>案例与评分指纹</summary><span>{item.id}</span><code>{item.scoreSha256}</code></details>
        </li>)}</ol>
      </section>
    </Card>

    <section className="workbench-learnings" aria-labelledby="workbench-learnings-heading"><div className="workbench-section-heading"><div><h2 id="workbench-learnings-heading">这次留下的经验</h2></div></div><dl>{snapshot.insights.map((item) => <div key={item.title}><dt>{item.title}</dt><dd>{item.body}</dd></div>)}</dl></section>

    <section className="workbench-next" aria-labelledby="workbench-next-heading"><div className="workbench-section-heading"><div><h2 id="workbench-next-heading">下一步，沿现有成果继续</h2></div></div><ul>{snapshot.nextSteps.map((item) => <li key={item.title}><h3>{item.title}</h3><p>{item.detail}</p></li>)}</ul></section>

    <details className="workbench-provenance"><summary>快照来源与版本</summary><p>交付版本 <code>{snapshot.sourceRevision}</code>。以下指纹绑定原始验收材料；下载的是整理快照，不包含本机运行日志或地图。</p><dl>{snapshot.provenance.map((item) => <div key={item.id}><dt>{item.source}</dt><dd><span>{item.classification}</span><code>{item.sha256}</code></dd></div>)}</dl></details>
  </main>
}
