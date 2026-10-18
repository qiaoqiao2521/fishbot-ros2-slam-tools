import { projectMissionEvidence } from '@/lib/command-evidence'
import { CommandEvidencePanel } from '@/components/status/command-evidence-panel'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowUp, Box, Check, Eye, Home, MapPin, Monitor, Play, RefreshCw, Route, Save, ShieldBan, Square, Trash2, Undo2, X } from 'lucide-react'

import { SimulationProperties, type SimulationObjectPoseEdit, type SimulationObjectSelection } from './simulation-properties'
import { WorkspaceSurface } from '@/components/workspace/workspace-surface'
import { focusWorkspaceCanvas } from '@/components/workspace/workspace-visibility'
import { SimulationMapView } from '@/components/simulation/simulation-map'
import { useSimulation } from '@/hooks/use-simulation'
import { useSimulationWorkspace } from '@/hooks/use-simulation-workspace'
import { useRviz } from '@/hooks/use-rviz'
import { usePatrolDraftCache } from '@/hooks/use-patrol-draft-cache'
import type { PatrolDraft } from '@/lib/patrol-draft-cache'
import { evaluateWaypointSelection, segmentConflicts, type SegmentConflict, type WaypointSelection } from '@/lib/route-safety'
import { calculatePolylineDistance, PatrolMissionTracker } from '@/lib/patrol-mission'
import { MapZonesManager } from '@/lib/map-zones'
import { goalDraftIdentity, goalIssueMatchesWaypoint, mapRuleErrorMessage } from '@/lib/simulation-errors'
import { editWaypointPose, MAX_MAP_ZONES, mapGeneration, missionElapsedSeconds, routeDraft, rulesDirty, ruleStartBlock, transformMapZone, zoneFromSelection, zonesEqual, type MapEditMode, type SavedRoute } from '@/lib/simulation-workspace'
import {
  MAX_WAYPOINTS, SIMULATION_DOMAIN, collisionMonitorText, isFreeWaypoint, missionCanRetryCancel,
  missionIsActive, missionLabel, missionProgressText,
  type Point, type Pose,
} from '@/lib/simulation'
import './simulation.css'

