import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowUp, Box, Check, Eye, Home, MapPin, Monitor, Play, RefreshCw, Route, Save, ShieldBan, Square, Trash2, Undo2, X } from 'lucide-react'

import { SimulationMapView } from '@/components/simulation/simulation-map'
import { useSimulation } from '@/hooks/use-simulation'
import { useSimulationWorkspace } from '@/hooks/use-simulation-workspace'
import { useRviz } from '@/hooks/use-rviz'
import { calculatePolylineDistance, PatrolMissionTracker } from '@/lib/patrol-mission'
import { MapZonesManager } from '@/lib/map-zones'
import { goalDraftIdentity, goalIssueMatchesWaypoint, mapRuleErrorMessage } from '@/lib/simulation-errors'
import { MAX_MAP_ZONES, mapGeneration, missionElapsedSeconds, routeDraft, rulesDirty, ruleStartBlock, zoneFromSelection, zonesEqual, type MapEditMode, type SavedRoute } from '@/lib/simulation-workspace'
import {
  MAX_WAYPOINTS, SIMULATION_DOMAIN, collisionMonitorText, isFreeWaypoint, missionCanRetryCancel,
  missionIsActive, missionLabel, missionProgressText,
  type Point, type Pose,
} from '@/lib/simulation'
import './simulation.css'

