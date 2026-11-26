import { useState } from 'react'
import { FileDown, ExternalLink } from 'lucide-react'
import catalog from '../../../public/workbench/delivery-results.json'
import { VisionDeliveryResult } from './vision-delivery-result'
import './delivery-results-gallery.css'

// Curated completed runs, with their original reports and media kept intact.
// Historical acceptance and partial experiments remain available below.
const currentResultIds = ['f2-warehouse-local-183948', 'f2-workshop-local-193522']

export function DeliveryResultsGallery() {
  const [selected, setSelected] = useState(currentResultIds[0])
  const [vehicle, setVehicle] = useState('all'), [sensor, setSensor] = useState('all')
  const groups = catalog.groups.filter(group => (vehicle === 'all' || group.vehicle === vehicle) && (sensor === 'all' || group.sensor === sensor))
  const experiments = catalog.experiments.filter(item => (vehicle === 'all' || item.vehicle === vehicle) && (sensor === 'all' || item.sensor === sensor))
  const completed = currentResultIds.flatMap(id => experiments.filter(item => item.id === id))
  const research = experiments.filter(item => !currentResultIds.includes(item.id))
  const current = [...completed, ...groups, ...research].find(item => item.id === selected) ?? completed[0] ?? groups[0] ?? research[0]
  function chooseResult(id: string) {
    setSelected(id)
    document.getElementById('selected-delivery-result')?.scrollIntoView({ block: 'start' })
  }
  return <section id="delivery-results-gallery" aria-labelledby="delivery-results-heading">
    <header className="delivery-gallery-heading"><div><h2 id="delivery-results-heading">配送成果 · 当前完整回合</h2><p>先看已完成的两单配送，再展开历史配置与失败研究。选择记录只读取保存资料。</p></div><a href="/workbench/delivery-results.json" download><FileDown size={15} aria-hidden="true" />下载资料目录</a></header>
    <div className="delivery-gallery-filters"><label>车型<select aria-label="筛选成果车型" value={vehicle} onChange={event => setVehicle(event.target.value)}><option value="all">全部车型</option><option value="j100">J100</option><option value="mecanum">麦克纳姆</option></select></label><label>雷达<select aria-label="筛选成果雷达" value={sensor} onChange={event => setSensor(event.target.value)}><option value="all">全部雷达</option><option value="2d">2D 雷达</option><option value="3d">3D 雷达</option></select></label><span role="status">{completed.length} 个当前完整回合 · {groups.length} 组历史配置 · {research.length} 项过程记录</span></div>
    {completed.length > 0 && <div className="delivery-gallery-groups delivery-gallery-current" role="group" aria-label="选择当前完整配送回合">{completed.map(item => <button key={item.id} type="button" data-result-experiment={item.id} data-current-result={item.id} aria-pressed={item.id === current?.id} onClick={() => chooseResult(item.id)}><strong>{item.title}</strong><span>{item.configuration}</span><small>{item.coverage}</small><small>{item.materials}</small></button>)}</div>}
    {!current ? <p className="vision-result-notice" role="status">没有符合当前筛选的组合。这里保留实际已验配置，不补造其他组合。</p> : <div id="selected-delivery-result" data-selected-result={current.id}><VisionDeliveryResult key={current.id} initialUrl={current.source} /></div>}
    <details className="delivery-gallery-history"><summary>历史配置与已验成果（{groups.length} 组）</summary><p>保留原回合的评分、素材完整度与重置记录；这些历史结果不被新回合覆盖。</p><div className="delivery-gallery-groups" role="group" aria-label="选择配送成果组">{groups.map(group => <button key={group.id} type="button" data-result-group={group.id} aria-pressed={group.id === current?.id} onClick={() => chooseResult(group.id)}><strong>{group.title}</strong><span>{group.configuration}</span><small>{group.coverage}</small><small>{group.materials}</small></button>)}</div></details>
    {research.length > 0 && <details className="delivery-gallery-experiments"><summary>失败与分阶段实验（{research.length} 项）</summary><p>原失败、部分成功与采集结果逐项保留，按各自报告解释。</p><div className="delivery-gallery-groups" role="group" aria-label="选择新场景实验">{research.map(item => <button key={item.id} type="button" data-result-experiment={item.id} aria-pressed={item.id === current?.id} onClick={() => chooseResult(item.id)}><strong>{item.title}</strong><span>{item.configuration}</span><small>{item.coverage}</small><small>{item.materials}</small></button>)}</div></details>}
    <details className="delivery-gallery-archives"><summary>Drive 原件与恢复入口</summary><p>{catalog.scope}。报告、位置回放和录像是不同材料；缺失原件不能由摘要还原。</p>{catalog.archives.map(archive => <a key={archive.url} href={archive.url} target="_blank" rel="noopener noreferrer">{archive.label}<ExternalLink size={13} aria-hidden="true" /></a>)}</details>
  </section>
}