export function SimulationPage({ onBack, onCooperation, active: workspaceActive = true }: { onBack: () => void; onCooperation?: () => void; active?: boolean }) {
  const { state, map, connectionError, mapError, actionError, goalIssue, pending, missionRequestUnknown, recoveryMessage, act } = useSimulation()
  const rviz = useRviz()
  const mapStage = useRef<HTMLDivElement>(null)
  const [homeEmphasized, setHomeEmphasized] = useState(false)
  const [attemptedDraft, setAttemptedDraft] = useState<string | null>(null)
  const [selectionMessage, setSelectionMessage] = useState('')
  const [editMode, setEditMode] = useState<MapEditMode>('waypoint')
  const [draftHistory, setDraftHistory] = useState<PatrolDraft[]>([])
  const [draftFuture, setDraftFuture] = useState<PatrolDraft[]>([])
  const [selectionPreview, setSelectionPreview] = useState<{ start: Point; selection: WaypointSelection } | null>(null)
  const [selectedObject, setSelectedObject] = useState<SimulationObjectSelection>({ kind: 'scene' })
  const generation = mapGeneration(map)
  const active = missionIsActive(state)
  const connected = state !== null && !connectionError
  const ready = connected && state.ready && !!map && !mapError
  const blocked = active || !!pending || missionRequestUnknown || !connected
  const workspace = useSimulationWorkspace(map, blocked)
  const { editor, dispatch, rulesError, ruleDraftMessage, routes, routesError, runs, runsError, routeWrite, routeMessage, refreshing, refresh, saveRules, saveRoute, exporting, exportMessage, exportRules } = workspace
  const writing = editor.writeState === 'saving' || routeWrite === 'saving'
  const editable = !blocked && !writing && editor.writeState !== 'unknown'
  const rulesReady = !!map && editor.mapId === map.map_id && !rulesError
  const startBlock = ruleStartBlock(editor, rulesReady)
  const dirty = rulesDirty(editor)
  const draftCache = usePatrolDraftCache({ domain: SIMULATION_DOMAIN, mapId: map?.map_id ?? null,
    connected, ready: rulesReady && !!editor.saved, rulesRevision: editor.saved?.revision ?? null })
  const { waypoints, returnHome, routeName } = draftCache.draft
  const draftEditable = !active && !pending && !missionRequestUnknown && !writing && editor.writeState !== 'unknown'
    && draftCache.loaded && !draftCache.loading

  useEffect(() => {
    setEditMode('waypoint')
    setSelectedObject({ kind: 'scene' })
    setDraftHistory([])
    setDraftFuture([])
    setSelectionPreview(null)
    setAttemptedDraft(null)
    setHomeEmphasized(false)
    setSelectionMessage('按当前地图恢复独立草稿；不会恢复或重发运动任务。')
  }, [generation])
  useEffect(() => { setSelectionPreview(null) }, [editor.zones, editor.baseRevision])
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
  let draftConflicts: SegmentConflict[] = []
  try {
    const points = active ? state!.path : [...(state?.pose ? [state.pose] : []), ...waypoints]
    draftConflicts = segmentConflicts(points, editor.zones)
    const hit = draftConflicts[0]
    if (hit) geometryMessage = `${active ? '收到的导航路径' : '点间直线预览'}与${hit.collisionType === 'wall' ? '虚拟墙' : '禁区'}接触（${hit.entityId}）。实际绕行与放行以 Nav2 为准。`
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
  const pointIdentity = goalDraftIdentity(displayedPoints, showReturnHome)
  const objectEditScope = JSON.stringify({ generation, revision: editor.baseRevision })
  const objectEditable = selectedObject.kind === 'zone' ? editable && rulesReady
    : selectedObject.kind === 'waypoint' ? draftEditable && !active : false
  const selectedMapObject = selectedObject.kind === 'zone' ? selectedObject
    : selectedObject.kind === 'waypoint' && selectedObject.draftIdentity === pointIdentity && displayedPoints[selectedObject.index]
      ? { kind: 'waypoint' as const, index: selectedObject.index, point: displayedPoints[selectedObject.index] } : null

  function changeDraft(next: PatrolDraft) {
    if (!draftEditable) return
    setDraftHistory((values) => [...values.slice(-29), structuredClone(draftCache.draft)])
    setDraftFuture([])
    draftCache.setDraft(next)
    setSelectionPreview(null)
  }

  function setWaypoints(next: Pose[] | ((points: Pose[]) => Pose[])) {
    changeDraft({ ...draftCache.draft, waypoints: typeof next === 'function' ? next(waypoints) : next })
  }

  function undoDraft(redo = false) {
    const stack = redo ? draftFuture : draftHistory
    const next = stack.at(-1)
    if (!draftEditable || !next) return
    if (redo) {
      setDraftHistory((values) => [...values, structuredClone(draftCache.draft)])
      setDraftFuture((values) => values.slice(0, -1))
    } else {
      setDraftFuture((values) => [...values, structuredClone(draftCache.draft)])
      setDraftHistory((values) => values.slice(0, -1))
    }
    draftCache.setDraft({ ...next, routeName: draftCache.draft.routeName })
    setSelectionPreview(null)
    setSelectionMessage(`${redo ? '已重做' : '已撤销'}航点草稿修改；未发送运动命令。`)
  }

  function validateDraft() {
    if (!map || !rulesReady || !editor.saved || !connected || draftCache.conflict) return false
    try {
      const manager = MapZonesManager.fromMapRulesZones(editor.zones)
      const invalid = waypoints.findIndex((point) => !isFreeWaypoint(point, map, .13) || manager.checkPathCollision([point], .13).hasCollision)
      if (invalid >= 0) {
        setSelectionMessage(`第 ${invalid + 1} 个航点的车体范围不安全，请移除或重新选择。`)
        return false
      }
      const accepted = draftCache.confirmValidated(draftCache.validationToken)
      setSelectionMessage(accepted ? `草稿已按当前地图与规则版本 ${editor.saved.revision} 复核；尚未派发。` : '版本核对尚未结束，请稍后复核；草稿仍保留。')
      return accepted
    } catch (error) {
      setSelectionMessage(error instanceof Error ? error.message : '草稿复核暂不可用；未派发任务。')
      return false
    }
  }

  function selectPoint(point: Point) {
    if (!map || editMode === 'observe' || !(editMode === 'waypoint' ? draftEditable : editable)) return
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
    const start = waypoints.at(-1) ?? state?.pose
    if (!start) {
      setSelectionMessage('尚无定位起点，暂不能校验选点；已有草稿仍保留。')
      return
    }
    const selection = evaluateWaypointSelection(start, point, map, editor.zones)
    if (selection.point && selection.kind !== 'rejected') setWaypoints((current) => [...current, { ...selection.point!, yaw: 0 }])
    setSelectionPreview({ start, selection })
    setSelectionMessage(selection.kind === 'snapped'
      ? `第 ${waypoints.length + 1} 点已从 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) 吸附到 (${selection.point!.x.toFixed(3)}, ${selection.point!.y.toFixed(3)}) 米。${selection.reason}`
      : selection.kind === 'accepted' ? `已添加第 ${waypoints.length + 1} 个点。${selection.reason}` : selection.reason)
  }

  function changeMode(mode: MapEditMode) {
    if (!(mode === 'waypoint' || mode === 'observe' ? draftEditable : editable)) return
    dispatch({ type: 'anchor', point: null })
    setEditMode(mode)
    setSelectionMessage({ waypoint: '点击空旷位置添加巡逻点。', wall: '选择两个点定义虚拟墙；只保存软件规则。',
      no_go: '选择两个对角定义矩形禁区。', observe: '观察模式不创建草稿，也不发送命令。' }[mode])
  }

  function loadRoute(route: SavedRoute) {
    if (!draftEditable || !editor.mapId || !map) return
    try {
      const draft = routeDraft(route, editor.mapId)
      if (!draft.waypoints.every((point) => isFreeWaypoint(point, map, .13))) throw new Error('路线包含当前地图不可达点，请重新安排。')
      changeDraft({ waypoints: draft.waypoints, returnHome: draft.returnHome, routeName: route.name })
      dispatch({ type: 'anchor', point: null })
      setEditMode('waypoint')
      setSelectionMessage(`“${route.name}”已载入草稿；尚未派发任务。`)
    } catch (error) { setSelectionMessage(error instanceof Error ? error.message : '路线无法载入。') }
  }

  function reorderPoint(index: number, delta: number) {
    if (!draftEditable) return
    setWaypoints((current) => {
      const next = [...current], other = index + delta
      if (other < 0 || other >= next.length) return current
      ;[next[index], next[other]] = [next[other], next[index]]
      return next
    })
  }

  function focusMapStage() {
    focusWorkspaceCanvas('simulation')
    const focus = () => {
      mapStage.current?.scrollIntoView({ block: 'center' })
      mapStage.current?.focus({ preventScroll: true })
    }
    if (typeof window !== 'undefined' && window.requestAnimationFrame) window.requestAnimationFrame(focus)
    else focus()
  }

  function applyObjectPose(edit: SimulationObjectPoseEdit): string | null {
    if (!map || edit.scope !== objectEditScope) return '地图或规则版本已变化，请重新选择对象。'
    try {
      if (edit.kind === 'zone') {
        if (!editable || !rulesReady) return '当前任务、保存或连接状态不允许修改规则。'
        if (selectedObject.kind !== 'zone' || selectedObject.id !== edit.id) return '选中规则已变化，请重新选择。'
        const current = editor.zones.find((zone) => zone.id === edit.id)
        if (!current || !zonesEqual([current], [edit.source])) return '规则内容已变化，请重新选择后修改。'
        const zone = transformMapZone(current, edit.pose, map)
        dispatch({ type: 'replace', id: edit.id, expected: current, zone })
        setSelectionMessage('规则位置已更新为本地草稿；保存后等待导航应用。')
      } else {
        if (!draftEditable || active) return '当前任务或保存状态不允许修改航点。'
        if (selectedObject.kind !== 'waypoint' || selectedObject.index !== edit.index
          || selectedObject.draftIdentity !== edit.draftIdentity || edit.draftIdentity !== pointIdentity) return '选中航点或路线已变化，请重新选择。'
        const next = editWaypointPose(waypoints, edit.index, edit.source, edit.pose, map, editor.zones)
        setWaypoints(next)
        setSelectedObject({ kind: 'waypoint', index: edit.index, draftIdentity: goalDraftIdentity(next, returnHome) })
        setSelectionMessage(`巡逻点 ${edit.index + 1} 已更新为本地草稿；尚未派发。`)
      }
      return null
    } catch (error) { return error instanceof Error ? error.message : '对象修改无效，草稿未更新。' }
  }

  function locateProblem() {
    if (!issueSameMap) return
    focusMapStage()
  }

  function locateReturnHome() {
    setHomeEmphasized(true)
    focusMapStage()
  }

  function startMission() {
    if (!ready || !editable || !draftEditable || !editor.mapId || !editor.saved || startBlock || draftCache.conflict || draftCache.validation === 'stale' || !validateDraft()) return
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

  return <div className="simulation-page simulation-workspace">
    <WorkspaceSurface id="simulation" title="小鱼巡逻" subtitle="编辑通行规则、保存路线，开始后由原生导航执行。" active={workspaceActive}
      toolbar={<div className="simulation-workspace-toolbar">
            <div className="simulation-mission-actions">
              <button type="button" className="simulation-button simulation-primary" disabled={!ready || !editable || !draftEditable || draftCache.conflict || draftCache.validation === 'stale' || waypoints.length === 0 || !!startBlock}
                onClick={startMission}><Play size={17} />{pending === 'mission' ? '正在派发…' : '开始巡逻'}</button>
              <button type="button" className="simulation-button simulation-cancel" disabled={!active || !!pending || (mission?.status === 'canceling' && !canRetryCancel)} onClick={() => void act('cancel')}><Square size={15} />{unknownAcceptance ? '取消无法确认' : canRetryCancel ? '重试取消' : mission?.status === 'canceling' ? '正在取消…' : '取消任务'}</button>
            </div>
    <div className="simulation-toolbar-context">
      <button type="button" className="simulation-button simulation-quiet" disabled={rviz.pending || rviz.status?.available === false}
        onClick={() => void rviz.open()}><Monitor size={16} />{rviz.pending ? '正在连接 RViz…' : rviz.unknown ? '确认 RViz 状态' : '打开 RViz'}</button>
      {onCooperation && <button type="button" className="simulation-button simulation-quiet" onClick={onCooperation}>车臂协同</button>}
      <button type="button" className="simulation-button simulation-quiet" onClick={onBack}><ArrowLeft size={16} />控制总览</button>
    </div></div>}
      notice={<div className="simulation-workspace-notices">
      {missionRequestUnknown && <p className="simulation-compact-error" role="status">派发回执未知，正在读取原任务状态；暂不能重复派发或编辑。</p>}
      {error && <details className="simulation-error" role="alert"><summary>{error}</summary>
        {goalIssue && !issueCurrent && <p className="simulation-issue-stale">此提示来自上一版路线或规则，重新派发前请检查。{!issueSameMap ? '地图已不同，不在当前地图标记。' : '地图中的琥珀色标记仅表示上次拒绝的坐标。'}</p>}
        {issueSameMap && <button type="button" className="simulation-button simulation-locate-issue" onClick={locateProblem}><MapPin size={16} />{issueCurrent ? '在地图上定位问题' : '定位上次问题'}</button>}
      </details>}
      <div className={`simulation-readiness ${ready ? 'simulation-ready' : 'simulation-waiting'}`} role="status">
        <span className="simulation-status-dot" aria-hidden="true" /><strong>{statusText}</strong>
        <span>MuJoCo 仿真域 {SIMULATION_DOMAIN} · {connectionError ? '请检查仿真启动窗口。' : state?.reason || '等待地图、定位与导航服务。'}</span>
      </div>
    </div>}
      canvas={<section className="simulation-scene" aria-labelledby="simulation-map-title">
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
                disabled={!map || ((mode === 'wall' || mode === 'no_go') ? !editable || !rulesReady : !draftEditable)} aria-pressed={editMode === mode} onClick={() => changeMode(mode)}><Icon size={15} />{label}</button>)}
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
            {map ? <SimulationMapView map={map} state={state} points={displayedPoints} editable={(editMode === 'waypoint' ? draftEditable : editable) && editMode !== 'observe'} onSelect={selectPoint} mode={editMode}
              selectedObject={selectedMapObject}
              draftConflicts={draftConflicts} selectionPreview={active ? null : selectionPreview}
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
              <span><i className="simulation-legend-conflict" />红线：草稿直线冲突</span>
            </div>
            {map && <span>{(map.width * map.resolution).toFixed(1)} × {(map.height * map.resolution).toFixed(1)} 米</span>}
          </div>
          <div className="simulation-position">
            <span>{connected ? '实际位置' : '上次位置'} {physical ? `(${physical.x.toFixed(2)}, ${physical.y.toFixed(2)}) 米` : '等待数据'}</span>
            <span>速度 {physical ? `${Math.abs(physical.linear_speed).toFixed(2)} 米/秒` : '—'}</span>
            <span>车头 {physical ? `${(physical.yaw * 180 / Math.PI).toFixed(0)}°` : '—'}</span>
          </div>
          <p className="simulation-keyboard-note">键盘选点：聚焦地图后，用方向键移动十字，回车选点，Esc取消当前选择。</p>
        </section>}
      objects={<div className="simulation-object-sections">
          <section className="simulation-task simulation-rules" aria-labelledby="simulation-rules-title">
            <div className="simulation-task-heading"><h2 id="simulation-rules-title">地图规则</h2><span>{editor.zones.length} 项</span></div>
            <p className="simulation-panel-note">软件规则限制导航通行，不改变实体墙，也不会生成雷达回波。</p>
            {ruleDraftMessage && <p className="simulation-panel-note" role="status">{ruleDraftMessage}</p>}
            {(rulesError || editor.error) && <p className="simulation-inline-error" role="alert">{editor.error || rulesError}</p>}
            {editor.saved?.message && <p className="simulation-panel-note">{editor.saved.message}</p>}
            {editor.saved && editor.baseRevision !== editor.saved.revision && <p className="simulation-inline-error" role="alert">规则版本已更新。请恢复最新规则，再重新编辑。</p>}
            {editor.zones.length > 0 && <ul className="simulation-rule-list">{editor.zones.map((zone, index) => <li key={zone.id} className={issueCurrent && goalIssue?.rule_id === zone.id ? 'simulation-rule-issue' : ''}>
              <button type="button" className="simulation-object-select" aria-label={`查看${zone.kind === 'wall' ? '虚拟墙' : '禁区'} ${index + 1} 属性`}
                aria-pressed={selectedObject.kind === 'zone' && selectedObject.id === zone.id} onClick={() => setSelectedObject({ kind: 'zone', id: zone.id })}>
                <span>{zone.kind === 'wall' ? '虚拟墙' : '禁区'} {index + 1}</span></button>
              <button type="button" aria-label={`移除${zone.kind === 'wall' ? '虚拟墙' : '禁区'} ${index + 1}`} disabled={!editable}
                onClick={() => dispatch({ type: 'remove', id: zone.id })}><X size={16} /></button>
            </li>)}</ul>}
            <div className="simulation-resource-actions">
              <button type="button" className="simulation-button simulation-quiet" disabled={!editable || !editor.saved || (!dirty && editor.baseRevision === editor.saved.revision)} onClick={() => dispatch({ type: 'restore' })}>恢复已保存</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!map || refreshing || writing} onClick={() => void refresh()}><RefreshCw size={14} />{refreshing ? '正在读取…' : '读取规则与路线'}</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!editor.saved || dirty || editor.saved.apply_state !== 'applied' || exporting} onClick={() => void exportRules()}>{exporting ? '正在导出…' : '导出 Nav2 规则'}</button>
            </div>
            {exportMessage && <p className="simulation-panel-note" role="status">{exportMessage}</p>}
          </section>
          <section className="simulation-task simulation-points">
            <div className="simulation-task-heading"><h2>巡逻点</h2><span>{displayedPoints.length} 个</span></div>
            {displayedPoints.length ? <ol className="simulation-waypoints">
              {displayedPoints.map((point, index) => {
                const current = mission?.status === 'running' && !awaitingAcceptance && index === mission.current_index
                const done = active && index < (mission?.current_index ?? 0)
                const isHome = active && mission?.return_home && index === displayedPoints.length - 1
                const rejected = issueCurrent && !!goalIssue && goalIssueMatchesWaypoint(goalIssue, index, point)
                return <li key={`${index}-${point.x}-${point.y}`} className={[current ? 'simulation-waypoint-current' : '', rejected ? 'simulation-waypoint-issue' : ''].filter(Boolean).join(' ')}>
                  <span className="simulation-waypoint-number">{done ? <Check size={14} /> : index + 1}</span>
                  <button type="button" className="simulation-object-select" aria-label={`查看巡逻点 ${index + 1} 属性`}
                    aria-pressed={selectedObject.kind === 'waypoint' && selectedObject.index === index && selectedObject.draftIdentity === pointIdentity}
                    onClick={() => setSelectedObject({ kind: 'waypoint', index, draftIdentity: pointIdentity })}>
                    <strong>{isHome ? '返回本次出发点' : `巡逻点 ${index + 1}`}</strong><span>({point.x.toFixed(2)}, {point.y.toFixed(2)}) 米</span>{rejected && <small className="simulation-rejected-point-label">此点被拒绝</small>}</button>
                  {current ? <span className="simulation-waypoint-tag">前往中</span> : draftEditable && <div className="simulation-waypoint-edit">
                    <button type="button" aria-label={`上移巡逻点 ${index + 1}`} disabled={index === 0} onClick={() => reorderPoint(index, -1)}><ArrowUp size={14} /></button>
                    <button type="button" aria-label={`下移巡逻点 ${index + 1}`} disabled={index === displayedPoints.length - 1} onClick={() => reorderPoint(index, 1)}><ArrowDown size={14} /></button>
                    <button type="button" aria-label={`移除巡逻点 ${index + 1}`} onClick={() => setWaypoints((values) => values.filter((_, i) => i !== index))}><X size={16} /></button>
                  </div>}
                </li>
              })}
            </ol> : <div className="simulation-queue-empty"><MapPin size={22} /><p>在地图上选择巡逻点，或载入已保存的路线。</p></div>}

            <div className="simulation-draft-history">
              <button type="button" className="simulation-button simulation-quiet" disabled={!draftEditable || !draftHistory.length} onClick={() => undoDraft()}><Undo2 size={14} />撤销航点</button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!draftEditable || !draftFuture.length} onClick={() => undoDraft(true)}>重做航点</button>
            </div>
            <button type="button" className="simulation-clear-queue" disabled={!draftEditable || waypoints.length === 0} onClick={() => { setWaypoints([]); setSelectionMessage('待派发巡逻点已清空。') }}><Trash2 size={14} />清空待派发点</button>
          </section>
          <section className="simulation-task" aria-labelledby="simulation-routes-title">
            <div className="simulation-task-heading"><h2 id="simulation-routes-title">路线模板</h2><span>{routes.length} 条</span></div>
            <p className="simulation-panel-note">保存与载入只改变草稿；点击“开始巡逻”才执行。</p>
            {routesError && <p className="simulation-inline-error" role="alert">{routesError}</p>}
            <label className="simulation-route-name">路线名称<input type="text" value={routeName} maxLength={64} placeholder="例如：窄口巡查" disabled={!draftEditable || routeWrite === 'unknown'} onChange={(event) => draftCache.setDraft((draft) => ({ ...draft, routeName: event.target.value }))} /></label>
            <button type="button" className="simulation-button simulation-quiet simulation-save-route" disabled={!editable || !rulesReady || !!routesError || !waypoints.length || !routeName.trim() || routeWrite === 'unknown'}
              onClick={() => void saveRoute(routeName, waypoints, returnHome)}><Save size={14} />{routeWrite === 'saving' ? '正在保存…' : '保存当前路线'}</button>
            {routeMessage && <p className="simulation-panel-note" role="status">{routeMessage}</p>}
            {routes.length > 0 && <ul className="simulation-template-list">{routes.map((route) => <li key={route.id}><button type="button" className="simulation-object-select" aria-label={`查看路线 ${route.name} 属性`}
                aria-pressed={selectedObject.kind === 'route' && selectedObject.id === route.id} onClick={() => setSelectedObject({ kind: 'route', id: route.id })}>
                <strong>{route.name}</strong><span>{route.waypoints.length} 点{route.return_home ? ' · 返航' : ''}</span></button>
              <button type="button" className="simulation-button simulation-quiet" disabled={!draftEditable || routeWrite === 'unknown'} onClick={() => loadRoute(route)}>载入草稿</button></li>)}</ul>}
          </section>
        </div>}
      properties={<SimulationProperties selection={selectedObject} map={map} zones={editor.zones} points={displayedPoints}
        routes={routes} pointIdentity={pointIdentity} revision={editor.baseRevision} goalIssue={goalIssue} issueCurrent={issueCurrent}
        editable={objectEditable} editScope={objectEditScope} onApply={applyObjectPose} onLocate={focusMapStage} />}
      task={<div className="simulation-task-sections">
          <section className="simulation-task">
            <div className="simulation-task-heading"><h2>巡逻路线</h2><span>{active ? displayedPoints.length : waypoints.length} 个点</span></div>
            <p className="simulation-panel-note">航点间直线 {routeDistance.toFixed(2)} 米，不含绕障。任务终态以 ROS 回执为准。</p>
            {elapsedSeconds !== null && <p className="simulation-panel-note">任务耗时 {elapsedSeconds.toFixed(1)} 秒</p>}
            {geometryMessage && <p className="simulation-panel-note" role="status">{geometryMessage}</p>}
            <div className={`simulation-mission-state simulation-mission-${mission?.status ?? 'idle'}`} aria-live="polite">
              <strong>{missionLabel(mission?.status, mission?.dispatch_state)}</strong>
              <CommandEvidencePanel evidence={projectMissionEvidence(mission ?? null, { pending: pending === 'mission', receiptUnknown: missionRequestUnknown })} />
              {recoveryMessage && <p role="status">{recoveryMessage}</p>}
              <p>{progressText}</p>
              {mission?.message && mission.status !== 'idle' && <small>{mission.message}</small>}
              {mission?.stop_reason && <small>取消触发原因：{mission.stop_reason}</small>}
            </div>

            <p className="simulation-selection-message" aria-live="polite">{!active && startBlock}</p>
            <label className={`simulation-return-home ${issueCurrent && goalIssue?.target === 'return_home' ? 'simulation-return-home-issue' : ''}`}><input type="checkbox" checked={showReturnHome} disabled={!draftEditable} onChange={(event) => changeDraft({ ...draftCache.draft, returnHome: event.target.checked })} /><Home size={16} /><span>巡逻结束后返回本次出发点</span>{issueCurrent && goalIssue?.target === 'return_home' && <small>返航起点被拒绝</small>}</label>
            {showReturnHome && <div className="simulation-home-details">
              <strong>{active ? '本次出发点／返航点' : '本次出发点（按当前定位）'}</strong>
              <span>{state?.home ? `(${state.home.x.toFixed(2)}, ${state.home.y.toFixed(2)}) 米` : '等待定位'}</span>
              <p>开始巡逻时记录当前定位，任务中保持不变。这里不是最后一个巡逻点。</p>
              <button type="button" className="simulation-button simulation-quiet" disabled={!map || !state?.home} onClick={locateReturnHome}><MapPin size={15} />定位本次出发点</button>
            </div>}
          </section>

      <section className={`simulation-draft-cache ${draftCache.conflict || draftCache.validation === 'stale' ? 'simulation-draft-cache-attention' : ''}`} aria-label="航点草稿保护">
        <div role="status"><strong>{!connected ? '离线草稿保留' : draftCache.conflict ? '草稿版本冲突' : draftCache.saving ? '正在缓存草稿' : draftCache.loaded ? '航点草稿保护' : '正在读取草稿'}</strong>
          <span>{draftCache.message}</span>
          {draftCache.error && <span className="simulation-inline-error">缓存未确认：{draftCache.error}；当前页草稿仍保留。</span>}
          <small>{draftCache.mode === 'memory_only' ? '仅当前页面内存 · 关闭页面不会恢复' : '浏览器本地缓存'} · 规则版本 {editor.saved?.revision ?? '待核对'}{draftCache.revisionId ? ` · 草稿 ${draftCache.revisionId.slice(0, 8)}` : ''} · 不自动补发运动</small>
        </div>
        <div className="simulation-draft-cache-actions">
          {draftCache.conflict || draftCache.error ? <button type="button" className="simulation-button simulation-quiet" disabled={!connected || active || !!pending || draftCache.loading}
            onClick={() => { setDraftHistory([]); setDraftFuture([]); setSelectionPreview(null); void draftCache.reloadCache() }}>用缓存替换本页草稿</button>
            : <button type="button" className="simulation-button simulation-quiet" disabled={!connected || !draftEditable || !rulesReady || !!startBlock}
              onClick={validateDraft}>按当前规则复核</button>}
        </div>
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

        <p className="simulation-rviz-status">{rviz.message} 窗口显示在控制站电脑，手机可发起打开。</p>
      </div>} />
  </div>
}
