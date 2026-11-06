import { useEffect, useRef, useState } from 'react'
import { ArrowDown, CheckCircle2, CircleHelp, CircleX, FileDown, Pause, Play, RefreshCw } from 'lucide-react'
import { parseDeliveryComparison, runDuration, type ReplayReport } from '@/lib/delivery-comparison'
import { parseDeliveryTiming, type TimingReport } from '@/lib/delivery-timing'
import { parseVisionResult, readVisionResult, type VisionResult } from '@/lib/vision-delivery'
import { DeliveryTimingPanel } from './delivery-timing-panel'
import { ReplayViewport } from './regression-page'
import './vision-delivery-result.css'

const metric = (v: number | null, unit: string, scale = 1) => v === null ? '未提供' : `${(v * scale).toFixed(2)} ${unit}`

export function VisionDeliveryResult({ initialResult }: { initialResult?: unknown }) {
  const [result, setResult] = useState<VisionResult | null>(() => initialResult === undefined ? null : parseVisionResult(initialResult))
  const [replay, setReplay] = useState<ReplayReport | null>(null), [timing, setTiming] = useState<TimingReport | null>(null)
  const [sourceUrl, setSourceUrl] = useState('/workbench/j100-vision-result.json')
  const [videoError, setVideoError] = useState(false)
  const [messages, setMessages] = useState<string[]>([]), [loading, setLoading] = useState(initialResult === undefined)
  const [orderIndex, setOrderIndex] = useState(0), [elapsed, setElapsed] = useState(0), [playing, setPlaying] = useState(false), [speed, setSpeed] = useState(8)
  const request = useRef<AbortController | null>(null), generation = useRef(0)
  async function load(url = sourceUrl, preferLatest = false) {
    const current = ++generation.current; request.current?.abort()
    const controller = new AbortController(); request.current = controller
    setLoading(true); setPlaying(false); setVideoError(false); setMessages([])
    try {
      let next = await readVisionResult(controller.signal, url), resolvedUrl = url
      const notes: string[] = []
      if (preferLatest && next.preferredUrl && next.preferredUrl !== url) {
        try { resolvedUrl = next.preferredUrl; next = await readVisionResult(controller.signal, resolvedUrl) }
        catch { resolvedUrl = url; notes.push('最新补录暂不可读取，继续展示历史摘要。') }
      }
      if (current !== generation.current) return
      setResult(next); setSourceUrl(resolvedUrl); setReplay(null); setTiming(null); setOrderIndex(0); setElapsed(0)
      const entries = await Promise.allSettled([next.replayUrl, next.timingUrl].map(async url => {
        if (!url) return null
        const response = await fetch(url, { method: 'GET', cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error(`一项回放/阶段报告读取失败（HTTP ${response.status}），成果摘要继续保留。`)
        return response.json() as Promise<unknown>
      }))
      if (current !== generation.current) return
      if (entries[0].status === 'fulfilled' && entries[0].value) setReplay(parseDeliveryComparison(entries[0].value))
      if (entries[1].status === 'fulfilled' && entries[1].value) setTiming(parseDeliveryTiming(entries[1].value))
      setMessages([...notes, ...entries.flatMap(item => item.status === 'rejected' && !controller.signal.aborted ? [item.reason instanceof Error ? item.reason.message : '一项素材读取失败。'] : [])])
    } catch (error) {
      if (!controller.signal.aborted && current === generation.current) setMessages([error instanceof Error ? error.message : '成果读取失败，已有内容保留。'])
    } finally { if (current === generation.current) setLoading(false) }
  }
  useEffect(() => {
    if (initialResult === undefined) void load(sourceUrl, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Invalidate the latest request, not the mount's earlier generation.
    return () => { generation.current++; request.current?.abort() }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const order = result?.orders[orderIndex]
  const VerdictIcon = order?.passed === true ? CheckCircle2 : order?.passed === false ? CircleX : CircleHelp
  const run = replay?.runs.find(item => item.taskId === order?.taskId)
  const anchor = run?.anchors.recording !== undefined ? 'recording' : 'route'
  const duration = run ? runDuration(run, anchor) : 0
  useEffect(() => {
    if (!playing) return
    let previous = performance.now()
    const timer = window.setInterval(() => {
      const now = performance.now(), dt = (now - previous) / 1000; previous = now
      setElapsed(value => { const next = Math.min(duration, value + dt * speed); if (next >= duration) setPlaying(false); return next })
    }, 60)
    const hide = () => { if (document.hidden) setPlaying(false) }
    document.addEventListener('visibilitychange', hide)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', hide) }
  }, [playing, duration, speed])
  function chooseTask(taskId: string, sourceTime?: number) {
    const index = result?.orders.findIndex(item => item.taskId === taskId) ?? -1
    if (index < 0) return
    setOrderIndex(index); setPlaying(false)
    const target = replay?.runs.find(item => item.taskId === taskId)
    const origin = target?.anchors.recording ?? target?.anchors.route
    setElapsed(sourceTime !== undefined && origin !== undefined ? Math.max(0, Math.min(sourceTime - origin, runDuration(target!, target!.anchors.recording !== undefined ? 'recording' : 'route'))) : 0)
    if (sourceTime !== undefined) document.getElementById('j100-vision-replay')?.scrollIntoView({ behavior: 'auto', block: 'center' })
  }
  return <>
    <section className="vision-result" id="j100-vision-delivery" aria-labelledby="vision-result-title">
      <header className="vision-result-heading"><div><h2 id="vision-result-title">{result?.title ?? 'J100 视觉配送'}</h2><p>从相机看到货物，到双指抓取、车载运输和货架交付。</p></div>
        <button type="button" onClick={() => void load()} disabled={loading}><RefreshCw size={15} aria-hidden="true" />{loading ? '读取成果' : '刷新成果'}</button></header>
      {messages.length > 0 && <div className="vision-result-notice" role="status">{messages.map((message, i) => <p key={i}>{message}</p>)}</div>}
      {!result ? <p className="vision-result-notice">{loading ? '正在读取已保存的成果…' : '暂未载入视觉成果，下面仍可查看历史配送报告。'}</p> : <>
        <div className="vision-result-context">{result.recordings.length > 1 && <label>配送记录 <select aria-label="选择视觉配送成果" disabled={loading} value={sourceUrl} onChange={event => void load(event.target.value)}>{result.recordings.map(item => <option key={item.url} value={item.url}>{item.label}</option>)}</select></label>}<span>{result.vehicle}</span><span>{result.sensor}</span><span>{result.model}</span><time>{result.recordedAt}</time><span>{result.evidenceKind === 'recorded_simulation' ? '记录回放' : result.evidenceKind === 'documented_acceptance' ? '已审历史摘要' : '来源待确认'}</span></div>
        <div className="vision-result-layout">
          <div className="vision-result-player" id="j100-vision-replay">
            {run && replay && run.frames.length > 0 ? <>
              <ReplayViewport report={replay} run={run} other={undefined} elapsed={elapsed} anchor={anchor} color="#2465da" ghost={false} />
              <div className="vision-result-playback"><button type="button" aria-label={playing ? '暂停视觉配送回放' : '播放视觉配送回放'} onClick={() => { if (elapsed >= duration) setElapsed(0); setPlaying(value => !value) }}>{playing ? <Pause size={16} /> : <Play size={16} />}{playing ? '暂停' : '播放'}</button>
                <input type="range" min="0" max={Math.max(.1, duration)} step=".02" value={elapsed} aria-label="视觉配送源时间" onChange={event => { setPlaying(false); setElapsed(Number(event.target.value)) }} />
                <output>{elapsed.toFixed(1)} / {duration.toFixed(1)} s</output><label>速度<select aria-label="视觉回放速度" value={speed} onChange={event => setSpeed(Number(event.target.value))}>{[1, 8, 32].map(value => <option key={value} value={value}>{value}×</option>)}</select></label></div>
              <p className="vision-result-caption">{replay.warnings.length ? '当前为已导入的展示采样，来源边界见下方告警。' : '车辆、货物与关节来自保存的实际采样。'}空档保持空白，播放不启动仿真。</p>{replay.warnings.length > 0 && <div className="vision-result-notice" role="status">{replay.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</div>}
            </> : <div className="vision-result-unavailable"><h3>位置回放尚未载入</h3><p>{result.availabilityNote || '原记录恢复并导出轻量回放后，在这里查看实际轨迹。'}</p><p>已验收的结果继续展示；不以其他回合或插值轨迹代替本回合。</p></div>}
            {result.videoUrl && <><video controls preload="metadata" poster={result.posterUrl ?? undefined} src={result.videoUrl} aria-label="视觉配送场景采样录像" onError={() => setVideoError(true)} /><p className="vision-result-caption">{result.videoCaption || '场景采样录像独立播放；阶段跳转定位上方数据回放，不定位录像。'}</p></>}{videoError && <p className="vision-result-notice" role="status">录像加载失败；成果摘要与可用的数据回放继续保留。</p>}
          </div>
          <aside className="vision-result-ledger" aria-label="视觉配送订单成果">
            <h3>{result.orders.length > 1 ? '两件货物，同一世界' : '实际派发的订单'}</h3><p>原任务与独立物理评分，分别对应每件货物。</p>
            <div role="group" aria-label="选择视觉配送订单">{result.orders.map((item, i) => <button type="button" key={item.id} aria-pressed={orderIndex === i} onClick={() => chooseTask(item.taskId)}>{item.label}</button>)}</div>
            {order && <><div className={`vision-result-verdict ${order.passed === true ? 'is-passed' : ''}`}><VerdictIcon size={18} aria-hidden="true" />{order.passed === true ? '独立业务评分通过' : order.passed === false ? '原评分未通过' : '评分待确认'}</div>{order.failureReason && <p className="vision-result-notice">{order.failureReason}</p>}{order.componentSummary && <p className="vision-result-component"><strong>已证实的分项</strong><br />{order.componentSummary}</p>}
              <dl><div><dt>配送路线</dt><dd>{metric(order.routeSeconds, 's')}</dd></div><div><dt>最终位置误差</dt><dd>{metric(order.positionError, 'cm', 100)}</dd></div><div><dt>最终偏航误差</dt><dd>{metric(order.yawError, 'rad')}</dd></div></dl>
              <p className="vision-result-observation">装货 / 卸货可见点：<strong>{order.points.length ? order.points.join(' / ') : '未提供'}</strong><br />所选模型候选：{order.candidates.length ? order.candidates.join(' / ') : '未提供'}</p></>}
            <p>{result.resets === null ? '重置次数未提供' : `${result.resets} 次世界重置`}；整轮 {metric(result.elapsed, 's')}。</p>
            <a href="#workbench-delivery-timing"><ArrowDown size={14} aria-hidden="true" />查看阶段瀑布图</a>
            <a href={sourceUrl} download="j100-vision-result.json"><FileDown size={14} aria-hidden="true" />下载成果摘要</a>
          </aside>
        </div>
        <details className="vision-result-evidence"><summary>来源、归档与适用范围</summary><p>运行 {result.runId}；{result.archiveStatus}。</p><p>固定绿色货物与工位仿真，OBB候选经预训练判别器评分，停车保护辅助单列。当前回放与原物理评分分开，不外推任意物体或真机。</p>
          {result.archiveUrl && <p><a href={result.archiveUrl} target="_blank" rel="noopener noreferrer">打开 Drive 恢复包</a></p>}{result.warnings.map((message, i) => <p key={i}>{message}</p>)}<a href="https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools/blob/main/docs/PRETRAINED_PERCEPTION.md" target="_blank" rel="noopener noreferrer">配置与验收说明</a></details>
      </>}
    </section>
    <DeliveryTimingPanel key={timing?.source_run_id ?? 'pending-vision'} initialSource="j100vision" sourceUrl={result?.timingUrl ?? undefined} initialReport={timing?.source}
      caseTaskId={order?.taskId} onCaseChange={chooseTask} onReplayRequest={chooseTask} replayTaskIds={replay?.runs.map(item => item.taskId)} />
  </>
}
