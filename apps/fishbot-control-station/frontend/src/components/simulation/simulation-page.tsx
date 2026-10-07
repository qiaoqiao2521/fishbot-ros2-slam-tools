import { useState } from 'react'
import { ArrowLeft, Box, Check, Home, MapPin, Play, Route, Square, Trash2, X } from 'lucide-react'

import { SimulationMapView } from '@/components/simulation/simulation-map'
import { useSimulation } from '@/hooks/use-simulation'
import {
  DEMO_WAYPOINTS, MAX_WAYPOINTS, isFreeWaypoint, missionIsActive, missionLabel,
  type Point, type Pose,
} from '@/lib/simulation'
import './simulation.css'

export function SimulationPage({ onBack }: { onBack: () => void }) {
  const { state, map, connectionError, mapError, actionError, pending, act } = useSimulation()
  const [waypoints, setWaypoints] = useState<Pose[]>([])
  const [returnHome, setReturnHome] = useState(true)
  const [selectionMessage, setSelectionMessage] = useState('')
  const active = missionIsActive(state)
  const connected = state !== null && !connectionError
  const ready = connected && state.ready && !!map && !mapError
  const editable = !active && !pending
  const displayedPoints = active ? state!.mission.waypoints : waypoints
  const mission = state?.mission
  const error = actionError ?? connectionError ?? mapError
  const physical = state?.truth
  const obstacleLabel = {
    parked: '箱子已退回', moving: '箱子正在进入路面', blocking: '箱子挡在前方',
    returning: '箱子正在退出路面', error: '障碍箱控制异常',
  }[state?.obstacle.state ?? ''] ?? '等待障碍箱状态'

  function selectPoint(point: Point) {
    if (!map || !editable) return
    if (waypoints.length >= MAX_WAYPOINTS) {
      setSelectionMessage(`最多添加 ${MAX_WAYPOINTS} 个点，请先移除一个点。`)
      return
    }
    if (!isFreeWaypoint(point, map)) {
      setSelectionMessage('这里太靠近障碍或地图边缘，请选空旷的位置。')
      return
    }
    setWaypoints((current) => [...current, { x: Number(point.x.toFixed(2)), y: Number(point.y.toFixed(2)), yaw: 0 }])
    setSelectionMessage(`已添加第 ${waypoints.length + 1} 个点。`)
  }

  function loadDemo() {
    if (!map || !editable) return
    if (!DEMO_WAYPOINTS.every((point) => isFreeWaypoint(point, map))) {
      setSelectionMessage('当前地图不适用这条演示路线，请直接在地图上选点。')
      return
    }
    setWaypoints(DEMO_WAYPOINTS.map((point) => ({ ...point })))
    setSelectionMessage('三点路线已载入，点击“开始巡逻”派发。')
  }

  const statusText = !connected ? state ? '连接中断，正在重连' : '正在连接仿真'
    : ready ? active ? '导航运行中' : '已就绪，可以派发' : '等待仿真就绪'
  const progressText = mission?.status === 'running'
    ? mission.return_home && mission.current_index === mission.waypoints.length - 1
      ? '正在返回起点' : `正在前往第 ${mission.current_index + 1} / ${mission.waypoints.length} 个点`
    : mission?.status === 'succeeded' ? `已完成 ${mission.waypoints.length} 个导航点`
      : mission?.status === 'canceling' ? '等待导航取消并停稳'
        : '选点后派发，小车会依次前往。'

  return (
    <div className="simulation-page">
      <header className="simulation-header">
        <div>
          <div className="simulation-mode"><span aria-hidden="true" />MuJoCo 物理仿真 <span className="simulation-domain">仿真域 93</span></div>
          <h1>小鱼巡逻</h1>
          <p>在地图上安排路线，看小车绕障、到点，再回到起点。</p>
        </div>
        <button type="button" className="simulation-button simulation-quiet" onClick={onBack}><ArrowLeft size={16} />返回控制台</button>
      </header>

      <div className={`simulation-readiness ${ready ? 'simulation-ready' : 'simulation-waiting'}`} role="status">
        <span className="simulation-status-dot" aria-hidden="true" />
        <strong>{statusText}</strong>
        <span>{connectionError ? '请检查仿真启动窗口。' : state?.reason || '等待地图、定位与导航服务。'}</span>
      </div>

      {error && <div className="simulation-error" role="alert">{error}</div>}

      <main className="simulation-layout">
        <section className="simulation-scene" aria-labelledby="simulation-map-title">
          <div className="simulation-scene-header">
            <div>
              <h2 id="simulation-map-title">{active ? '巡逻正在进行' : '点地图，安排一圈巡逻'}</h2>
              <p>{active ? '蓝色是小鱼，绿色线是当前导航路径。' : '点击空旷处添加巡逻点，编号就是前往的顺序。'}</p>
            </div>
            <button type="button" className="simulation-button simulation-quiet" disabled={!map || !editable} onClick={loadDemo}><Route size={16} />载入三点路线</button>
          </div>

          <div className="simulation-map-stage">
            {map ? <SimulationMapView map={map} state={state} points={displayedPoints} editable={editable} onSelect={selectPoint} />
              : <div className="simulation-map-empty"><MapPin size={34} /><strong>等待仿真地图</strong><p>地图发布后，就能在这里选点。</p></div>}
          </div>

          <div className="simulation-map-footer">
            <div className="simulation-legend" aria-label="地图图例">
              <span><i className="simulation-legend-robot" />小鱼实际位置</span>
              <span><i className="simulation-legend-path" />导航路径</span>
              <span><i className="simulation-legend-obstacle" />移动障碍</span>
            </div>
            {map && <span>{(map.width * map.resolution).toFixed(1)} × {(map.height * map.resolution).toFixed(1)} 米</span>}
          </div>
          <div className="simulation-position">
            <span>{connected ? '实际位置' : '上次位置'} {physical ? `(${physical.x.toFixed(2)}, ${physical.y.toFixed(2)}) 米` : '等待数据'}</span>
            <span>速度 {physical ? `${Math.abs(physical.linear_speed).toFixed(2)} 米/秒` : '—'}</span>
            <span>车头 {physical ? `${(physical.yaw * 180 / Math.PI).toFixed(0)}°` : '—'}</span>
          </div>
          <p className="simulation-keyboard-note">键盘选点：聚焦地图后，用方向键移动十字，回车添加。</p>
        </section>

        <aside className="simulation-sidebar" aria-label="巡逻任务">
          <section className="simulation-task">
            <div className="simulation-task-heading"><h2>巡逻路线</h2><span>{active ? displayedPoints.length : waypoints.length} 个点</span></div>
            <div className={`simulation-mission-state simulation-mission-${mission?.status ?? 'idle'}`} aria-live="polite">
              <strong>{missionLabel(mission?.status)}</strong>
              <p>{progressText}</p>
              {mission?.message && mission.status !== 'idle' && <small>{mission.message}</small>}
            </div>

            {displayedPoints.length ? <ol className="simulation-waypoints">
              {displayedPoints.map((point, index) => {
                const current = active && index === mission?.current_index
                const done = active && index < (mission?.current_index ?? 0)
                const isHome = active && mission?.return_home && index === displayedPoints.length - 1
                return <li key={`${index}-${point.x}-${point.y}`} className={current ? 'simulation-waypoint-current' : ''}>
                  <span className="simulation-waypoint-number">{done ? <Check size={14} /> : index + 1}</span>
                  <div><strong>{isHome ? '返回起点' : `巡逻点 ${index + 1}`}</strong><span>({point.x.toFixed(2)}, {point.y.toFixed(2)}) 米</span></div>
                  {current ? <span className="simulation-waypoint-tag">前往中</span> : editable && <button type="button" aria-label={`移除巡逻点 ${index + 1}`} onClick={() => setWaypoints((values) => values.filter((_, i) => i !== index))}><X size={16} /></button>}
                </li>
              })}
            </ol> : <div className="simulation-queue-empty"><MapPin size={22} /><p>地图上选几个点，或载入三点路线。</p></div>}

            <p className="simulation-selection-message" aria-live="polite">{selectionMessage}</p>
            <label className="simulation-return-home"><input type="checkbox" checked={active ? !!mission?.return_home : returnHome} disabled={!editable} onChange={(event) => setReturnHome(event.target.checked)} /><Home size={16} /><span>巡逻结束后返回起点</span></label>
            <div className="simulation-mission-actions">
              <button type="button" className="simulation-button simulation-primary" disabled={!ready || !editable || waypoints.length === 0}
                onClick={() => void act('mission', { waypoints, return_home: returnHome, issued_at: Date.now() / 1000 })}><Play size={17} />{pending === 'mission' ? '正在派发…' : '开始巡逻'}</button>
              <button type="button" className="simulation-button simulation-cancel" disabled={!active || !!pending || mission?.status === 'canceling'} onClick={() => void act('cancel')}><Square size={15} />{mission?.status === 'canceling' ? '正在取消…' : '取消任务'}</button>
            </div>
            <button type="button" className="simulation-clear-queue" disabled={!editable || waypoints.length === 0} onClick={() => { setWaypoints([]); setSelectionMessage('待派发巡逻点已清空。') }}><Trash2 size={14} />清空待派发点</button>
          </section>

          <section className="simulation-obstacle" aria-labelledby="simulation-obstacle-title">
            <div><Box size={19} /><h2 id="simulation-obstacle-title">试试突然挡路</h2></div>
            <p>巡逻途中，让箱子驶入小车前方，观察减速与避障；箱子随后自动退回。</p>
            <strong aria-live="polite">{obstacleLabel}</strong>
            <div className="simulation-obstacle-actions">
              <button type="button" className="simulation-button simulation-quiet" disabled={!ready || mission?.status !== 'running' || !!pending || state?.obstacle.state !== 'parked'} onClick={() => void act('obstacle', { action: 'block' })}>移入障碍</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!connected || !!pending || !state?.obstacle || state.obstacle.state === 'parked' || state.obstacle.state === 'returning'} onClick={() => void act('obstacle', { action: 'clear' })}>移走障碍</button>
            </div>
          </section>
          <p className="simulation-boundary">当前操作只作用于 MuJoCo 仿真。</p>
        </aside>
      </main>
    </div>
  )
}
