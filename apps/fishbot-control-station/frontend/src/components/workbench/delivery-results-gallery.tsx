import { useState } from 'react'
import { FileDown, ExternalLink } from 'lucide-react'
import catalog from '../../../public/workbench/delivery-results.json'
import { VisionDeliveryResult } from './vision-delivery-result'
import './delivery-results-gallery.css'

export function DeliveryResultsGallery() {
  const [selected, setSelected] = useState('j100-vision')
  const [vehicle, setVehicle] = useState('all'), [sensor, setSensor] = useState('all')
  const groups = catalog.groups.filter(group => (vehicle === 'all' || group.vehicle === vehicle) && (sensor === 'all' || group.sensor === sensor))
  const current = groups.find(group => group.id === selected) ?? groups[0]
  return <section id="delivery-results-gallery" aria-labelledby="delivery-results-heading">
    <header className="delivery-gallery-heading"><div><h2 id="delivery-results-heading">四组配送成果</h2><p>同一套任务接口，保留每种底盘、雷达与观测方式的实际结果。</p></div><a href="/workbench/delivery-results.json" download><FileDown size={15} aria-hidden="true" />下载资料目录</a></header>
    <div className="delivery-gallery-filters"><label>车型<select aria-label="筛选成果车型" value={vehicle} onChange={event => setVehicle(event.target.value)}><option value="all">全部车型</option><option value="j100">J100</option><option value="mecanum">麦克纳姆</option></select></label><label>雷达<select aria-label="筛选成果雷达" value={sensor} onChange={event => setSensor(event.target.value)}><option value="all">全部雷达</option><option value="2d">2D 雷达</option><option value="3d">3D 雷达</option></select></label><span role="status">{groups.length} / 4 组成果 · 仅查看已保存资料</span></div>
    <div className="delivery-gallery-groups" role="group" aria-label="选择配送成果组">{groups.map(group => <button key={group.id} type="button" data-result-group={group.id} aria-pressed={group.id === current?.id} onClick={() => setSelected(group.id)}><strong>{group.title}</strong><span>{group.configuration}</span><small>{group.coverage}</small><small>{group.materials}</small></button>)}</div>
    {!current ? <p className="vision-result-notice" role="status">没有符合当前筛选的组合。这里保留实际已验配置，不补造其他组合。</p> : <VisionDeliveryResult key={current.id} initialUrl={current.source} />}
    <details className="delivery-gallery-archives"><summary>Drive 原件与恢复入口</summary><p>{catalog.scope}。报告、位置回放和录像是不同材料；缺失原件不能由摘要还原。</p>{catalog.archives.map(archive => <a key={archive.url} href={archive.url} target="_blank" rel="noopener noreferrer">{archive.label}<ExternalLink size={13} aria-hidden="true" /></a>)}</details>
  </section>
}
