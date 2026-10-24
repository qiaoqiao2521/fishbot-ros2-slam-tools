import { useEffect, useMemo, useRef, useState } from 'react'
import { FileDown, FileUp, Pause, Play, RefreshCw } from 'lucide-react'
import { commonAnchors, distribution, parseDeliveryComparison, readComparison, replayFrame, replayPath, runDuration,
  type ReplayFrame, type ReplayReport, type ReplayRun } from '@/lib/delivery-comparison'
import './regression-page.css'

const seconds = (v: number | null) => v === null ? '未知' : `${v.toFixed(3)} s`
const metric = (v: number | null, unit: string, scale = 1) => v === null ? '未知' : `${(v * scale).toFixed(2)} ${unit}`
const anchorName = (name: string) => name === 'route' ? '配送路线开始' : name === 'recording' ? '记录开始' : name.replace('stage:', '阶段：')
const groupName = (name: string) => ({ baseline: '基线', candidate: '候选', replication: '同配置复现', holdout: '留出', unassigned: '未分组' }[name] ?? name)
const coords = (points: number[][]) => points.map(p => `${p[0]},${-p[1]}`).join(' ')

function Vehicle({ frame, report, color, ghost = false }: { frame: ReplayFrame | null; report: ReplayReport; color: string; ghost?: boolean }) {
  if (!frame) return null
  const q = frame.quaternion
  const yaw = q ? Math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2)) : null
  return <g opacity={ghost ? .32 : 1} data-replay-ghost={ghost || undefined}>
    {frame.car && <g transform={`translate(${frame.car[0]},${-frame.car[1]}) rotate(${-(yaw ?? 0) * 180 / Math.PI})`}>
      {report.footprint.length > 2 && yaw !== null ? <polygon points={coords(report.footprint)} fill={color} fillOpacity='.17' stroke={color} strokeWidth='.018' /> : <circle r='.025' fill={color} />}
      {yaw !== null && <path d='M0,0 L.12,0 M.09,-.025 L.12,0 L.09,.025' fill='none' stroke={color} strokeWidth='.018' />}
    </g>}
    {frame.joints.length > 1 && <><polyline points={coords(frame.joints)} fill='none' stroke={color} strokeWidth='.018' />{frame.joints.map((p, i) => <circle key={i} cx={p[0]} cy={-p[1]} r='.014' fill={color} />)}</>}
    {frame.cargo && <g transform={`translate(${frame.cargo[0]},${-frame.cargo[1]})`}><circle r='.022' fill='#c4781a' stroke='#fff' strokeWidth='.007' /><path d='M-.05,0 H.05 M0,-.05 V.05' stroke='#c4781a' strokeWidth='.008' /></g>}
  </g>
}

function ReplayViewport({ report, run, other, elapsed, anchor, color, ghost }: {
  report: ReplayReport; run: ReplayRun; other: ReplayRun | undefined; elapsed: number; anchor: string; color: string; ghost: boolean
}) {
  const path = useMemo(() => replayPath(run), [run])
  const frame = replayFrame(run, elapsed, anchor), second = other ? replayFrame(other, elapsed, anchor) : null
  const [x0, y0, x1, y1] = report.bounds
  return <section className='regression-viewport' aria-label={`${run.label} 回放`}>
    <header><div><strong style={{ color }}>{run.label}</strong><small>{run.scope === 'route' ? '载货路线切片' : run.scope === 'transport' ? '完整运输' : '范围未确认'} · {groupName(run.group)}</small></div>
      <span className={`regression-verdict regression-verdict-${run.passed === true ? 'pass' : run.passed === false ? 'fail' : 'unknown'}`}>{run.passed === true ? '原独立评分通过' : run.passed === false ? '原独立评分未通过' : '评分未知'}</span></header>
    <svg viewBox={`${x0} ${-y1} ${x1 - x0} ${y1 - y0}`} role='img' aria-label={`${run.label} 原世界坐标轨迹`}>
      <rect x={x0} y={-y1} width={x1 - x0} height={y1 - y0} fill='#f7f9fc' />
      <path d={`M${x0},0 H${x1} M0,${-y1} V${-y0}`} stroke='#dce4ed' strokeWidth='.009' />
      {report.boxes.map((b, i) => <rect key={i} x={-b.size[0]} y={-b.size[1]} width={b.size[0] * 2} height={b.size[1] * 2}
        transform={`translate(${b.position[0]},${-b.position[1]}) rotate(${-b.yaw * 180 / Math.PI})`} fill='#c4cdd8' stroke='#8b9aaa' strokeWidth='.008'><title>{b.id}</title></rect>)}
      <path d={path} fill='none' stroke={color} strokeWidth='.015' opacity='.45' />
      {ghost && <Vehicle frame={second} report={report} color={color === '#2465da' ? '#178765' : '#2465da'} ghost />}
      <Vehicle frame={frame} report={report} color={color} />
    </svg>
    <div className='regression-sample' aria-live='off'>{frame ? <><span>源时间 {frame.source.toFixed(3)} s · 序号 {frame.sequence ?? '未知'}</span><span>{frame.stage === 'unknown' ? '阶段未知' : frame.stage} · {frame.hold === true ? '车辆保持' : frame.hold === false ? '车辆释放' : '保持状态未知'}</span>
      <span>货物高度 {frame.cargo ? `${frame.cargo[2].toFixed(3)} m` : '未知'}</span></> : <span className='regression-gap'>此时无有效采样；缺口保持空白。</span>}</div>
    <dl><div><dt>路线 / 原预算</dt><dd>{seconds(run.routeSeconds)} / {seconds(run.budget)}</dd></div><div><dt>末位置 / 偏航误差</dt><dd>{metric(run.positionError, 'cm', 100)} / {metric(run.yawError, 'rad')}</dd></div>
      <div><dt>缺失物理序号 / 保护介入</dt><dd>{run.missing ?? '未知'} / {seconds(run.guardSeconds)}</dd></div></dl>
    <details><summary>原任务与机械臂读数</summary><p>任务 {run.taskId}<br />回合 {run.episodeId}<br />检查点 {run.snapshot ?? '未知'}</p><p>机械臂 q6：{frame?.q6?.map(n => n.toFixed(3)).join(', ') ?? '当前无读数'} rad</p>
      {run.nativeActions.map(action => <p key={action.uuid}>{action.label} · 原生终态 {action.status ?? '未知'}<br /><code>{action.uuid}</code></p>)}
      <p>关节线框来自记录 q6 的正运动学投影；路径与车辆外廓用于显示，原物理评分保持。</p>{run.warnings.map((s, i) => <p key={i}>{s}</p>)}</details>
  </section>
}