export function SimulationPage({ onBack, onCooperation }: { onBack: () => void; onCooperation?: () => void }) {
  const { state, map, connectionError, mapError, actionError, goalIssue, pending, missionRequestUnknown, act } = useSimulation()
  const rviz = useRviz()
  const mapStage = useRef<HTMLDivElement>(null)
  const [waypoints, setWaypoints] = useState<Pose[]>([])
  const [returnHome, setReturnHome] = useState(true)
  const [homeEmphasized, setHomeEmphasized] = useState(false)
  const [attemptedDraft, setAttemptedDraft] = useState<string | null>(null)
  const [selectionMessage, setSelectionMessage] = useState('')
  const [editMode, setEditMode] = useState<MapEditMode>('waypoint')
  const [routeName, setRouteName] = useState('')
  const generation = mapGeneration(map)
  const active = missionIsActive(state)
  const connected = state !== null && !connectionError
  const ready = connected && state.ready && !!map && !mapError
  const blocked = active || !!pending || missionRequestUnknown || !connected
  const workspace = useSimulationWorkspace(map, blocked)
  const { editor, dispatch, rulesError, routes, routesError, runs, runsError, routeWrite, routeMessage, refreshing, refresh, saveRules, saveRoute, exporting, exportMessage, exportRules } = workspace
  const writing = editor.writeState === 'saving' || routeWrite === 'saving'
  const editable = !blocked && !writing && editor.writeState !== 'unknown'
  const rulesReady = !!map && editor.mapId === map.map_id && !rulesError
  const startBlock = ruleStartBlock(editor, rulesReady)
  const dirty = rulesDirty(editor)

  useEffect(() => {
    setWaypoints([])
    setReturnHome(true)
    setEditMode('waypoint')
    setRouteName('')
    setAttemptedDraft(null)
    setHomeEmphasized(false)
    setSelectionMessage('地图已更换，旧路线和规则草稿已清除。')
  }, [generation])
  const displayedPoints = active ? state!.mission.waypoints : waypoints
  const mission = state?.mission
  const elapsedSeconds = missionElapsedSeconds(mission, runs, map?.map_id)
  const patrolDraft = useMemo(() => {
    const draft = new PatrolMissionTracker({ returnHomeOnComplete: returnHome, maxDurationSeconds: 360 })
    for (const point of waypoints) draft.addWaypoint(point, point.yaw)
    return draft
  }, [waypoints, returnHome])
  const routeDistance = useMemo(() => calculatePolylineDistance(displayedPoints), [displayedPoints])
  let geometryMessage = ''
  try {
    const points = active ? state!.path : [...(state?.pose ? [state.pose] : []), ...waypoints]
    const hit = MapZonesManager.fromMapRulesZones(editor.zones).checkPathCollision(points, .13)
    if (hit.hasCollision) geometryMessage = `${active ? '收到的导航路径' : '点间直线预览'}与${hit.collisionType === 'wall' ? '虚拟墙' : '禁区'}接触（${hit.collidedEntityId}）。实际绕行与放行以 Nav2 为准。`
  } catch (error) { geometryMessage = error instanceof Error ? error.message : '草稿几何检查暂不可用。' }
  const awaitingAcceptance = mission?.status === 'running' && mission.dispatch_state === 'pending'
  const unknownAcceptance = mission?.status === 'canceling' && mission.dispatch_state === 'unavailable'
  const canRetryCancel = missionCanRetryCancel(mission)
  const collisionMonitor = state?.collision_monitor
  const issueSameMap = !!goalIssue && !!map?.map_id && goalIssue.map_id === map.map_id
  const issueCurrent = issueSameMap && attemptedDraft === goalDraftIdentity(waypoints, returnHome)
    && !!editor.saved && goalIssue!.rules_revision === editor.saved.revision && zonesEqual(editor.zones, editor.saved.zones)
  const error = mapRuleErrorMessage(actionError, editor.zones, goalIssue) ?? connectionError ?? mapError
  const physical = state?.truth
  const obstacleLabel = {
    parked: '箱子已退回', moving: '箱子正在进入路面', blocking: '箱子挡在前方',
    returning: '箱子正在退出路面', error: '障碍箱控制异常',
  }[state?.obstacle.state ?? ''] ?? '等待障碍箱状态'
  const showReturnHome = active ? !!mission?.return_home : returnHome

  function selectPoint(point: Point) {
    if (!map || !editable || editMode === 'observe') return
    if (editMode === 'wall' || editMode === 'no_go') {
      if (!rulesReady) { setSelectionMessage('地图规则未读回，暂不能编辑。'); return }
      if (!editor.anchor) {
        dispatch({ type: 'anchor', point })
        setSelectionMessage(editMode === 'wall' ? '已选墙起点，请选择终点。' : '已选禁区一角，请选择对角。')
        return
      }
      try {
        if (editor.zones.length >= MAX_MAP_ZONES) throw new Error(`最多保存${MAX_MAP_ZONES}个规则，请先移除一项。`)
        dispatch({ type: 'add', zone: zoneFromSelection(editMode, editor.anchor, point, crypto.randomUUID()) })
        setSelectionMessage('规则草稿已添加；点击“保存规则”才会发布。')
      } catch (error) { setSelectionMessage(error instanceof Error ? error.message : '规则选择无效。') }
      return
    }
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

  function changeMode(mode: MapEditMode) {
    if (!editable) return
    dispatch({ type: 'anchor', point: null })
    setEditMode(mode)
    setSelectionMessage({ waypoint: '点击空旷位置添加巡逻点。', wall: '选择两个点定义虚拟墙；只保存软件规则。',
      no_go: '选择两个对角定义矩形禁区。', observe: '观察模式不创建草稿，也不发送命令。' }[mode])
  }

  function loadRoute(route: SavedRoute) {
    if (!editable || !editor.mapId || !map) return
    try {
      const draft = routeDraft(route, editor.mapId)
      if (!draft.waypoints.every((point) => isFreeWaypoint(point, map))) throw new Error('路线包含当前地图不可达点，请重新安排。')
      setWaypoints(draft.waypoints)
      setReturnHome(draft.returnHome)
      setRouteName(route.name)
      dispatch({ type: 'anchor', point: null })
      setEditMode('waypoint')
      setSelectionMessage(`“${route.name}”已载入草稿；尚未派发任务。`)
    } catch (error) { setSelectionMessage(error instanceof Error ? error.message : '路线无法载入。') }
  }

  function reorderPoint(index: number, delta: number) {
    if (!editable) return
    setWaypoints((current) => {
      const next = [...current], other = index + delta
      if (other < 0 || other >= next.length) return current
      ;[next[index], next[other]] = [next[other], next[index]]
      return next
    })
  }

  function locateProblem() {
    if (!issueSameMap) return
    mapStage.current?.scrollIntoView({ block: 'center' })
    mapStage.current?.focus({ preventScroll: true })
  }

  function locateReturnHome() {
    setHomeEmphasized(true)
    mapStage.current?.scrollIntoView({ block: 'center' })
    mapStage.current?.focus({ preventScroll: true })
  }

  function startMission() {
    if (!editor.mapId || !editor.saved) return
    try {
      const payload = patrolDraft.toMissionPayload({ issuedAt: Date.now() / 1000, mapId: editor.mapId, rulesRevision: editor.saved.revision })
      setAttemptedDraft(goalDraftIdentity(waypoints, returnHome))
      void act('mission', payload)
    } catch (error) { setSelectionMessage(error instanceof Error ? error.message : '巡逻草稿无效。') }
  }

  const ruleStatus = editor.writeState === 'saving' ? '正在保存规则…' : editor.writeState === 'unknown' ? '保存结果未知'
    : !rulesReady ? '规则尚未接入或未读回' : editor.saved?.apply_state === 'applied' ? `导航已应用 · 版本 ${editor.saved.revision}`
      : editor.saved?.apply_state === 'published' ? '已发布，等待导航确认' : '规则未应用'

  const statusText = !connected ? state ? '连接中断，正在重连' : '正在连接仿真'
    : ready ? unknownAcceptance ? 'Nav2 接收状态未知' : awaitingAcceptance ? '等待 Nav2 确认'
      : mission?.status === 'canceling' ? '正在取消任务'
        : active ? '导航运行中' : '已就绪，可以派发' : '等待仿真就绪'
  const progressText = missionProgressText(mission)
  const sceneTitle = active ? unknownAcceptance ? '原任务接收状态未知' : awaitingAcceptance ? '等待 Nav2 确认任务'
    : mission?.status === 'canceling' ? '正在收束巡逻任务' : '巡逻正在进行' : '点地图，安排一圈巡逻'

  return (
    <div className="simulation-page">
      <header className="simulation-header">
        <div>
          <div className="simulation-mode"><span aria-hidden="true" />MuJoCo 物理仿真 <span className="simulation-domain">仿真域 {SIMULATION_DOMAIN}</span></div>
          <h1>小鱼巡逻</h1>
          <p>在地图上编辑通行规则、保存路线，再安排一圈巡逻。</p>
        </div>
        <div className="simulation-header-actions">
          {onCooperation && <button type="button" className="simulation-button simulation-quiet" onClick={onCooperation}>固定工位 · 车臂协同</button>}
          <button type="button" className="simulation-button simulation-quiet" disabled={rviz.pending || rviz.status?.available === false}
            onClick={() => void rviz.open()}><Monitor size={16} />{rviz.pending ? '正在连接 RViz…' : rviz.unknown ? '确认 RViz 状态' : '打开 RViz'}</button>
          <button type="button" className="simulation-button simulation-quiet" onClick={onBack}><ArrowLeft size={16} />返回控制台</button>
        </div>
      </header>

      <p className="simulation-rviz-status" role="status">{rviz.message} 窗口显示在控制站电脑，手机可发起打开。</p>

      <div className={`simulation-readiness ${ready ? 'simulation-ready' : 'simulation-waiting'}`} role="status">
        <span className="simulation-status-dot" aria-hidden="true" />
        <strong>{statusText}</strong>
        <span>{connectionError ? '请检查仿真启动窗口。' : state?.reason || '等待地图、定位与导航服务。'}</span>
      </div>

      {missionRequestUnknown && <div className="simulation-error" role="status">派发回执未知，正在读取原任务状态；暂不能重复派发或编辑。</div>}
      {error && <div className="simulation-error" role="alert">
        <p>{error}</p>
        {goalIssue && !issueCurrent && <p className="simulation-issue-stale">此提示来自上一版路线或规则，重新派发前请检查。{!issueSameMap ? '地图已不同，不在当前地图标记。' : '地图中的琥珀色标记仅表示上次拒绝的坐标。'}</p>}
        {issueSameMap && <button type="button" className="simulation-button simulation-locate-issue" onClick={locateProblem}><MapPin size={16} />{issueCurrent ? '在地图上定位问题' : '定位上次问题'}</button>}
      </div>}

      <main className="simulation-layout">
        <section className="simulation-scene" aria-labelledby="simulation-map-title">
          <div className="simulation-scene-header">
            <div>
              <h2 id="simulation-map-title">{sceneTitle}</h2>
              <p>{active ? '蓝色是小鱼，绿色线是当前导航路径。' : '点击空旷处添加巡逻点，编号就是前往的顺序。'}</p>
            </div>
          </div>

          <div className="simulation-map-tools" aria-label="地图编辑模式">
            {([{ mode: 'waypoint', label: '巡逻点', icon: MapPin }, { mode: 'wall', label: '虚拟墙', icon: Route },
              { mode: 'no_go', label: '禁区', icon: ShieldBan }, { mode: 'observe', label: '观察', icon: Eye }] as const).map(({ mode, label, icon: Icon }) =>
              <button key={mode} type="button" className={`simulation-button simulation-quiet ${editMode === mode ? 'simulation-tool-selected' : ''}`}
                disabled={!map || !editable || ((mode === 'wall' || mode === 'no_go') && !rulesReady)} aria-pressed={editMode === mode} onClick={() => changeMode(mode)}><Icon size={15} />{label}</button>)}
          </div>
          <div className="simulation-rule-strip">
            <span role="status">{ruleStatus}{dirty ? ' · 有未保存草稿' : ''}</span>
            <div>
              <button type="button" className="simulation-button simulation-quiet" disabled={!editable || (!editor.anchor && !editor.history.length)} onClick={() => dispatch({ type: 'undo' })}><Undo2 size={14} />撤销</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!editable || !!editor.anchor || !editor.future.length} onClick={() => dispatch({ type: 'redo' })}>重做</button>
              <button type="button" className="simulation-button simulation-primary" disabled={!editable || !rulesReady || !dirty || !!editor.anchor || editor.baseRevision !== editor.saved?.revision}
                onClick={() => void saveRules()}><Save size={14} />保存规则</button>
            </div>
          </div>
          <p className="simulation-map-guidance" aria-live="polite">{selectionMessage || (editMode === 'wall' ? '选择墙的两个端点。' : editMode === 'no_go' ? '选择矩形的两个对角。' : editMode === 'observe' ? '只观察，不发送指令。' : '点击空旷处添加巡逻点。')}</p>
          <div className="simulation-map-stage" ref={mapStage} tabIndex={-1} aria-label="巡逻地图视图">
            {map ? <SimulationMapView map={map} state={state} points={displayedPoints} editable={editable && editMode !== 'observe'} onSelect={selectPoint} mode={editMode}
              zones={editor.zones} savedZones={editor.saved?.zones} anchor={editor.anchor} goalIssue={goalIssue} issueCurrent={issueCurrent} homeEmphasized={homeEmphasized} onCancelSelection={() => dispatch({ type: 'anchor', point: null })} />
              : <div className="simulation-map-empty"><MapPin size={34} /><strong>等待仿真地图</strong><p>地图发布后，就能在这里选点。</p></div>}
          </div>

          <div className="simulation-map-footer">
            <div className="simulation-legend" aria-label="地图图例">
              <span><i className="simulation-legend-robot" />小鱼实际位置</span>
              <span><i className="simulation-legend-path" />导航路径</span>
              <span><i className="simulation-legend-obstacle" />移动障碍</span>
              <span><i className="simulation-legend-wall" />软件虚拟墙</span>
              <span><i className="simulation-legend-zone" />禁区 · 虚线为草稿</span>
            </div>
            {map && <span>{(map.width * map.resolution).toFixed(1)} × {(map.height * map.resolution).toFixed(1)} 米</span>}
          </div>
          <div className="simulation-position">
            <span>{connected ? '实际位置' : '上次位置'} {physical ? `(${physical.x.toFixed(2)}, ${physical.y.toFixed(2)}) 米` : '等待数据'}</span>
            <span>速度 {physical ? `${Math.abs(physical.linear_speed).toFixed(2)} 米/秒` : '—'}</span>
            <span>车头 {physical ? `${(physical.yaw * 180 / Math.PI).toFixed(0)}°` : '—'}</span>
          </div>
          <p className="simulation-keyboard-note">键盘选点：聚焦地图后，用方向键移动十字，回车选点，Esc取消当前选择。</p>
        </section>

        <aside className="simulation-sidebar" aria-label="巡逻任务">
          <section className="simulation-task simulation-rules" aria-labelledby="simulation-rules-title">
            <div className="simulation-task-heading"><h2 id="simulation-rules-title">地图规则</h2><span>{editor.zones.length} 项</span></div>
            <p className="simulation-panel-note">软件规则限制导航通行，不改变实体墙，也不会生成雷达回波。</p>
            {(rulesError || editor.error) && <p className="simulation-inline-error" role="alert">{editor.error || rulesError}</p>}
            {editor.saved?.message && <p className="simulation-panel-note">{editor.saved.message}</p>}
            {editor.saved && editor.baseRevision !== editor.saved.revision && <p className="simulation-inline-error" role="alert">规则版本已更新。请恢复最新规则，再重新编辑。</p>}
            {editor.zones.length > 0 && <ul className="simulation-rule-list">{editor.zones.map((zone, index) => <li key={zone.id} className={issueCurrent && goalIssue?.rule_id === zone.id ? 'simulation-rule-issue' : ''}>
              <span>{zone.kind === 'wall' ? '虚拟墙' : '禁区'} {index + 1}</span>
              <button type="button" aria-label={`移除${zone.kind === 'wall' ? '虚拟墙' : '禁区'} ${index + 1}`} disabled={!editable}
                onClick={() => dispatch({ type: 'remove', id: zone.id })}><X size={16} /></button>
            </li>)}</ul>}
            <div className="simulation-resource-actions">
              <button type="button" className="simulation-button simulation-quiet" disabled={!editable || !editor.saved || !dirty} onClick={() => dispatch({ type: 'restore' })}>恢复已保存</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!map || refreshing || writing} onClick={() => void refresh()}><RefreshCw size={14} />{refreshing ? '正在读取…' : '读取规则与路线'}</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!editor.saved || dirty || editor.saved.apply_state !== 'applied' || exporting} onClick={() => void exportRules()}>{exporting ? '正在导出…' : '导出 Nav2 规则'}</button>
            </div>
            {exportMessage && <p className="simulation-panel-note" role="status">{exportMessage}</p>}
          </section>
          <section className="simulation-task">
            <div className="simulation-task-heading"><h2>巡逻路线</h2><span>{active ? displayedPoints.length : waypoints.length} 个点</span></div>
            <p className="simulation-panel-note">航点间直线 {routeDistance.toFixed(2)} 米，不含绕障。任务终态以 ROS 回执为准。</p>
            {elapsedSeconds !== null && <p className="simulation-panel-note">任务耗时 {elapsedSeconds.toFixed(1)} 秒</p>}
            {geometryMessage && <p className="simulation-panel-note" role="status">{geometryMessage}</p>}
            <div className={`simulation-mission-state simulation-mission-${mission?.status ?? 'idle'}`} aria-live="polite">
              <strong>{missionLabel(mission?.status, mission?.dispatch_state)}</strong>
              <p>{progressText}</p>
              {mission?.message && mission.status !== 'idle' && <small>{mission.message}</small>}
              {mission?.stop_reason && <small>取消触发原因：{mission.stop_reason}</small>}
            </div>

            {displayedPoints.length ? <ol className="simulation-waypoints">
              {displayedPoints.map((point, index) => {
                const current = mission?.status === 'running' && !awaitingAcceptance && index === mission.current_index
                const done = active && index < (mission?.current_index ?? 0)
                const isHome = active && mission?.return_home && index === displayedPoints.length - 1
                const rejected = issueCurrent && !!goalIssue && goalIssueMatchesWaypoint(goalIssue, index, point)
                return <li key={`${index}-${point.x}-${point.y}`} className={[current ? 'simulation-waypoint-current' : '', rejected ? 'simulation-waypoint-issue' : ''].filter(Boolean).join(' ')}>
                  <span className="simulation-waypoint-number">{done ? <Check size={14} /> : index + 1}</span>
                  <div><strong>{isHome ? '返回本次出发点' : `巡逻点 ${index + 1}`}</strong><span>({point.x.toFixed(2)}, {point.y.toFixed(2)}) 米</span>{rejected && <small className="simulation-rejected-point-label">此点被拒绝</small>}</div>
                  {current ? <span className="simulation-waypoint-tag">前往中</span> : editable && <div className="simulation-waypoint-edit">
                    <button type="button" aria-label={`上移巡逻点 ${index + 1}`} disabled={index === 0} onClick={() => reorderPoint(index, -1)}><ArrowUp size={14} /></button>
                    <button type="button" aria-label={`下移巡逻点 ${index + 1}`} disabled={index === displayedPoints.length - 1} onClick={() => reorderPoint(index, 1)}><ArrowDown size={14} /></button>
                    <button type="button" aria-label={`移除巡逻点 ${index + 1}`} onClick={() => setWaypoints((values) => values.filter((_, i) => i !== index))}><X size={16} /></button>
                  </div>}
                </li>
              })}
            </ol> : <div className="simulation-queue-empty"><MapPin size={22} /><p>在地图上选择巡逻点，或载入已保存的路线。</p></div>}

            <p className="simulation-selection-message" aria-live="polite">{!active && startBlock}</p>
            <label className={`simulation-return-home ${issueCurrent && goalIssue?.target === 'return_home' ? 'simulation-return-home-issue' : ''}`}><input type="checkbox" checked={showReturnHome} disabled={!editable} onChange={(event) => setReturnHome(event.target.checked)} /><Home size={16} /><span>巡逻结束后返回本次出发点</span>{issueCurrent && goalIssue?.target === 'return_home' && <small>返航起点被拒绝</small>}</label>
            {showReturnHome && <div className="simulation-home-details">
              <strong>{active ? '本次出发点／返航点' : '本次出发点（按当前定位）'}</strong>
              <span>{state?.home ? `(${state.home.x.toFixed(2)}, ${state.home.y.toFixed(2)}) 米` : '等待定位'}</span>
              <p>开始巡逻时记录当前定位，任务中保持不变。这里不是最后一个巡逻点。</p>
              <button type="button" className="simulation-button simulation-quiet" disabled={!map || !state?.home} onClick={locateReturnHome}><MapPin size={15} />定位本次出发点</button>
            </div>}
            <div className="simulation-mission-actions">
              <button type="button" className="simulation-button simulation-primary" disabled={!ready || !editable || waypoints.length === 0 || !!startBlock}
                onClick={startMission}><Play size={17} />{pending === 'mission' ? '正在派发…' : '开始巡逻'}</button>
              <button type="button" className="simulation-button simulation-cancel" disabled={!active || !!pending || (mission?.status === 'canceling' && !canRetryCancel)} onClick={() => void act('cancel')}><Square size={15} />{unknownAcceptance ? '取消无法确认' : canRetryCancel ? '重试取消' : mission?.status === 'canceling' ? '正在取消…' : '取消任务'}</button>
            </div>
            <button type="button" className="simulation-clear-queue" disabled={!editable || waypoints.length === 0} onClick={() => { setWaypoints([]); setSelectionMessage('待派发巡逻点已清空。') }}><Trash2 size={14} />清空待派发点</button>
          </section>

          <section className="simulation-task" aria-labelledby="simulation-routes-title">
            <div className="simulation-task-heading"><h2 id="simulation-routes-title">路线模板</h2><span>{routes.length} 条</span></div>
            <p className="simulation-panel-note">保存与载入只改变草稿；点击“开始巡逻”才执行。</p>
            {routesError && <p className="simulation-inline-error" role="alert">{routesError}</p>}
            <label className="simulation-route-name">路线名称<input type="text" value={routeName} maxLength={64} placeholder="例如：窄口巡查" disabled={!editable || routeWrite === 'unknown'} onChange={(event) => setRouteName(event.target.value)} /></label>
            <button type="button" className="simulation-button simulation-quiet simulation-save-route" disabled={!editable || !rulesReady || !!routesError || !waypoints.length || !routeName.trim() || routeWrite === 'unknown'}
              onClick={() => void saveRoute(routeName, waypoints, returnHome)}><Save size={14} />{routeWrite === 'saving' ? '正在保存…' : '保存当前路线'}</button>
            {routeMessage && <p className="simulation-panel-note" role="status">{routeMessage}</p>}
            {routes.length > 0 && <ul className="simulation-template-list">{routes.map((route) => <li key={route.id}><div><strong>{route.name}</strong><span>{route.waypoints.length} 点{route.return_home ? ' · 返航' : ''}</span></div>
              <button type="button" className="simulation-button simulation-quiet" disabled={!editable || routeWrite === 'unknown'} onClick={() => loadRoute(route)}>载入草稿</button></li>)}</ul>}
          </section>
          <details className="simulation-task simulation-runs"><summary>任务记录 <span>{runs.length} 条</span></summary>
            {runsError && <p className="simulation-inline-error" role="alert">{runsError}</p>}
            {!runsError && runs.length === 0 && <p className="simulation-panel-note">尚无任务记录。</p>}
            <ol>{runs.map((run) => <li key={run.id}><strong>{run.status === 'unknown' ? '终态未知' : missionLabel(run.status as NonNullable<typeof mission>['status'], run.dispatch_state)}</strong>
              <span>地图 {run.map_id ? run.map_id.slice(0, 12) : '未知'} · 规则 {run.rules_revision ?? '未知'}</span>
              <p>{run.stop_reason || run.message || '等待记录更新'}</p>
              <small>{run.id}</small></li>)}</ol>
          </details>
          <section className="simulation-collision-report" aria-labelledby="simulation-collision-title">
            <h2 id="simulation-collision-title">最近 CM 报告</h2>
            <strong aria-live="polite">{connected ? collisionMonitorText(collisionMonitor) : '连接中断，当前报告未知。'}</strong>
            <p>{collisionMonitor?.available && collisionMonitor.observation_age_s != null
              ? `最近变化在 ${collisionMonitor.observation_age_s.toFixed(1)} 秒前；持续状态不定时重发。`
              : '等待状态来源与监测节点就绪。'}</p>
            <small>该报告说明监测层最近的决定；零速本身不能确定停因。</small>
          </section>

          <section className="simulation-obstacle" aria-labelledby="simulation-obstacle-title">
            <div><Box size={19} /><h2 id="simulation-obstacle-title">试试突然挡路</h2></div>
            <p>巡逻途中，让箱子驶入小车前方，观察减速与避障；箱子随后自动退回。</p>
            <strong aria-live="polite">{obstacleLabel}</strong>
            <div className="simulation-obstacle-actions">
              <button type="button" className="simulation-button simulation-quiet" disabled={!ready || mission?.status !== 'running' || awaitingAcceptance || !!pending || state?.obstacle.state !== 'parked'} onClick={() => void act('obstacle', { action: 'block' })}>移入障碍</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!connected || !!pending || !state?.obstacle || state.obstacle.state === 'parked' || state.obstacle.state === 'returning'} onClick={() => void act('obstacle', { action: 'clear' })}>移走障碍</button>
            </div>
          </section>
          <p className="simulation-boundary">当前操作只作用于 MuJoCo 仿真。</p>
        </aside>
      </main>
    </div>
  )
}
