import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, MouseEvent, PointerEvent } from 'react'

import {
  mapToWorld, worldToMap,
  type Point, type Pose, type SimulationGoalIssue, type SimulationMap, type SimulationState,
} from '@/lib/simulation'
import { goalIssueTarget } from '@/lib/simulation-errors'
import { mapGeneration, rectanglePoints, zonesEqual, type MapEditMode, type MapZone } from '@/lib/simulation-workspace'
import type { SegmentConflict, WaypointSelection } from '@/lib/route-safety'

export function SimulationMapView({ map, state, points, editable, onSelect, mode = 'waypoint', zones = [], savedZones = [], anchor = null, onCancelSelection, goalIssue = null, issueCurrent = false, homeEmphasized = false, draftConflicts = [], selectionPreview = null }: {
  map: SimulationMap
  state: SimulationState | null
  points: Pose[]
  editable: boolean
  onSelect: (point: Point) => void
  mode?: MapEditMode
  zones?: MapZone[]
  savedZones?: MapZone[]
  anchor?: Point | null
  onCancelSelection?: () => void
  goalIssue?: SimulationGoalIssue | null
  issueCurrent?: boolean
  homeEmphasized?: boolean
  draftConflicts?: SegmentConflict[]
  selectionPreview?: { start: Point; selection: WaypointSelection } | null
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [cursor, setCursor] = useState<Point>({ x: 0, y: 0 })
  const [focused, setFocused] = useState(false)
  const [trace, setTrace] = useState<Point[]>([])
  const robot = state?.truth ?? state?.pose
  const generation = mapGeneration(map)

  useEffect(() => {
    setTrace([])
    setCursor(mapToWorld({ x: map.width / 2, y: map.height / 2 }, map))
    // Map content identity, rather than each polling object, owns the local trace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation])

  useEffect(() => {
    const context = canvas.current?.getContext('2d')
    if (!context) return
    const image = context.createImageData(map.width, map.height)
    for (let y = 0; y < map.height; y += 1) {
      for (let x = 0; x < map.width; x += 1) {
        const value = map.data[y * map.width + x]
        const color = value < 0 ? [201, 201, 194] : value >= 50 ? [69, 72, 69] : [248, 248, 241]
        const offset = ((map.height - 1 - y) * map.width + x) * 4
        image.data.set([...color, 255], offset)
      }
    }
    context.putImageData(image, 0, 0)
  }, [map])

  useEffect(() => {
    if (!state?.truth) return
    const { x, y } = state.truth
    setTrace((current) => {
      const last = current.at(-1)
      if (last && Math.hypot(last.x - x, last.y - y) < 0.025) return current
      return [...current.slice(-1200), { x, y }]
    })
  }, [state?.truth])

  function eventPosition(event: MouseEvent<SVGSVGElement> | PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    return mapToWorld({
      x: (event.clientX - rect.left) / rect.width * map.width,
      y: (event.clientY - rect.top) / rect.height * map.height,
    }, map)
  }

  function select(event: MouseEvent<SVGSVGElement>) {
    if (!editable || mode === 'observe') return
    const position = eventPosition(event)
    setCursor(position)
    onSelect(position)
  }

  function keySelect(event: KeyboardEvent<SVGSVGElement>) {
    if (!editable || mode === 'observe') return
    if (event.key === 'Escape') { event.preventDefault(); onCancelSelection?.(); return }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(cursor)
    } else if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      event.preventDefault()
      const pixel = worldToMap(cursor, map)
      const delta = 0.1 / map.resolution
      const next = {
        x: Math.max(0, Math.min(map.width, pixel.x + (event.key === 'ArrowRight' ? delta : event.key === 'ArrowLeft' ? -delta : 0))),
        y: Math.max(0, Math.min(map.height, pixel.y + (event.key === 'ArrowDown' ? delta : event.key === 'ArrowUp' ? -delta : 0))),
      }
      setCursor(mapToWorld(next, map))
    }
  }

  function polyline(values: Point[]) {
    return values.map((value) => { const p = worldToMap(value, map); return `${p.x},${p.y}` }).join(' ')
  }

  const unit = 1 / map.resolution
  const home = state?.home ? worldToMap(state.home, map) : null
  const homeLabel = state?.mission.return_home && ['running', 'canceling'].includes(state.mission.status) ? '出发点／返航点' : '本次出发点'
  const obstacle = state?.obstacle
  const obstaclePosition = obstacle && typeof obstacle.x === 'number' && Number.isFinite(obstacle.x)
    && typeof obstacle.y === 'number' && Number.isFinite(obstacle.y)
    ? worldToMap({ x: obstacle.x, y: obstacle.y }, map) : null
  const cursorPixel = worldToMap(cursor, map)
  const issue = map.map_id && goalIssue?.map_id === map.map_id ? goalIssue : null
  const issuePixel = issue ? worldToMap(issue.point, map) : null
  const issueColor = issueCurrent ? '#b32d2b' : '#9b7029'
  const issueLabel = issue ? `${issueCurrent ? '拒绝点' : '上次拒绝点'}：${goalIssueTarget(issue)}` : ''

  return (
    <div className="simulation-map-frame" style={{ aspectRatio: `${map.width} / ${map.height}` }}>
      <canvas ref={canvas} width={map.width} height={map.height} aria-hidden="true" />
      <svg
        ref={svg}
        viewBox={`0 0 ${map.width} ${map.height}`}
        aria-label={`巡逻地图，当前${{ waypoint: '巡逻点', wall: '虚拟墙', no_go: '禁区', observe: '观察' }[mode]}模式，方向键移动十字，回车选点，Escape取消选择`}
        role="application"
        tabIndex={editable ? 0 : -1}
        className={editable ? 'simulation-map-editable' : ''}
        onClick={select}
        onPointerMove={(event) => { if (editable && anchor) setCursor(eventPosition(event)) }}
        onKeyDown={keySelect}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      >
        <defs>
          <pattern id="simulation-grid" width={unit} height={unit} patternUnits="userSpaceOnUse">
            <path d={`M ${unit} 0 L 0 0 0 ${unit}`} fill="none" stroke="#b5b9b0" strokeOpacity=".28" strokeWidth=".15" />
          </pattern>
        </defs>
        <rect width={map.width} height={map.height} fill="url(#simulation-grid)" pointerEvents="none" />
        {zones.map((zone) => {
          const persisted = savedZones.some((saved) => zonesEqual([saved], [zone]))
          const blocked = issueCurrent && issue?.kind === 'map_rule' && issue.rule_id === zone.id
          const zonePoints = polyline(zone.points)
          return zone.kind === 'wall' ? <polyline key={zone.id} points={zonePoints} fill="none" stroke={blocked ? '#b32d2b' : '#b26120'}
            data-rule-issue={blocked || undefined} strokeWidth={blocked ? Math.max((zone.width ?? 0.02) * unit, 1.5) : (zone.width ?? 0.02) * unit} strokeLinecap="round" strokeDasharray={persisted ? undefined : '2 1'}>
            <title>{`${persisted ? '已保存虚拟墙' : '虚拟墙草稿'}：${zone.id}`}</title>
          </polyline> : <polygon key={zone.id} points={zonePoints} fill={blocked ? '#b32d2b' : '#b14255'} fillOpacity={blocked ? '.30' : '.20'} stroke={blocked ? '#b32d2b' : '#b14255'}
            data-rule-issue={blocked || undefined} strokeWidth={blocked ? '1.5' : '.8'} strokeDasharray={persisted ? undefined : '2 1'}><title>{`${persisted ? '已保存禁区' : '禁区草稿'}：${zone.id}`}</title></polygon>
        })}
        {anchor && mode === 'wall' && <polyline points={polyline([anchor, cursor])} fill="none" stroke="#b26120" strokeWidth="1" strokeDasharray="2 1" />}
        {anchor && mode === 'no_go' && <polygon points={polyline(rectanglePoints(anchor, cursor))} fill="#b14255" fillOpacity=".12" stroke="#b14255" strokeWidth=".8" strokeDasharray="2 1" />}
        {anchor && <g transform={`translate(${worldToMap(anchor, map).x} ${worldToMap(anchor, map).y})`}><circle r="1.4" fill="#713f9f" /><title>已选第一个点，继续选择第二个点</title></g>}
        {trace.length > 1 && <polyline points={polyline(trace)} fill="none" stroke="#297fb1" strokeOpacity=".42" strokeWidth=".7" strokeDasharray="1.5 1.5" />}
        {state && state.path.length > 1 && <polyline points={polyline(state.path)} fill="none" stroke="#577636" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />}
        {points.length > 1 && <polyline points={polyline(points)} fill="none" stroke="#a77637" strokeOpacity=".6" strokeDasharray="2 2" strokeWidth=".5" />}
        <g className="simulation-draft-conflicts" pointerEvents="none" aria-label="草稿直线冲突">
          {draftConflicts.map((conflict) => <polyline key={`${conflict.index}-${conflict.entityId}`} data-draft-conflict={conflict.entityId}
            points={polyline([conflict.start, conflict.end])} fill="none" stroke="#d42d46" strokeWidth="1.3" strokeDasharray="2 1">
            <title>{`第 ${conflict.index + 1} 段草稿直线接触${conflict.collisionType === 'wall' ? '虚拟墙' : '禁区'} ${conflict.entityId}；实际绕行由 Nav2 规划`}</title>
          </polyline>)}
        </g>
        {selectionPreview && selectionPreview.selection.kind !== 'accepted' && (() => {
          const { start, selection } = selectionPreview
          const requested = worldToMap(selection.requested, map)
          const snapped = selection.point ? worldToMap(selection.point, map) : null
          return <g data-selection-preview={selection.kind} pointerEvents="none">
            <polyline points={polyline([start, selection.requested])} fill="none" stroke="#d42d46" strokeWidth="1.2" strokeDasharray="2 1" />
            <circle cx={requested.x} cy={requested.y} r="3.2" fill="#fff" fillOpacity=".8" stroke="#d42d46" strokeWidth=".8" />
            <path d={`M ${requested.x - 1.5} ${requested.y - 1.5} l 3 3 m -3 0 l 3 -3`} stroke="#d42d46" strokeWidth=".8" />
            <text x={requested.x + 4} y={requested.y - 4} fontSize={Math.max(3.6, map.width / 85)} fill="#b61d36" stroke="white" strokeWidth=".7" paintOrder="stroke">原目标</text>
            {snapped && <>
              <line x1={requested.x} y1={requested.y} x2={snapped.x} y2={snapped.y} stroke="#16867d" strokeWidth=".65" strokeDasharray="1 1" />
              <circle cx={snapped.x} cy={snapped.y} r={.14 * unit} fill="#19aa99" fillOpacity=".12" stroke="#16867d" strokeWidth=".7" />
              <text x={snapped.x + 4} y={snapped.y + 6} fontSize={Math.max(3.6, map.width / 85)} fill="#076a60" stroke="white" strokeWidth=".7" paintOrder="stroke">安全吸附点</text>
            </>}
            <title>{selection.reason}</title>
          </g>
        })()}
        {obstacle && obstaclePosition && <g transform={`translate(${obstaclePosition.x} ${obstaclePosition.y})`}>
          <rect x={-obstacle.size * unit / 2} y={-obstacle.size * unit / 2} width={obstacle.size * unit} height={obstacle.size * unit}
            rx=".5" fill={obstacle.state === 'parked' ? '#a6aaa2' : '#ce731d'} stroke="#794518" strokeWidth=".5" />
          <title>{obstacle.state === 'parked' ? '已退回的障碍箱' : '真实移动障碍箱'}</title>
        </g>}
        {points.map((point, index) => {
          const pixel = worldToMap(point, map)
          const active = state?.mission.status === 'running' && index === state.mission.current_index
          return <g key={`${index}-${point.x}-${point.y}`} transform={`translate(${pixel.x} ${pixel.y})`}>
            <circle r={active ? 3.4 : 2.8} fill={active ? '#986423' : '#fffaf0'} stroke="#95662a" strokeWidth=".7" />
            <text textAnchor="middle" dominantBaseline="central" fontSize="3.5" fontWeight="700" fill={active ? '#ffffff' : '#684e2b'}>{index + 1}</text>
            <title>{`巡逻点 ${index + 1}：${point.x.toFixed(2)}，${point.y.toFixed(2)} 米`}</title>
          </g>
        })}
        {state?.pose && state?.truth && <g transform={poseTransform(state.pose, map)}>
          <circle r={0.16 * unit} fill="none" stroke="#527635" strokeWidth=".4" strokeDasharray="1 1" />
          <title>导航定位</title>
        </g>}
        {robot && <g transform={poseTransform(robot, map)}>
          <circle r={0.13 * unit + 1.2} fill="#ffffff" opacity=".82" />
          <rect x={-0.08 * unit} y={-0.14 * unit} width={0.16 * unit} height={0.28 * unit} rx=".5" fill="#1d5d83" />
          <circle r={0.13 * unit} fill="#2780b2" stroke="#154d70" strokeWidth=".45" />
          <path d={`M${0.20 * unit} 0 L${0.04 * unit} ${-0.065 * unit} L${0.04 * unit} ${0.065 * unit}Z`} fill="#f5fbff" stroke="#154d70" strokeWidth=".25" />
          <title>小鱼位置，尖端为车头方向</title>
        </g>}
        {issue && issuePixel && <g className="simulation-goal-issue-overlay" data-goal-issue-current={issueCurrent} pointerEvents="none">
          {issue.blocking_point && <>
            <line x1={issuePixel.x} y1={issuePixel.y} x2={worldToMap(issue.blocking_point, map).x} y2={worldToMap(issue.blocking_point, map).y}
              stroke={issueColor} strokeWidth=".6" strokeDasharray="1 1" />
            <circle cx={worldToMap(issue.blocking_point, map).x} cy={worldToMap(issue.blocking_point, map).y} r="1.1" fill={issueColor} />
          </>}
          <circle cx={issuePixel.x} cy={issuePixel.y} r={issue.required_clearance_m !== undefined ? issue.required_clearance_m * unit : 1.5}
            fill={issueColor} fillOpacity=".10" stroke={issueColor} strokeWidth=".8" strokeDasharray={issueCurrent ? undefined : '1.5 1'} />
          <path d={`M ${issuePixel.x - 1.2} ${issuePixel.y - 1.2} l 2.4 2.4 m -2.4 0 l 2.4 -2.4`} stroke={issueColor} strokeWidth=".7" />
          <text x={Math.max(1, Math.min(map.width - 1, issuePixel.x))} y={Math.max(3, Math.min(map.height - 2, issuePixel.y - (issue.required_clearance_m ?? 0) * unit - 2))}
            textAnchor={issuePixel.x > map.width / 2 ? 'end' : 'start'} fontSize={Math.max(4, map.width / 70)} fontWeight="700" fill={issueColor} stroke="#fffaf0" strokeWidth=".6" paintOrder="stroke">{issueLabel}</text>
          <title>{`${issueLabel}（${issue.point.x.toFixed(2)}, ${issue.point.y.toFixed(2)}）米；${issue.required_clearance_m !== undefined ? '圈线为服务端检查所需的车体范围' : '标记为被拒绝的坐标'}${issueCurrent ? '' : '，对应上一版路线或规则'}`}</title>
        </g>}
        {focused && editable && <g transform={`translate(${cursorPixel.x} ${cursorPixel.y})`} stroke="#713f9f" strokeWidth=".6">
          <path d="M-4 0H4M0-4V4" />
          <circle r="2.4" fill="none" />
        </g>}
      </svg>
      {home && state?.home && <div className={`simulation-home-marker ${home.y < map.height / 4 || selectionPreview ? 'simulation-home-marker-below' : ''} ${home.x < map.width / 4 ? 'simulation-home-marker-left' : home.x > map.width * 3 / 4 ? 'simulation-home-marker-right' : ''}`}
        style={{ left: `${home.x / map.width * 100}%`, top: `${home.y / map.height * 100}%` }} data-home-emphasized={homeEmphasized}
        aria-label={`${homeLabel}（${state.home.x.toFixed(2)}, ${state.home.y.toFixed(2)}）米`}>
        <i className="simulation-home-anchor" aria-hidden="true" />
        <span className="simulation-home-leader" aria-hidden="true" />
        <span className="simulation-home-callout"><strong>{homeLabel}</strong><span>({state.home.x.toFixed(2)}, {state.home.y.toFixed(2)}) 米</span></span>
      </div>}
    </div>
  )
}

function poseTransform(pose: Pose, map: SimulationMap) {
  const pixel = worldToMap(pose, map)
  return `translate(${pixel.x} ${pixel.y}) rotate(${-(pose.yaw - map.origin[2]) * 180 / Math.PI})`
}