function Distribution({ runs }: { runs: ReplayRun[] }) {
  const groups = [...new Set(runs.map(r => r.group))]
  return <section className='regression-distribution'><h2>保留每一次结果</h2><table><thead><tr><th>组别</th><th>通过 / 总数</th><th>耗时 P50</th><th>耗时 P95</th><th>最小 ～ 最大</th><th>缺指标</th></tr></thead><tbody>{groups.map(group => {
    const rows = runs.filter(r => r.group === group), d = distribution(rows.map(r => r.routeSeconds))
    return <tr key={group}><th scope='row'>{groupName(group)}</th><td>{rows.filter(r => r.passed === true).length} / {rows.length}</td><td>{seconds(d.median)}</td><td>{seconds(d.p95)}</td><td>{seconds(d.min)} ～ {seconds(d.max)}</td><td>{d.missing}</td></tr>
  })}</tbody></table><p>耗时保留失败回合，缺失值不填零。分位数采用最近秩；有限重复不代表泛化成功率。</p></section>
}

export function RegressionPage({ initialReport }: { initialReport?: unknown }) {
  const [report, setReport] = useState<ReplayReport | null>(() => initialReport === undefined ? null : parseDeliveryComparison(initialReport))
  const [left, setLeft] = useState(0), [right, setRight] = useState(1), [anchor, setAnchor] = useState('route')
  const [elapsed, setElapsed] = useState(0), [playing, setPlaying] = useState(false), [ghost, setGhost] = useState(true)
  const [error, setError] = useState(''), [loading, setLoading] = useState(false)
  const generation = useRef(0), request = useRef<AbortController | null>(null)
  async function load(file?: File) {
    const current = ++generation.current; request.current?.abort()
    const controller = new AbortController(); request.current = controller
    setLoading(true); setError(''); setPlaying(false)
    try {
      let value: ReplayReport
      if (file) value = await readComparison(file)
      else {
        const response = await fetch('/workbench/continuous-comparison.json', { method: 'GET', cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(`尚无可读取的对照摘要（HTTP ${response.status}）。可导入本地 comparison.json。`)
        value = parseDeliveryComparison(await response.json())
      }
      if (generation.current !== current) return
      setReport(value); setLeft(0); setRight(Math.min(1, Math.max(0, value.runs.length - 1))); setElapsed(0)
      setAnchor(commonAnchors(value.runs.slice(0, 2)).includes('route') ? 'route' : 'recording')
    } catch (cause) { if (!controller.signal.aborted && generation.current === current) setError(cause instanceof Error ? cause.message : '读取失败；已有报告保持。') }
    finally { if (generation.current === current) setLoading(false) }
  }
  useEffect(() => { if (initialReport === undefined) void load(); return () => { generation.current++; request.current?.abort() } }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const a = report?.runs[left], b = report?.runs[right]
  const selected = [a, b].filter((r): r is ReplayRun => r !== undefined)
  const anchors = commonAnchors(selected), validAnchor = anchors.includes(anchor) ? anchor : anchors[0] ?? 'recording'
  const duration = Math.max(0, ...selected.map(r => runDuration(r, validAnchor)))
  useEffect(() => {
    if (!playing) return
    let previous = performance.now()
    const timer = window.setInterval(() => {
      const now = performance.now(), dt = (now - previous) / 1000; previous = now
      setElapsed(value => { const next = Math.min(duration, value + dt); if (next >= duration) setPlaying(false); return next })
    }, 100)
    return () => window.clearInterval(timer)
  }, [playing, duration])
  function download() {
    if (!report) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(report.source)], { type: 'application/json' })), link = document.createElement('a')
    link.href = url; link.download = 'comparison.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  const compatible = report?.sameScene && report.sameSnapshot
  const currentA = a ? replayFrame(a, elapsed, validAnchor) : null, currentB = b ? replayFrame(b, elapsed, validAnchor) : null
  const separation = currentA?.car && currentB?.car ? Math.hypot(currentA.car[0] - currentB.car[0], currentA.car[1] - currentB.car[1]) : null
  return <main className='regression-page'>
    <header className='regression-heading'><div><h1>配送回归</h1><p>看原生任务怎样走，也看它在哪里失败。</p></div><div className='regression-actions'>
      <button disabled={loading} onClick={() => void load()}><RefreshCw size={15} />刷新报告</button><label><FileUp size={15} />导入对照<input type='file' accept='.json,application/json' aria-label='导入配送对照 JSON' onChange={e => { const file = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (file) void load(file) }} /></label>
      <button disabled={!report} onClick={download}><FileDown size={15} />下载摘要</button></div></header>
    {error && <p role='alert' className='regression-warning'>{error}</p>}
    {!report ? <p role='status'>{loading ? '读取对照摘要…' : '导入两个回合的 comparison.json 后查看。'}</p> : <>
      <div className='regression-provenance'><strong>{compatible ? '同一检查点 · 同一几何场景' : '来源未满足同起点 A/B 对照'}</strong><span>历史仿真记录 · 未重新执行或评分 · 原世界坐标</span></div>
      {!compatible && <p className='regression-warning'>两个回合可以分别查看；来源不同，不据此宣称参数带来改进。Ghost 已停用。</p>}
      {report.warnings.map((s, i) => <p className='regression-warning' key={i}>{s}</p>)}
      <div className='regression-selection'>{(['左侧回合', '右侧回合'] as const).map((name, i) => <label key={name}>{name}<select aria-label={name} value={i ? right : left} onChange={e => { (i ? setRight : setLeft)(Number(e.target.value)); setPlaying(false); setElapsed(0) }}>{report.runs.map((run, n) => <option key={run.id} value={n}>{run.label}</option>)}</select></label>)}
        <label>时间锚点<select aria-label='时间锚点' value={validAnchor} onChange={e => { setAnchor(e.target.value); setElapsed(0); setPlaying(false) }}>{anchors.map(name => <option key={name} value={name}>{anchorName(name)}</option>)}</select></label>
        <label className='regression-ghost'><input type='checkbox' checked={ghost && Boolean(compatible)} disabled={!compatible} onChange={e => setGhost(e.target.checked)} />叠加另一回合</label></div>
      <div className='regression-viewports'>{a && <ReplayViewport report={report} run={a} other={b} elapsed={elapsed} anchor={validAnchor} color='#2465da' ghost={ghost && Boolean(compatible)} />}
        {b && <ReplayViewport report={report} run={b} other={a} elapsed={elapsed} anchor={validAnchor} color='#178765' ghost={ghost && Boolean(compatible)} />}</div>
      <div className='regression-timeline'><button aria-label={playing ? '暂停回放' : '播放回放'} disabled={!duration} onClick={() => { if (elapsed >= duration) setElapsed(0); setPlaying(value => !value) }}>{playing ? <Pause size={17} /> : <Play size={17} />}{playing ? '暂停' : '播放'}</button>
        <input type='range' min='0' max={Math.max(.1, duration)} step='.02' value={elapsed} aria-label='共享源时间轴' onChange={e => { setPlaying(false); setElapsed(Number(e.target.value)) }} />
        <output>{elapsed.toFixed(2)} / {duration.toFixed(2)} s</output></div>
      <p className='regression-note'>按源时间相对锚点同步。只选择真实采样；缺口不插值，不平移轨迹。播放、刷新和切页均不派发任务。</p>
      <p className='regression-note'>当前车辆距离：{metric(separation, 'cm', 100)}；{compatible ? '原世界坐标直接比较。' : '来源不同，仅供查看，不代表参数改进。'}</p>
      <Distribution runs={report.runs} />
    </>}
  </main>
}
