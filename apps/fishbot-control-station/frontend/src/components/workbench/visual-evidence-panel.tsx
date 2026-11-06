import { useEffect, useState } from 'react'
import { FileDown, RefreshCw } from 'lucide-react'
import { parseVisualEvidence, readVisualEvidence, type VisualEvidence, type VisualEvidenceEntry, type VisualMilestone, type VisualQuery } from '@/lib/visual-evidence'
import './visual-evidence-panel.css'

const metric = (value: number | null, unit: string, scale = 1) => value === null ? '未提供' : `${(value * scale).toFixed(3)} ${unit}`
const verdict = (value: boolean | null) => value === true ? '原分项评分通过' : value === false ? '原分项评分未通过' : '未提供原分项评分'
function EvidenceImage({ src, label }: { src: string | null; label: string }) {
  const [failed, setFailed] = useState(false)
  return <figure className="visual-evidence-image">{src && !failed ? <a href={src} target="_blank" rel="noopener noreferrer"><img src={src} alt={label} loading="lazy" onError={() => setFailed(true)} /></a> : <div className="visual-evidence-missing">{src ? `${label}加载失败` : `${label}未提供`}</div>}<figcaption>{label}</figcaption></figure>
}
function VisibleCloud({ entry }: { entry: VisualEvidenceEntry }) {
  const [plane, setPlane] = useState<'xy' | 'xz'>('xy')
  const points = entry.points.xyz, second = plane === 'xy' ? 1 : 2
  const xs = points.map(p => p[0]), ys = points.map(p => p[second]), zs = points.map(p => p[2])
  const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys)
  const zmin = Math.min(...zs), zmax = Math.max(...zs)
  return <div className="visual-evidence-cloud"><div role="group" aria-label="点云投影平面">{(['xy', 'xz'] as const).map(value => <button type="button" key={value} aria-pressed={plane === value} onClick={() => setPlane(value)}>{value.toUpperCase()} 投影</button>)}</div>
    {points.length ? <svg viewBox="0 0 400 260" role="img" aria-label={`实际可见点云 ${plane.toUpperCase()} 投影`}><rect x="0" y="0" width="400" height="260" fill="#f4f7fb" />{points.map((p, i) => <circle key={i} cx={24 + (p[0] - xmin) / Math.max(xmax - xmin, 1e-6) * 352} cy={230 - (p[second] - ymin) / Math.max(ymax - ymin, 1e-6) * 200} r="2" fill={`hsl(${215 - (p[2] - zmin) / Math.max(zmax - zmin, 1e-6) * 140} 65% 43%)`} />)}<text x="10" y="253">X {metric(xmin, 'm')} → {metric(xmax, 'm')}</text></svg> : <p className="visual-evidence-missing">未提供可见点坐标，不使用完整物体模型补点。</p>}
    <p>{points.length} 个展示点；原观测 {entry.observation.pointCount ?? '未知'} 点。颜色表示相机 Z；投影按本帧范围缩放。</p><p>坐标系 {entry.points.frame}，单位米；不是物体完整几何。</p></div>
}
function PhysicalMilestone({ value, label, lift = false }: { value: VisualMilestone | null; label: string; lift?: boolean }) {
  return <><EvidenceImage key={value?.image ?? 'missing'} src={value?.image ?? null} label={label} /><p>{verdict(value?.originalPassed ?? null)}；源时间 {metric(value?.sourceTime ?? null, 's')}。</p>{lift && <p>原记录抬升量 {metric(value?.measuredLift ?? null, 'mm', 1000)}。</p>}<p className="visual-evidence-boundary">画面与评分分别保留，图片存在不等于动作通过。</p></>
}
const stageNames: Record<string, string> = {
  query_started: '查询开始', child_spawned: '子进程已派发', child_started: '子进程开始',
  source_modules_import_started: '规划模块导入开始', source_modules_import_completed: '规划模块导入完成',
  planner_init_started: '规划初始化开始', planner_init_completed: '规划初始化完成',
  world_model_compile_started: '世界模型编译开始', world_model_compile_completed: '世界模型编译完成',
  contact_model_compile_started: '接触模型编译开始', contact_model_compile_completed: '接触模型编译完成',
  rig_model_compile_started: '机械臂模型编译开始', rig_model_compile_completed: '机械臂模型编译完成',
  named_entity_view_started: '绑定车臂货物开始', named_entity_view_completed: '绑定车臂货物完成',
  collision_checkers_init_started: '碰撞检查器初始化开始', collision_checkers_init_completed: '碰撞检查器初始化完成',
  rgbd_query_data_started: '创建相机查询', rgbd_render_started: '相机渲染开始', rgbd_render_completed: '相机渲染完成',
  visible_cloud_extraction_started: '可见点云提取开始', visible_cloud_saved: '可见点云已保存',
  model_client_process_started: '模型客户端派发', model_client_process_exited: '模型客户端退出',
  model_cli_started: '推理入口开始', model_input_load_started: '模型输入读取开始', model_input_loaded: '模型输入读取完成',
  official_server_loading_started: '模型加载开始', official_server_loaded: '模型加载完成（未推理）',
  official_client_metadata_started: '模型连接请求', official_client_metadata_completed: '模型连接响应',
  official_inference_request_started: '模型推理请求', official_inference_response_received: '模型候选响应',
  official_server_request_started: '服务端推理开始', official_server_request_completed: '服务端推理完成',
  official_post_inference_metadata_started: '推理回执请求', official_post_inference_metadata_completed: '推理回执响应',
  candidate_serialization_started: '候选保存开始', candidate_serialization_completed: '候选保存完成',
  model_candidates_loaded: '候选载入完成', candidate_planning_started: '候选IK与碰撞规划开始',
  candidate_phase_started: '候选IK／碰撞／OMPL步骤开始', candidate_phase_finished: '候选IK／碰撞／OMPL步骤完成',
  grasp_ik: '抓取姿态IK', pregrasp_ik: '预抓取姿态IK', transfer_endpoint_ik: '放货端点IK',
  transfer_release_sweep: '开爪碰撞扫掠', descent_validation: '下降路径碰撞检查', ascent_validation: '抬升路径碰撞检查',
  ompl_approach: 'OMPL接近路径规划', model_candidate_selected: '可执行候选已选定', candidate_planning_failed: '候选规划未通过',
  child_response_writing: '子进程写入响应', child_exited: '子进程退出', child_failed: '子进程失败',
  model_cli_failed: '模型入口失败', model_cli_report_writing: '保存推理回执',
  query_result_accepted: '规划结果已接纳', query_failed: '查询失败', query_cleanup_completed: '查询清理完成',
  query_deadline_reached: '原查询期限到期', query_timeout: '原查询期限到期',
}
const outcomeNames: Record<string, string> = {
  accepted: '规划结果已接纳（非物理成功）', completed: '查询完成', succeeded: '查询完成',
  timeout: '查询超时', timed_out: '查询超时', TimeoutError: '查询超时', TimeoutExpired: '子进程超时',
  failed: '查询失败', RuntimeError: '查询运行错误', ValueError: '查询输入或结果异常',
  canceled: '查询已取消', cancelled: '查询已取消', CancelledError: '查询已取消', KeyboardInterrupt: '查询被中断',
  incomplete: '取证未完成', unknown: '终态未知',
}
const phaseNames: Record<string, string> = {
  grasp_ik: '抓取姿态IK', pregrasp_ik: '预抓取姿态IK', transfer_endpoint_ik: '放货端点IK',
  transfer_release_sweep: '开爪碰撞扫掠', descent_validation: '下降路径碰撞检查', ascent_validation: '抬升路径碰撞检查',
  closure_sweep: '闭爪碰撞扫掠', direct_approach: '直达接近路径检查', ompl_approach: 'OMPL接近路径规划',
}
function queryStageLabel(stage: VisualQuery['stages'][number], timeout: number | null) {
  if (['query_deadline_reached', 'query_timeout'].includes(stage.stage) && timeout === 30) return '原30秒到期'
  if (stage.phase && ['candidate_phase_started', 'candidate_phase_finished'].includes(stage.stage)) {
    return `${phaseNames[stage.phase] ?? stage.phase}${stage.stage === 'candidate_phase_started' ? '开始' : '完成'}`
  }
  return stageNames[stage.stage] ?? stage.stage
}
function QueryTimeline({ query }: { query: VisualQuery }) {
  const limit = Math.max(query.timeout ?? 30, ...query.stages.map(stage => stage.elapsed ?? 0), 1)
  return <details className="visual-query"><summary>查询 {query.id} · {outcomeNames[query.outcome] ?? query.outcome}</summary><p>原终态 <code>{query.outcome}</code>。原查询期限 {metric(query.timeout, 's')}。墙钟间隔包含等待与调度，不能当作 CPU 耗时。</p><ol>{query.stages.map((stage, i) => {
    const previous = i > 0 ? query.stages[i - 1].elapsed : 0
    const duration = stage.elapsed !== null && previous !== null && stage.elapsed >= previous ? stage.elapsed - previous : null
    return <li key={`${stage.stage}-${i}`}><span>{queryStageLabel(stage, query.timeout)}</span><output>累计 {metric(stage.elapsed, 's')}</output><div className="visual-query-track" title="前一事件到本事件的墙钟间隔">{duration !== null && <span style={{ marginLeft: `${(previous ?? 0) / limit * 100}%`, width: `${duration / limit * 100}%` }} />}</div><small>原事件 <code>{stage.stage}</code>{stage.phase && <> · 原步骤 <code>{stage.phase}</code></>}{stage.candidateIndex !== null && <> · 候选 #{stage.candidateIndex}</>}；前一事件至此 {metric(duration, 's')}</small></li>
  })}</ol>{!query.stages.length && <p>未提供分段事件，不能从总超时推断模型或规划耗时。</p>}</details>
}
export function VisualEvidencePanel({ sourceUrl, expectedRunId, taskId, initialReport }: { sourceUrl: string; expectedRunId?: string; taskId?: string; initialReport?: unknown }) {
  const [report, setReport] = useState<VisualEvidence | null>(() => initialReport === undefined ? null : parseVisualEvidence(initialReport))
  const [error, setError] = useState(''), [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(initialReport === undefined)
  const [selected, setSelected] = useState('')
  useEffect(() => {
    if (initialReport !== undefined && refresh === 0) return
    const controller = new AbortController()
    setLoading(true); setError('')
    void readVisualEvidence(sourceUrl, controller.signal).then(value => { setReport(value); setSelected('') }).catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : '视觉材料读取失败。') }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [sourceUrl, initialReport, refresh])
  const identityMismatch = Boolean(report && expectedRunId && report.runId !== expectedRunId)
  const entries = identityMismatch ? [] : report?.entries.filter(entry => !taskId || entry.taskId === taskId) ?? []
  const entry = entries.find(item => item.id === selected) ?? entries[0]
  return <section className="visual-evidence-panel" aria-labelledby="visual-evidence-heading"><header><div><h2 id="visual-evidence-heading">视觉证据链</h2><p>输入、模型候选与实际抓放分开核对；本页只查看保存材料。</p></div><button type="button" onClick={() => setRefresh(value => value + 1)} disabled={loading}><RefreshCw size={14} aria-hidden="true" />刷新材料</button></header>
    {error && <p role="status" className="visual-evidence-warning">{error}</p>}{report?.warnings.map((warning, i) => <p key={i} className="visual-evidence-warning">{warning.startsWith('No recorded RGB-D observation directories found') ? '本回合未保存RGB-D输入，视觉链为空，不计模型或抓放成功。' : warning}</p>)}
    {identityMismatch && <p role="status" className="visual-evidence-warning">证据运行 {report?.runId || '未知'} 与当前配送运行不一致；当前项不混用，其他配送材料仍保留。</p>}
    {!report ? <p>{loading ? '正在读取视觉材料…' : '未载入视觉证据，不能把模型加载解释成实际推理。'}</p> : <><p className="visual-evidence-source">运行 {report.runId || '未提供'} · 场景 {report.sceneId} · {report.sourceConfirmed ? '只读导入 · 未重新评分' : '来源边界待确认'}</p>
      <div className="visual-evidence-picker" role="group" aria-label="选择抓取视觉材料">{entries.map(item => <button type="button" key={item.id} aria-pressed={item.id === entry?.id} onClick={() => setSelected(item.id)}>{item.phase === 'load' ? '装货' : item.phase === 'unload' ? '卸货' : item.phase} · {item.cargoId} · {item.armId}</button>)}</div>
      {!entry ? <p className="visual-evidence-warning">{report.entries.length === 0 ? '本运行没有已记录的RGB-D输入或模型候选；下面保留查询分段取证，不能把服务加载当作实际模型调用。' : '当前订单没有匹配的视觉输入或候选记录。未从其他订单补入。'}</p> : <><p className="visual-evidence-source">Episode {entry.observation.episodeId || '未知'} · sequence {entry.observation.sequence ?? '未知'} · 源时间 {metric(entry.observation.stamp, 's')} · {entry.observation.frame}</p>
        <div className="visual-evidence-chain"><article><h3>RGB／深度输入</h3><div className="visual-evidence-inputs"><EvidenceImage key={entry.images.rgb ?? 'rgb'} src={entry.images.rgb} label="原始 RGB" /><EvidenceImage key={entry.images.depth ?? 'depth'} src={entry.images.depth} label="米制深度的显示映射" /></div><details><summary>目标选区</summary><EvidenceImage key={entry.images.mask ?? 'mask'} src={entry.images.mask} label="原始目标掩码" /></details></article>
          <article><h3>实际可见点云</h3><VisibleCloud key={entry.id} entry={entry} /></article>
          {entry.generatedCandidates && <article><h3>模型生成候选（未执行）</h3><p>原输出共 {entry.generatedCandidates.count ?? '未知'} 个候选。下面仅预览原顺序中的 {entry.generatedCandidates.preview.length} 项，不表示候选已选定或实际执行。</p>{entry.generatedCandidates.overlay && <EvidenceImage src={entry.generatedCandidates.overlay} label="原生成候选预览投影（不是所选候选）" />}<details><summary>查看生成候选的原索引与分数</summary><ul>{entry.generatedCandidates.preview.map((candidate, i) => <li key={i}>候选 #{candidate.index ?? '未知'} · {candidate.origin} · 模型分数 {metric(candidate.score, '')}</li>)}</ul></details>{entry.generatedCandidates.sourceReport && <a href={entry.generatedCandidates.sourceReport} download>下载全部生成候选</a>}<p className="visual-evidence-boundary">生成候选、规划尝试和已执行选择分别记账；分数不代表物理成功概率。</p></article>}
          <article><h3>所选抓取候选</h3><EvidenceImage key={entry.images.graspOverlay ?? 'candidate'} src={entry.images.graspOverlay} label="所选候选在输入画面的投影" />{entry.selected ? <p>候选 #{entry.selected.index ?? '未知'} · {entry.selected.origin} · 模型分数 {metric(entry.selected.score, '')}</p> : <p>未提供已执行的候选选择。</p>}<p>推理状态：{entry.inference.status}；候选总数 {entry.inference.candidateCount ?? '未知'}。</p><p>请求 {metric(entry.inference.requestWall, 's')}；模型入口总计 {metric(entry.inference.total, 's')}。</p>{entry.inference.sourceReport && <a href={entry.inference.sourceReport} download>下载原推理回执</a>}<p className="visual-evidence-boundary">模型分数不解释为成功概率，也不替代物理评分。</p></article>
          <article><h3>实际抬升</h3><PhysicalMilestone value={entry.milestones.lift} label="实际抬升采样画面" lift /></article>
          <article><h3>实际放货</h3><p className="visual-evidence-boundary">{entry.phase === 'load' ? '本项是装货后放入小车托盘，不是目的地卸货上架。' : entry.phase === 'unload' ? '本项是目的地卸货阶段；仍需核对整单原评分。' : '放货阶段按原记录展示。'}</p><PhysicalMilestone value={entry.milestones.placement} label="实际放货采样画面" /></article></div>
        {entry.warnings.map((warning, i) => <p key={i} className="visual-evidence-warning">{warning}</p>)}</>}
      <details className="visual-query-section"><summary>查询分段取证 · {report.queries.length} 次</summary><p>按原查询事件顺序显示初始化、渲染、推理、候选与规划的边界；缺少阶段就保留未知。</p>{report.queries.map((query, i) => <QueryTimeline key={`${query.id}-${i}`} query={query} />)}</details></>}
    <a className="visual-evidence-download" href={sourceUrl} download><FileDown size={14} aria-hidden="true" />下载视觉证据目录</a>
  </section>
}
