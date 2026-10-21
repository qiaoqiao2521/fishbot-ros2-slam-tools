import { useEffect, useState, type ReactNode } from 'react'
import { ArrowLeft, Box, CircleCheck, MapPin, Play, RefreshCw, Square, Truck } from 'lucide-react'
import { WorkspaceSurface } from '@/components/workspace/workspace-surface'
import { EventContinuity } from './event-continuity'
import { projectCooperationEvidence } from '@/lib/command-evidence'
import { CommandEvidencePanel } from '@/components/status/command-evidence-panel'
import {
  COOPERATION_DOMAIN, COOPERATION_POLL_MS, COOPERATION_STAGES, CooperationController,
  cooperationCanCancel, cooperationCanReset, cooperationCanStart, cooperationConnected,
  cooperationStageLabel, cooperationStatusLabel,
  type CooperationFrameObservation, type CooperationSnapshot,
} from '@/lib/cooperation'
import { CooperationCanvasView, LiveCooperationCanvas } from './cooperation-canvas'
import { CooperationSceneProfilePanel } from './cooperation-scene-profile'
import { cooperationLiveProfile } from '@/lib/cooperation-scene-profile'
import './cooperation.css'
import './cooperation-workspace.css'

export function CooperationPage({ onBack, controller: suppliedController, active = true }: {
  onBack: () => void; controller?: CooperationController; active?: boolean
}) {
  const [controller] = useState(() => {
    if (suppliedController) return suppliedController
    let storage: Storage | null = null
    try { storage = window.sessionStorage } catch { /* Blocked stores retain receipts in memory. */ }
    return new CooperationController({ storage })
  })
  const [snapshot, setSnapshot] = useState(controller.getSnapshot)
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [])
  // This page owns the business session, even when its canvas/panels are hidden.
  useEffect(() => {
    const unsubscribe = controller.subscribe(setSnapshot)
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      await controller.refresh()
      if (!stopped) timer = setTimeout(poll, COOPERATION_POLL_MS)
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer); unsubscribe() }
  }, [controller])
  return <CooperationView snapshot={snapshot} now={now} frame={null} onBack={onBack} active={active}
    onStart={() => { void controller.act('start') }} onCancel={() => { void controller.act('cancel') }}
    onReset={() => { void controller.reset() }} onRefresh={() => { void controller.refresh() }}
    canvas={<LiveCooperationCanvas snapshot={snapshot} now={now} active={active} />} />
}

type CooperationViewProps = {
  snapshot: CooperationSnapshot
  now: number
  frame: CooperationFrameObservation | null
  onBack: () => void
  onStart: () => void
  onCancel: () => void
  onReset?: () => void
  onRefresh: () => void
  displayedFrameSrc?: string | null
  visionFrame?: CooperationFrameObservation | null
  displayedVisionSrc?: string | null
  active?: boolean
  canvas?: ReactNode
}
type SelectedObject = 'car' | 'arm' | 'cargo' | 'station'
const sceneObjects: Array<{ id: SelectedObject; name: string; detail: string }> = [
  { id: 'car', name: 'FishBot', detail: '运输底盘 · 导航与运动' },
  { id: 'arm', name: 'SO101 机械臂', detail: '固定工位 · 关节与交接' },
  { id: 'cargo', name: '自由货物', detail: '接触、支撑与实际位置' },
  { id: 'station', name: '工位与交付点', detail: '当前场景坐标 · 只读' },
]
function metric(value: number | undefined, digits = 3): string {
  return value === undefined ? '未收到' : value.toFixed(digits)
}

