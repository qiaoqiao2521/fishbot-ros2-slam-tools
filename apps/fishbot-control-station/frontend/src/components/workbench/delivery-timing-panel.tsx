import { useEffect, useRef, useState } from 'react'
import { FileDown, FileUp, RefreshCw, Timer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardTitle } from '@/components/ui/card'
import { parseDeliveryTiming, readDeliveryTiming, readLocalDeliveryTiming, timingWindow, type DeliveryTimingSource, type TimingSpan } from '@/lib/delivery-timing'
import './delivery-timing-panel.css'

const seconds = (value: number | null, decimals = 3) => value === null ? '未知' : `${value.toFixed(decimals)} s`
const phases: Record<string, string> = {
  car_to_dock: '驶向工位', docking: '工位停靠', car_hold: '小车保持', arm_approach: '机械臂接近',
  arm_descend: '机械臂下降', arm_grasp: '双指抓取', arm_lift: '抬升货物', arm_move: '机械臂搬运',
  arm_place: '托盘放置', arm_release: '释放货物', arm_retreat: '机械臂退让', arm_home: '机械臂回位',
  car_egress: '小车离站', car_to_delivery: '驶向交付点', delivery_stop: '交付点停稳', completed: '任务完成',
  dock_stopped: '工位停稳', arm_transport: '机械臂搬运', cargo_settle: '货物落稳', delivery_stopped: '交付点停稳',
}
const label = (s: TimingSpan) => phases[s.label] ?? s.label
const boundary = (values: (number | null)[], origin: number | null) => values.length && origin !== null
  ? values.map(v => v === null ? '未知' : `${(v - origin).toFixed(3)}s`).join(' ～ ') : '未提供精确边界'

