import { useEffect, useState } from 'react'
import { FileDown, RefreshCw } from 'lucide-react'
import { angularPoint, boxAngularEdges, parseSensorExperience, parseSensorFrame, readSensorExperience, readSensorFrame, sameSensorIdentity, type SensorExperience, type SensorFrame } from '@/lib/sensor-experience'
import './sensor-experience-panel.css'
const sourceSeconds = (value: number | null) => value === null ? '未知' : value.toFixed(3)
const display = (value: unknown) => value === undefined || value === null || value === '' ? '未提供' : typeof value === 'object' ? JSON.stringify(value) : String(value)
function Panorama({ frame, truthCompatible }: { frame: SensorFrame; truthCompatible: boolean }) {
  const [observation, setObservation] = useState(true), [truth, setTruth] = useState(true)
  const lines = frame.truth.boxes.map(box => ({ id: box.id, ...boxAngularEdges(box.vertices) }))
  return <><div className="sensor-layer-controls"><label><input type="checkbox" checked={observation} onChange={e => setObservation(e.target.checked)} />实际点云</label><label><input type="checkbox" checked={truth} onChange={e => setTruth(e.target.checked)} disabled={!truthCompatible} />真值 BOX 线框（只展示）</label></div>
    <svg className="sensor-panorama" viewBox="-38 -16 796 367" role="img" aria-label="同一源帧的点云与真值全景投影"><rect width="720" height="320" fill="#f4f7fb" />{[-180, -90, 0, 90, 180].map((degree, i) => <g key={degree}><line x1={i * 180} y1="0" x2={i * 180} y2="320" stroke="#dbe4ef" /><text x={i * 180} y="342" textAnchor="middle">{degree}°</text></g>)}{[90, 45, 0, -45, -90].map((degree, i) => <g key={degree}><line x1="0" y1={i * 80} x2="720" y2={i * 80} stroke="#dbe4ef" /><text x="-8" y={i * 80 + 4} textAnchor="end">{degree}°</text></g>)}
      {truth && truthCompatible && lines.flatMap(box => box.edges.map((line, i) => <line key={`${box.id}-${i}`} x1={line.from[0]} y1={line.from[1]} x2={line.to[0]} y2={line.to[1]} stroke="#b7791f" strokeWidth="1.1" opacity=".7" />))}
      {observation && frame.points.map((point, i) => { const xy = angularPoint(point); return xy ? <circle key={i} cx={xy[0]} cy={xy[1]} r="1.1" fill="#2563eb" opacity=".8" /> : null })}</svg>
    <p>横轴 yaw＝atan2(y,x)，纵轴 pitch＝atan2(z,hypot(x,y))。角度单位为度；同一帧和同一坐标系叠加。</p><p>蓝点为实际接收点，棕线为编译碰撞 BOX。跨 ±180° 的 {lines.reduce((n, item) => n + item.wrapped, 0)} 条边断开，未画跨图长线；遮挡后真值也可能可见。</p></>
}
export function SensorExperiencePanel({ sourceUrl, expectedRunId, initialReport, initialFrame }: { sourceUrl: string; expectedRunId?: string; initialReport?: unknown; initialFrame?: unknown }) {
  const [report, setReport] = useState<SensorExperience | null>(() => initialReport === undefined ? null : parseSensorExperience(initialReport, sourceUrl))
  const [frame, setFrame] = useState<SensorFrame | null>(() => initialFrame === undefined ? null : parseSensorFrame(initialFrame))
  const [index, setIndex] = useState(0), [refresh, setRefresh] = useState(0), [error, setError] = useState('')
  useEffect(() => {
    if (initialReport !== undefined && refresh === 0) return
    const controller = new AbortController(); setError('')
    void readSensorExperience(sourceUrl, controller.signal).then(value => { setReport(value); setIndex(0) }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '对比目录读取失败。') })
    return () => controller.abort()
  }, [sourceUrl, initialReport, refresh])
  const reference = report?.frames[index]
  useEffect(() => {
    if (initialFrame !== undefined && index === 0 && refresh === 0) return
    const controller = new AbortController(); setFrame(null); setError('')
    if (reference?.url) void readSensorFrame(reference.url, controller.signal).then(setFrame).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '该源帧读取失败。') })
    return () => controller.abort()
  }, [reference, initialFrame, index, refresh])
  const runMismatch = Boolean(report?.runId && expectedRunId && report.runId !== expectedRunId)
  const identityMatch = Boolean(reference && frame && sameSensorIdentity(reference.identity, frame.identity))
  const truthCompatible = Boolean(identityMatch && frame?.frameId && frame.frameId === frame.truth.frameId && frame.truth.referenceOnly)
  const sensor = report?.sensor ?? {}
  const tfWarnings = report?.warnings.filter(warning => warning.startsWith('Same-source map TF unavailable:')) ?? []
  const otherWarnings = report?.warnings.filter(warning => !warning.startsWith('Same-source map TF unavailable:')) ?? []
  const sensorName = sensor.scan_pattern === 'livox_mid360_csv_stride5' ? 'MID-360式扫描' : sensor.lines ? `${display(sensor.lines)}线3D雷达` : '扫描模式未提供'
  return <section className="sensor-experience-panel" aria-labelledby="sensor-experience-heading"><header><div><h2 id="sensor-experience-heading">传感器与真值对比</h2><p>同源 PointCloud2 与独立几何参考，本图真值叠加只用于展示和评分。</p></div><button type="button" onClick={() => setRefresh(v => v + 1)}><RefreshCw size={14} aria-hidden="true" />刷新对比</button></header>
    {error && <p role="status" className="sensor-experience-warning">{error}</p>}{otherWarnings.map((warning, i) => <p key={i} className="sensor-experience-warning">{warning}</p>)}
    {!report ? <p>正在读取已保存的传感器采样…</p> : <><div className="sensor-experience-context"><span>{sensorName}</span><span>采集{report.status === 'complete' ? '已完成' : report.status === 'incomplete' ? '未完整' : report.status}</span><span>{report.confirmedReadOnly ? '只读导入 · 未重评分' : '来源边界待确认'}</span><span>坐标系 {report.frameId || '未提供'}</span></div>
      {tfWarnings.length > 0 && <p className="sensor-experience-warning">部分帧未取得对应时刻 map TF，未以真值补齐。原始原因可在下方展开。</p>}{runMismatch && <p className="sensor-experience-warning">采集运行与当前成果不一致，不混用投影。</p>}
      <div className="sensor-experience-selection"><label>源帧<select aria-label="选择传感器源帧" value={index} onChange={e => setIndex(Number(e.target.value))}>{report.frames.map((value, i) => <option key={`${value.url}-${i}`} value={i}>帧 {i + 1} · seq {value.identity.sequence || '未知'} · 源 {sourceSeconds(value.source)}s</option>)}</select></label><a href={sourceUrl} download><FileDown size={14} aria-hidden="true" />下载采集目录</a></div>
      {!report.frames.length ? <p className="sensor-experience-warning">没有精确匹配的云／元数据／物理源帧，未选择最近帧补齐。</p> : !frame ? <p>该帧尚未载入；未使用其他时刻替代。</p> : !identityMatch || runMismatch ? <p className="sensor-experience-warning">目录与帧的 scene／manifest／episode／sequence 不一致，当前帧不参与叠加，其余成果保留。</p> : <>
        {!truthCompatible && <p className="sensor-experience-warning">真值坐标系或只读标记不匹配，仅显示实际点云。</p>}<Panorama key={`${frame.identity.episode_id}:${frame.identity.sequence}`} frame={frame} truthCompatible={truthCompatible} />
        <p>实际来源 {frame.observedSource || '未提供'} · {frame.observedTopic || 'topic未提供'} · {frame.validPoints ?? frame.points.length} 有效点；原消息 {display(frame.width)} × {display(frame.height)}。</p><p>真值只含 {frame.truth.boxes.length} 个碰撞BOX，省略 {display(frame.truth.omitted)} 个非BOX几何；它包含遮挡后表面，不是深度相机可见面。</p>
        <details className="sensor-source-details"><summary>源身份、原始纳秒与TF详情</summary><dl className="sensor-experience-identity"><div><dt>场景身份</dt><dd>{frame.identity.scene_sha256 || '未提供'}</dd></div><div><dt>Manifest 身份</dt><dd>{frame.identity.manifest_sha256 || '未提供'}</dd></div><div><dt>Episode / sequence</dt><dd>{frame.identity.episode_id} / {frame.identity.sequence}</dd></div><div><dt>原源时间纳秒</dt><dd>{frame.sourceNs || '精确值未提供'}</dd></div></dl>{frame.actualTf ? <><p>{frame.actualTf.source} → {frame.actualTf.target}，原 TF 查询源纳秒 {frame.actualTf.sourceNs || '未知'}。</p><p>平移 {JSON.stringify(frame.actualTf.translation[0] ?? null)} m；四元数 xyzw {JSON.stringify(frame.actualTf.quaternion)}。</p></> : <p>该帧 map TF 未取得；不通过车体真值补TF。</p>}{frame.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</details></>}
      <details className="sensor-experience-evidence"><summary>传感器配置、接收与消费者证据</summary>{!report.runId && <p>该采集报告未绑定 run_id，保留实际场景、manifest、episode 与源序号；不据此宣称跨场景公平 A/B。</p>}<dl><div><dt>扫描模式</dt><dd>{display(sensor.scan_pattern ?? sensor.basis)}</dd></div><div><dt>实际点数配置 / 帧率</dt><dd>{display(sensor.lines)} × {display(sensor.horizontal_samples)} / {display(sensor.rate_hz ?? sensor.hz)}Hz</dd></div><div><dt>近似与降采样</dt><dd>角度降采样 {display(sensor.angular_downsample)}；硬件名义 {display(sensor.nominal_hardware_points_per_s)} 点/s</dd></div></dl>
        <p>MID-360式配置使用保序抽样的官方扫描表、帧内冻结查询；不等于完整商业硬件的时序、反射率或噪声模型。均匀线束配置保持其原名，不因切换视图变成MID-360。</p><p>接收计数 {JSON.stringify(report.counts)}；TF统计 {JSON.stringify(report.tf)}。</p>{tfWarnings.length > 0 && <details className="sensor-tf-reasons"><summary>原始TF采集原因（{tfWarnings.length}项）</summary>{tfWarnings.map((warning, i) => <p key={i}>{warning}</p>)}</details>}<p>实际订阅发现：{report.subscribers.length ? report.subscribers.map(s => `${s.node} (${s.type})`).join('；') : '未提供'}。</p><p>订阅发现不等于逐消息消费ACK。点云被接收、控制器消费和完整配送评分各自独立；页面叠加不派发动作。</p><p>本图真值叠加回流控制：{report.truthToControl === false && frame?.truthToControl !== true ? '未进入（按原采集记录）' : '边界待核实'}。本页没有发布者或动作调用；工位信标等原控制输入以成果卡的 ideal／vision 模式为准。</p></details></>}
  </section>
}