export function CooperationView({ snapshot, now, frame, onBack, onStart, onCancel, onReset, onRefresh,
  displayedFrameSrc, visionFrame = null, displayedVisionSrc = null, active = true, canvas }: CooperationViewProps) {
  const [selected, setSelected] = useState<SelectedObject>('car')
  const { state, pending, receipt, resetReceipt, actionError, connectionError } = snapshot
  const connected = cooperationConnected(snapshot, now)
  const ready = connected && !!state?.ready
  const physics = state?.physics
  const task = state?.task
  const liveProfile = cooperationLiveProfile(state)
  const workflowOwned = liveProfile.workflowOwned
  const dockOnly = task?.scope === 'dock'
  const stages = dockOnly ? COOPERATION_STAGES.slice(0, 2) : COOPERATION_STAGES
  const stageLabel = cooperationStageLabel(task?.stage, task?.scope)
  const canStart = !workflowOwned && cooperationCanStart(snapshot, now)
  const canCancel = cooperationCanCancel(snapshot, now)
  const canReset = !workflowOwned && cooperationCanReset(snapshot, now)
  const resetSupported = !!state?.reset && !!state.episode_id
  const events = [...new Map((state?.events ?? []).map((event) => [event.sequence, event])).values()]
    .sort((first, second) => first.sequence - second.sequence)
  const carStopped = !!physics && Math.abs(physics.car.linear_speed) < 0.01 && Math.abs(physics.car.angular_speed) < 0.03
  const stageRole = COOPERATION_STAGES.find((item) => item.key === task?.stage)?.role
  const armPhase = dockOnly ? '本回合未执行装货' : stageRole === 'arm' ? stageLabel : task?.status === 'succeeded' ? '机械臂已退出' : '等待机械臂阶段反馈'
  const startReason = workflowOwned ? '当前三批任务由 workflow 派发；网页只读取反馈，不重复开始。'
    : resetReceipt || state?.reset?.pending ? '正在核对场景重置，暂不能派发新任务。'
    : receipt ? '正在核对原任务，暂不能重复派发。' : !connected ? '等待有效的协同服务状态。'
    : !state?.ready ? state?.reason : !canStart ? '当前任务尚未结束。' : '小车到固定工位装货，再驶向交付点。'
  const resetReason = workflowOwned ? '三批任务由原 workflow 创建下一回合，网页不竞争重置。'
    : resetReceipt ? '只读取原重置请求，请勿重复重置。' : !connected ? '等待有效的协同服务状态。'
    : state?.reset?.reason || '当前场景暂不能重置。'
  const resetCompleted = !resetReceipt && task?.status === 'idle' && state?.reset?.last?.status === 'succeeded'
    && state.reset.last.to_episode === state.episode_id
  const toolbar = <div className="cooperation-workspace-toolbar">
          <div className="cooperation-task-actions">
            <button type="button" className="cooperation-button cooperation-primary" disabled={!canStart} onClick={onStart} title={startReason}><Play size={16} aria-hidden="true" />开始装货运输</button>
            {resetSupported && <button type="button" className="cooperation-button cooperation-quiet" disabled={!canReset || !onReset} onClick={onReset} title={resetReason}><RefreshCw size={16} aria-hidden="true" />重置场景</button>}
            <button type="button" className="cooperation-button cooperation-cancel" disabled={!canCancel} onClick={onCancel}><Square size={15} aria-hidden="true" />取消当前任务</button>
          </div>
    <button type="button" className="cooperation-button cooperation-quiet" onClick={onRefresh} title="只读取最新状态" aria-label="读取最新反馈"><RefreshCw size={16} aria-hidden="true" /><span>读取反馈</span></button>
    <button type="button" className="cooperation-button cooperation-quiet cooperation-back" onClick={onBack} title="返回控制台" aria-label="返回控制台"><ArrowLeft size={16} aria-hidden="true" /><span>返回控制台</span></button>
  </div>
  const notice = <>
    {actionError && <div className="cooperation-error" role="alert">{actionError}</div>}
    {receipt && <div className="cooperation-receipt" role="status">
      <strong>{receipt.unknown ? '操作回执未知' : '已收到操作回执，正在核对任务状态'}</strong>
      <p>只读取任务 {receipt.taskId}。{receipt.action === 'cancel' ? '等待原任务取消或结束的反馈。' : '等待原任务接收或结束的反馈。'}</p>
    </div>}
    {resetReceipt && <div className="cooperation-receipt" role="status">
      <strong>{resetReceipt.unknown ? '场景重置回执未知' : '正在核对场景重置'}</strong>
      <p>只读取重置请求 {resetReceipt.requestId}，原回合 {resetReceipt.fromEpisode}。不重复重置，不自动开始运输。</p>
    </div>}

    <div className={`cooperation-readiness ${ready ? 'cooperation-ready' : ''}`} role="status">
      <span aria-hidden="true" /><strong>{ready ? '共享场景已就绪' : connected ? '暂不能开始' : '等待协同服务'}</strong>
      <p>{connectionError ?? (!connected && state ? '状态已过期，正在读取最新反馈。' : state?.reason ?? '正在连接共享场景与导航服务。')}</p>
    </div>
  </>
  const objects = <div className="workspace-object-list cooperation-object-list" aria-label="协同场景对象">
    {sceneObjects.map((object) => <button type="button" key={object.id} data-coop-object={object.id}
      aria-pressed={selected === object.id} onClick={() => setSelected(object.id)}>
      <span className="cooperation-object-marker" aria-hidden="true">{object.id === 'car' ? <Truck size={18} /> : object.id === 'cargo' ? <Box size={18} /> : object.id === 'station' ? <MapPin size={18} /> : <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 21h13M7 21v-6l6-5-3-6 3-2 5 8-6 7v4M18 10l3 3-3 3" /><circle cx="13" cy="10" r="2" /></svg>}</span>
      <span><strong>{object.id === 'car' ? liveProfile.vehicleName : object.name}</strong><small>{object.detail}</small></span>
    </button>)}
    <p className="cooperation-object-help">选择对象查看属性。对象与工位只读，不发送移动指令。</p>
  </div>
  const properties = <div className="workspace-properties cooperation-workspace-properties">
    <div className="cooperation-properties-heading"><strong>{selected === 'car' ? liveProfile.vehicleName : sceneObjects.find((object) => object.id === selected)?.name}</strong>
      <span>{connected ? '当前服务反馈' : '最近反馈 · 已过期'}</span></div>
    <section className="cooperation-telemetry" aria-label="实际物理反馈" data-current={connected}>
      <div hidden={selected !== 'car'} data-object-properties="car">
        <h2><Truck size={19} aria-hidden="true" />小车定位与运动</h2>
        <strong className="cooperation-telemetry-status">{physics ? carStopped ? '当前速度低于停稳阈值' : '当前小车有运动' : '等待小车反馈'}</strong>
        <dl><div><dt>物理位置</dt><dd>{physics ? `${metric(physics.car.x)}, ${metric(physics.car.y)} m` : '未收到'}</dd></div>
          <div><dt>物理朝向</dt><dd>{physics ? `${metric(physics.car.yaw * 180 / Math.PI, 1)}°` : '未收到'}</dd></div>
          <div><dt>线速度</dt><dd>{physics ? `${metric(physics.car.linear_speed)} m/s` : '未收到'}</dd></div>
          <div><dt>角速度</dt><dd>{physics ? `${metric(physics.car.angular_speed)} rad/s` : '未收到'}</dd></div>
          <div><dt>导航定位</dt><dd>{state?.nav?.pose ? `${metric(state.nav.pose.x)}, ${metric(state.nav.pose.y)} m` : '未收到'}</dd></div>
          <div><dt>Nav2</dt><dd>{state?.nav ? state.nav.ready ? '已就绪' : '未就绪' : '未收到'}</dd></div></dl>
      </div>
      <div hidden={selected !== 'arm'} data-object-properties="arm">
        <h2><svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 21h13M7 21v-6l6-5-3-6 3-2 5 8-6 7v4M18 10l3 3-3 3" /><circle cx="13" cy="10" r="2" /></svg>SO101 机械臂</h2>
        <strong className="cooperation-telemetry-status">{armPhase}</strong>
        <dl><div><dt>关节数量</dt><dd>{physics ? physics.arm.q.length : '未收到'}</dd></div>
          <div><dt>最大关节速度</dt><dd>{physics && physics.arm.velocity.length ? `${metric(Math.max(...physics.arm.velocity.map(Math.abs)))} rad/s` : '未收到'}</dd></div>
          <div className="cooperation-joints"><dt>实际关节角度</dt><dd>{physics && physics.arm.q.length ? physics.arm.q.map((value) => `${(value * 180 / Math.PI).toFixed(1)}°`).join(' / ') : '未收到'}</dd></div></dl>
        <p>{dockOnly ? '本回合仅验证停靠与停稳，不执行机械臂装货。' : '只有机械臂退出与货物放稳均确认后，小车才能出发。'}</p>
      </div>
      <div hidden={selected !== 'cargo'} data-object-properties="cargo">
        <h2><Box size={19} aria-hidden="true" />自由货物</h2>
        <strong className="cooperation-telemetry-status">{physics ? physics.cargo.tray_contact ? '检测到托盘接触' : '当前无托盘接触' : '等待货物反馈'}</strong>
        <dl><div><dt>位置</dt><dd>{physics ? `${metric(physics.cargo.x)}, ${metric(physics.cargo.y)} m` : '未收到'}</dd></div>
          <div><dt>高度</dt><dd>{physics ? `${metric(physics.cargo.z)} m` : '未收到'}</dd></div>
          <div><dt>速度</dt><dd>{physics ? `${metric(physics.cargo.speed)} m/s` : '未收到'}</dd></div>
          <div><dt>夹指接触力</dt><dd>{physics ? `${physics.cargo.tip_forces.map((value) => value.toFixed(2)).join(' / ') || '未收到'} N` : '未收到'}</dd></div></dl>
        <p>货物位置与接触来自物理反馈。</p>
      </div>
    </section>
    <section hidden={selected !== 'station'} data-object-properties="station" className="cooperation-station-properties">
      <h2>工位与交付点</h2>
          <div className="cooperation-stations">
            <div><MapPin size={15} aria-hidden="true" /><span>固定工位</span><strong>{state?.stations ? `${metric(state.stations.dock.x, 2)}, ${metric(state.stations.dock.y, 2)} m` : '等待坐标'}</strong></div>
            <div><CircleCheck size={15} aria-hidden="true" /><span>交付点</span><strong>{state?.stations ? `${metric(state.stations.delivery.x, 2)}, ${metric(state.stations.delivery.y, 2)} m` : '等待坐标'}</strong></div>
          </div>      <p>坐标由当前场景提供。选择对象不会修改位置或重新派发任务。</p>
    </section>
    <footer className="cooperation-source"><span>仅用于仿真 · 物理真值与导航定位分别显示</span><span>场景来源 SHA：{state?.source?.scene_sha || '等待服务发布'}</span></footer>
  </div>
  const taskPanel = <div className="cooperation-workspace-task">
        <CooperationSceneProfilePanel state={state} />
        <div className="cooperation-process">
          <h2>{dockOnly ? '停靠流程' : '装货运输流程'}</h2>
          <ol>{stages.map((stage, index) => <li key={stage.key} aria-current={stage.key === task?.stage || (dockOnly && task?.status === 'succeeded' && stage.key === 'dock_stopped') ? 'step' : undefined}>
            <span>{index + 1}</span><strong>{stage.label}</strong>
          </li>)}</ol>
          <p>当前阶段：<strong>{stageLabel}</strong>。阶段由协同服务的实际反馈更新。</p>
          <p>{state?.perception?.mode === 'vision' ? '近距离精停靠使用 AprilTag 图像观测；检测失败时不回退到理想信标。'
            : state?.perception?.mode === 'perturbed' ? '近距离精停靠使用受扰仿真信标；未接入视觉识别。'
              : state?.perception && state.perception.mode !== 'ideal' ? `当前停靠感知模式：${state.perception.mode}。等待已确认的感知来源。`
                : '近距离精停靠使用理想化仿真信标；未接入视觉识别。'}</p>
        </div>
      <aside className="cooperation-sidebar">
        <section className="cooperation-task" aria-labelledby="cooperation-task-heading">
          <div className="cooperation-section-heading"><h2 id="cooperation-task-heading">{dockOnly ? '停靠任务' : '装货运输任务'}</h2><Truck size={20} aria-hidden="true" /></div>
          <div className={`cooperation-task-state cooperation-task-${task?.status ?? 'idle'}`} role="status">
            <strong>{pending === 'reset' ? '正在提交场景重置' : pending === 'start' ? '正在派发任务' : pending === 'cancel' ? '正在发送取消' : cooperationStatusLabel(task?.status, task?.scope)}</strong>
            <p>{task?.message || '开始后，小车先驶向固定 SO101 工位。'}</p>
            {task?.id && <small>任务 {task.id}</small>}
            {state?.episode_id && <small>当前回合 {state.episode_id}</small>}
          </div>
          {task?.stop_reason && <p className="cooperation-stop-reason">停止原因：{task.stop_reason}</p>}
          <p className="cooperation-action-help">{startReason}</p>
          {resetSupported && <p className="cooperation-action-help">{workflowOwned ? '三批回合由原 workflow 重置和继续派发，网页保留只读反馈。'
            : <>重置只创建新的合成回合，并保留历史记录。重置完成后，请再点击“开始装货运输”。{!canReset && !resetCompleted ? ` ${resetReason}` : ''}</>}</p>}
          {resetCompleted && <p className="cooperation-action-help" role="status">{ready ? workflowOwned ? '新回合已就绪，等待原 workflow 继续派发。' : '新回合已就绪，请点击开始装货运输。' : '新回合已创建，等待共享物理世界与导航就绪。'}</p>}
          {!resetSupported && task?.status === 'succeeded' && <p className="cooperation-action-help">当前协同服务不支持网页重置；需要启动新的合成回合。</p>}
          {task?.status === 'running' && snapshot.ownedTaskId !== task.id && <p className="cooperation-action-help">{workflowOwned ? '当前任务由原 workflow 发起。这里只读取反馈。' : '当前任务由另一页面发起。这里只读取反馈。'}</p>}
          <CommandEvidencePanel evidence={projectCooperationEvidence(task ?? null, snapshot.receipt, { pending: !!pending, expectedTaskId: snapshot.ownedTaskId })} />

        </section>
        <section className="cooperation-dialogue" aria-labelledby="cooperation-dialogue-heading">
          <div className="cooperation-section-heading"><div><h2 id="cooperation-dialogue-heading">合作对话</h2><p>每条消息来自实际动作反馈。</p></div><span>{events.length} 条</span></div>
          {state && <EventContinuity events={state.events} episodeId={state.episode_id ?? null} taskId={state.task.id} />}
          {events.length ? <ol>{events.map((event) => <li key={event.sequence} className={`cooperation-event-${event.role}`}>
            <div><strong>{{ car: liveProfile.vehicleName, arm: 'SO101', system: '协同服务' }[event.role]}</strong><time>{event.time_s.toFixed(2)} s</time></div>
            <p>{event.message}</p>
          </li>)}</ol> : <div className="cooperation-dialogue-empty"><p>尚未收到合作消息。</p><span>开始任务后，这里记录小车和机械臂的实际回应。</span></div>}
        </section>
        {!!state?.history?.length && <section className="cooperation-dialogue" aria-labelledby="cooperation-history-heading">
          <div className="cooperation-section-heading"><div><h2 id="cooperation-history-heading">历史回合</h2><p>以下记录由协同服务保存，场景重置不会删除已完成记录。</p></div><span>{state.history.length} 条</span></div>
          <ol>{[...state.history].reverse().map((entry) => <li key={`${entry.episode_id}-${entry.task.id}`}>
            <details>
              <summary data-history-task>{cooperationStatusLabel(entry.task.status, entry.task.scope)} · 记录时间 {new Date(typeof entry.completed_at === 'number' ? entry.completed_at * 1000 : entry.completed_at).toLocaleString('zh-CN')}</summary>
              <p>回合 {entry.episode_id}{entry.task.id ? `，任务 ${entry.task.id}` : ''}</p>
              <p>{entry.task.message}</p>
              {entry.task.stop_reason && <p>停止原因：{entry.task.stop_reason}</p>}
              <ol>{[...new Map(entry.events.map((event) => [event.sequence, event])).values()].sort((a, b) => a.sequence - b.sequence).map((event) => <li key={event.sequence}>
                <div><strong>{{ car: liveProfile.vehicleName, arm: 'SO101', system: '协同服务' }[event.role]}</strong><time>{event.time_s.toFixed(2)} s</time></div>
                <p>{event.message}</p>
              </li>)}</ol>
            </details>
          </li>)}</ol>
        </section>}
      </aside>  </div>
  return <WorkspaceSurface id="cooperation" title="车臂协同" active={active}
    subtitle={`共享 MuJoCo · ROS 域 ${COOPERATION_DOMAIN} · 固定 SO101 工位装货与运输`}
    toolbar={toolbar} notice={notice} objects={objects} properties={properties} task={taskPanel}
    canvas={canvas ?? <CooperationCanvasView snapshot={snapshot} now={now} frame={frame} displayedFrameSrc={displayedFrameSrc}
      visionFrame={visionFrame} displayedVisionSrc={displayedVisionSrc} />} />
}