export function DeliveryTimingPanel({ initialReport }: { initialReport?: unknown }) {
  const [report, setReport] = useState(() => initialReport === undefined ? null : parseDeliveryTiming(initialReport))
  const [caseIndex, setCaseIndex] = useState(0)
  const [mode, setMode] = useState<'route' | 'task'>('route')
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(initialReport === undefined)
  const [source, setSource] = useState<DeliveryTimingSource>('j100')
  const request = useRef<AbortController | null>(null)
  const generation = useRef(0)

  async function load(local?: File, selectedSource = source) {
    const current = ++generation.current
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setLoading(true); setError('')
    try {
      const next = local ? await readLocalDeliveryTiming(local) : await readDeliveryTiming(controller.signal, fetch, selectedSource)
      if (current !== generation.current) return
      setReport(next); setCaseIndex(0); setSelected(null)
    } catch (cause) {
      if (controller.signal.aborted || current !== generation.current) return
      setError(cause instanceof SyntaxError ? 'JSON 无法解析，请修正后重试。已有报告继续保留。' : cause instanceof Error ? cause.message : '报告读取失败。')
    } finally {
      if (current === generation.current) setLoading(false)
    }
  }
  useEffect(() => {
    if (initialReport === undefined) void load()
    return () => { generation.current += 1; request.current?.abort() }
    // initialReport seeds the panel once; report loading is explicit after mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function download() {
    if (!report) return
    // Download the readable source snapshot, not a new score or live run.
    const anchor = document.createElement('a')
    const url = URL.createObjectURL(new Blob([JSON.stringify(report.source, null, 2)], { type: 'application/json' }))
    anchor.href = url
    anchor.download = 'fishbot-delivery-timing.json'
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  const item = report?.cases[caseIndex]
  const view = item ? timingWindow(item, mode) : null
  const detail = view?.spans.find(s => s.id === selected)
  const chartPercent = (wall: number) => view?.origin === null || !view ? 0 : Math.max(0, Math.min(100, (wall - view.origin) / view.limit * 100))
  return <Card className="delivery-timing-panel" id="workbench-delivery-timing" aria-labelledby="delivery-timing-heading">
    <div className="delivery-timing-heading"><div><span className="delivery-timing-eyebrow"><Timer size={14} aria-hidden="true" />F1 配送 · 时间分析</span>
      <CardTitle id="delivery-timing-heading">120 秒，花在了哪里</CardTitle><p>原生动作、阶段采样与独立物理结果放在同一时间轴，保留各自含义。</p></div>
      <div className="delivery-timing-actions"><label>配送记录<select aria-label="选择配送记录" value={source} disabled={loading} onChange={event => { const value = event.target.value as DeliveryTimingSource; setSource(value); void load(undefined, value) }}><option value="j100">J100 · 原完整 K</option><option value="mecanum">麦克纳姆 · P2 历史</option><option value="mecanum2d">麦克纳姆 · 2D 回归</option><option value="mecanum3d">麦克纳姆 · 3D 雷达</option></select></label>
        <Button size="sm" variant="outline" disabled={loading} onClick={() => void load()}><RefreshCw size={14} aria-hidden="true" />{loading ? '读取中' : '刷新报告'}</Button>
        <label className="delivery-timing-upload"><FileUp size={14} aria-hidden="true" />导入 JSON<input type="file" accept=".json,application/json" aria-label="导入配送耗时 JSON" onChange={e => { const file = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (file) void load(file) }} /></label></div>
    </div>
    {error && <p role="alert" className="delivery-timing-warning">{error}</p>}
    {!report ? <p role="status">{loading ? '正在读取历史耗时报告…' : '暂无报告。可刷新或导入本地摘要。'}</p> : <>
      <div className="delivery-timing-provenance"><strong>{report.label}</strong><span>{report.historical && report.new_execution === false && report.rescored === false ? '历史仿真导入 · 未新执行或重评分' : '来源边界待确认'}</span></div>
      {report.warnings.length > 0 && <ul className="delivery-timing-warning">{report.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
      <div className="delivery-timing-toolbar"><div role="group" aria-label="选择配送订单">{report.cases.map((c, i) => <button type="button" key={`${c.id}-${i}`} aria-pressed={i === caseIndex} onClick={() => { setCaseIndex(i); setSelected(null) }}>{c.label.replace('order-', '订单 ').toUpperCase()}</button>)}</div>
        <div role="group" aria-label="时间预算范围"><button type="button" aria-pressed={mode === 'route'} onClick={() => { setMode('route'); setSelected(null) }}>配送路线</button><button type="button" aria-pressed={mode === 'task'} onClick={() => { setMode('task'); setSelected(null) }}>完整任务</button></div></div>
      {!item || !view ? <p>当前报告没有可展示案例，请补齐 cases 后重新导入。</p> : <>
        <dl className="delivery-timing-metrics"><div><dt>{mode === 'route' ? '配送路线耗时' : '完整任务耗时'}</dt><dd><span>{seconds(view.elapsed)}</span><small>原预算 {seconds(view.budget, 0)}</small></dd></div>
          <div className={item.route.remaining_s !== null && item.route.remaining_s < 1 ? 'delivery-timing-tight' : ''}><dt>路线预算余量</dt><dd><span>{seconds(item.route.remaining_s)}</span><small>出站完成后起算，包含最终停稳确认</small></dd></div>
          <div><dt>原独立评分</dt><dd>{item.original_passed === true ? '通过' : item.original_passed === false ? '未通过' : '待确认'}<small>本次导入：{item.import_status === 'complete' ? '完整' : item.import_status === 'partial' ? '存在缺项' : '未知'}</small></dd></div></dl>
        <div className="delivery-timing-chart-heading"><p>{mode === 'route' ? '仅展示配送预算内的原生动作与未细分间隔。离站不占此预算。' : '阶段起止来自 HTTP 采样；原生离站与配送汇总单独列出，重叠行不相加。'}</p><span>点击条目查看来源</span></div>
        {view.origin === null ? <p className="delivery-timing-warning">缺少起点时间，保留指标，暂不绘制时间轴。</p> : <div className="delivery-timing-scroll" tabIndex={0} aria-label="配送耗时瀑布图，可横向滚动">
          <div className="delivery-timing-chart">
            <div className="delivery-timing-axis"><span>墙钟接收区间</span><div>{[0, 1, 2, 3, 4].map(n => <span key={n} style={{ left: `${n * 24}%` }}>{seconds(view.limit * n * .24, 0)}</span>)}</div></div>
            {view.spans.map(s => {
              const left = s.start_wall_s === null ? 0 : chartPercent(s.start_wall_s)
              const right = s.end_wall_s === null ? left : chartPercent(s.end_wall_s)
              return <button type="button" key={s.id} className={`delivery-timing-row delivery-timing-${s.layer}`} aria-pressed={s.id === selected} onClick={() => setSelected(s.id)}>
                <span className="delivery-timing-row-label">{label(s)}<small>{s.layer === 'observed_stage' ? '采样阶段 · 边界有区间' : s.layer === 'native' ? `原生终态 ${s.terminal_status ?? '未知'}` : s.layer === 'budget' ? '汇总区间 · 不与子行相加' : '未归因区间'}</small></span>
                <span className="delivery-timing-track"><span className="delivery-timing-bar" style={{ left: `${left}%`, width: `${Math.max(.25, right - left)}%` }} /><span className="delivery-timing-duration">{seconds(s.duration_s)}</span>
                  {view.budget !== null && <span className="delivery-timing-limit" style={{ left: `${view.budget / view.limit * 100}%` }} />}</span>
              </button>
            })}
            <div className="delivery-timing-gap-row"><span>物理采样缺口</span><div>{item.sampling.gaps.filter(g => g.before_wall_s !== null && g.after_wall_s !== null && g.after_wall_s >= view.origin! && g.before_wall_s <= view.origin! + view.limit).map((g, i) => <span key={i} className="delivery-timing-gap-mark" title={`缺 ${g.missing ?? '未知'} 帧`} style={{ left: `${chartPercent(g.before_wall_s!)}%`, width: `${Math.max(.5, chartPercent(g.after_wall_s!) - chartPercent(g.before_wall_s!))}%` }} />)}<span className="delivery-timing-budget-label">虚线：原 {seconds(view.budget, 0)} 预算</span></div></div>
          </div>
        </div>}
        {detail && <div className="delivery-timing-detail" role="region" aria-label="所选阶段来源"><strong>{label(detail)} · {seconds(detail.duration_s)}</strong><p>{detail.evidence}</p>
          {detail.goal_id && <p>原 Goal UUID <code>{detail.goal_id}</code> · 终态 {detail.terminal_status ?? '未知'}。终态回执不等于控制器消费回执。</p>}
          {detail.layer === 'observed_stage' && <p>起点区间 {boundary(detail.start_boundary_wall_s, view.origin)}；终点区间 {boundary(detail.end_boundary_wall_s, view.origin)}{detail.right_censored ? '。末阶段仅知最后一次观测，之后状态未知。' : '。不能将采样边界当作精确事件。'}</p>}
          <p>源时间 {seconds(detail.start_source_s)} → {seconds(detail.end_source_s)}；与本图墙钟分别记录。</p></div>}
        <div className="delivery-timing-evidence"><dl><div><dt>最终位置 / 偏航误差</dt><dd>{item.physical.final_position_error_m === null ? '未知' : `${(item.physical.final_position_error_m * 100).toFixed(2)} cm`} / {item.physical.final_yaw_error_rad?.toFixed(4) ?? '未知'} rad</dd></div>
          <div><dt>连续停稳（源时间）</dt><dd>{seconds(item.physical.continuous_final_stop_source_s, 2)}</dd></div><div><dt>保护介入（源时间）</dt><dd>{seconds(item.guard_seconds, 2)}<small>理想保护辅助，单列保留</small></dd></div>
          <div><dt>物理样本 / 缺失序号</dt><dd>{item.sampling.physics_records ?? '未知'} / {item.sampling.missing_samples ?? '未知'}<small>任务窗口内 {item.sampling.task_physics_records ?? '未知'} 条；缺口未插值</small></dd></div></dl>
          <details><summary>采样缺口、原任务与未观测项</summary>
            <p>场景 {item.scene_id} · 车型 {item.vehicle} · {item.sensor} · 观测 {item.observation_mode}</p><p>原任务 <code>{item.task_id}</code><br />Episode <code>{item.episode_id}</code></p>
            <ul>{item.sampling.gaps.map((g, i) => <li key={i}>缺 {g.missing ?? '未知'} 帧；源时间 {seconds(g.before_source_s)} → {seconds(g.after_source_s)}；{g.stage_before} → {g.stage_after}</li>)}</ul>
            <p>未观测：规划 CPU 分项、控制器计算 / 消费回执、阶段精确切换时间。图中的区间不能替代这些证据。</p>
            <p>10Hz 展示摘要 {item.trajectory.sample_count ?? '未知'} 点；独立评分仍使用原始采样。</p>
            <p>会话级物理循环诊断（不能归因到本单 Nav2）：{report.loop.map(l => `${l.name} max ${seconds(l.max_s)}`).join('；') || '未提供'}</p>
          </details>
        </div>
        {item.warnings.length > 0 && <ul className="delivery-timing-warning">{item.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
      </>}
      <p className="delivery-timing-footnote">历史 K 的结果与旧失败分别保留。场景、车型或参数不同的记录不能直接当作 A/B 性能对照。本页只读，不启动任务；本轮仿真证据不外推真机或 sim-to-real。</p>
      <Button size="sm" variant="ghost" onClick={download}><FileDown size={14} aria-hidden="true" />下载原始摘要 JSON</Button>
    </>}
  </Card>
}
