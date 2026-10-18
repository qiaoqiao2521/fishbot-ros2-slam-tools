import { useState } from 'react'
import { goalIssueMatchesWaypoint, mapRuleErrorMessage } from '@/lib/simulation-errors'
import type { Pose, SimulationGoalIssue, SimulationMap } from '@/lib/simulation'
import { mapZonePose, parseObjectPoseFields, type MapZone, type SavedRoute } from '@/lib/simulation-workspace'

export type SimulationObjectSelection = { kind: 'scene' } | { kind: 'zone'; id: string }
  | { kind: 'waypoint'; index: number; draftIdentity: string } | { kind: 'route'; id: string }
export type SimulationObjectPoseEdit = ({ kind: 'zone'; id: string; source: MapZone }
  | { kind: 'waypoint'; index: number; draftIdentity: string; source: Pose }) & { scope: string; pose: Pose }

/** Only the page commits a draft transaction; inspection never sends a robot operation. */
export function SimulationProperties({ selection, map, zones, points, routes, pointIdentity, revision, goalIssue, issueCurrent,
  editable = false, editScope = '', onApply, onLocate }: {
  selection: SimulationObjectSelection
  map: SimulationMap | null
  zones: MapZone[]
  points: Pose[]
  routes: SavedRoute[]
  pointIdentity: string
  revision: number | null
  goalIssue: SimulationGoalIssue | null
  issueCurrent: boolean
  editable?: boolean
  editScope?: string
  onApply?: (edit: SimulationObjectPoseEdit) => string | null
  onLocate?: () => void
}) {
  const zone = selection.kind === 'zone' ? zones.find((item) => item.id === selection.id) : undefined
  const point = selection.kind === 'waypoint' && selection.draftIdentity === pointIdentity ? points[selection.index] : undefined
  const route = selection.kind === 'route' ? routes.find((item) => item.id === selection.id) : undefined
  const currentIssue = goalIssue && map?.map_id && goalIssue.map_id === map.map_id ? goalIssue : null
  const relatedIssue = currentIssue && (zone ? currentIssue.rule_id === zone.id
    : point && selection.kind === 'waypoint' ? goalIssueMatchesWaypoint(currentIssue, selection.index, point) : false)
  const title = zone ? `${zone.kind === 'wall' ? '虚拟墙' : '禁区'}属性` : point && selection.kind === 'waypoint'
    ? `巡逻点 ${selection.index + 1}` : route ? route.name : '场景属性'
  const missing = selection.kind !== 'scene' && !zone && !point && !route
  let editPose: Pose | null = point ?? null, editError = ''
  try { if (zone) editPose = mapZonePose(zone) }
  catch (error) { editError = error instanceof Error ? error.message : '规则几何无效，请重新读取。' }
  return <section className="simulation-properties" aria-label="所选对象属性">
    <div className="simulation-task-heading"><h2>{title}</h2><span>{editable && onApply && (zone || point) ? '本地草稿' : '只读'}</span></div>
    {missing && <p className="simulation-panel-note" role="status">选中对象已随草稿或地图变化，请重新选择。</p>}
    <dl className="simulation-properties-list">
      <div><dt>地图</dt><dd>{map?.map_id || '等待地图身份'}</dd></div>
      <div><dt>规则基线版本</dt><dd>{revision ?? '待核对'}</dd></div>
      {zone && <><div><dt>规则编号</dt><dd>{zone.id}</dd></div>
        <div><dt>类型</dt><dd>{zone.kind === 'wall' ? '软件虚拟墙' : '矩形禁区'}</dd></div>
        {zone.kind === 'wall' && <div><dt>线宽</dt><dd>{(zone.width ?? .02).toFixed(3)} 米</dd></div>}</>}
      {point && <><div><dt>X</dt><dd>{point.x.toFixed(3)} 米</dd></div><div><dt>Y</dt><dd>{point.y.toFixed(3)} 米</dd></div>
        <div><dt>朝向</dt><dd>{(point.yaw * 180 / Math.PI).toFixed(1)}°</dd></div></>}
      {route && <><div><dt>路线编号</dt><dd>{route.id}</dd></div><div><dt>航点</dt><dd>{route.waypoints.length} 个</dd></div>
        <div><dt>返航</dt><dd>{route.return_home ? '返回本次出发点' : '不返航'}</dd></div></>}
      {!zone && !point && !route && map && <><div><dt>地图范围</dt><dd>{(map.width * map.resolution).toFixed(2)} × {(map.height * map.resolution).toFixed(2)} 米</dd></div>
        <div><dt>分辨率</dt><dd>{map.resolution.toFixed(3)} 米／格</dd></div>
        <div><dt>地图原点</dt><dd>{map.origin[0].toFixed(2)}, {map.origin[1].toFixed(2)} 米</dd></div>
        <div><dt>原点朝向</dt><dd>{(map.origin[2] * 180 / Math.PI).toFixed(1)}°</dd></div></>}
    </dl>
    {zone && <div className="simulation-property-vertices"><h3>世界坐标</h3><ol>{zone.points.map((vertex, index) => <li key={index}>
      <span>{index + 1}</span><span>{vertex.x.toFixed(3)}, {vertex.y.toFixed(3)} 米</span>
    </li>)}</ol></div>}
    {onApply && editError && <p className="simulation-object-edit-error" role="alert">无法编辑此对象：{editError}</p>}
    {onApply && editPose && ((zone && selection.kind === 'zone') || (point && selection.kind === 'waypoint')) && <ObjectPoseForm
      key={JSON.stringify({ selection, zone, point, editScope })} selection={selection} zone={zone} point={point}
      initial={editPose} editable={editable} editScope={editScope} onApply={onApply} onLocate={onLocate} />}
    {relatedIssue && <div className="simulation-property-rejection" role="status">
      <strong>{issueCurrent ? '本次拒绝详情' : '上次拒绝记录'}</strong>
      <p>{mapRuleErrorMessage('rejected', zones, currentIssue)}</p>
      {!issueCurrent && <small>此记录来自上一版路线或规则，不代表当前对象仍被拒绝。</small>}
    </div>}
    <p className="simulation-panel-note">在对象栏选择规则、航点或路线查看详情。属性查看不会发送运动命令。</p>
  </section>
}

function ObjectPoseForm({ selection, zone, point, initial, editable, editScope, onApply, onLocate }: {
  selection: SimulationObjectSelection; zone?: MapZone; point?: Pose; editable: boolean; editScope: string
  initial: Pose
  onApply: (edit: SimulationObjectPoseEdit) => string | null; onLocate?: () => void
}) {
  const [x, setX] = useState(String(initial.x)), [y, setY] = useState(String(initial.y))
  const [yaw, setYaw] = useState(String(initial.yaw * 180 / Math.PI))
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  const translateOnly = zone?.kind === 'no_go'
  function apply() {
    if (!editable) return
    try {
      const pose = parseObjectPoseFields({ x, y, yaw }, translateOnly)
      const edit = zone && selection.kind === 'zone' ? { kind: 'zone' as const, id: selection.id, source: structuredClone(zone), scope: editScope, pose }
        : point && selection.kind === 'waypoint' ? { ...selection, source: { ...point }, scope: editScope, pose } : null
      if (!edit) throw new Error('选中对象已变化，请重新选择。')
      const error = onApply(edit)
      setFailed(!!error)
      setMessage(error || '已应用到本地草稿；尚未保存规则或派发任务。')
    } catch (error) {
      setFailed(true); setMessage(error instanceof Error ? error.message : '参数无效，草稿未修改。')
    }
  }
  return <form className="simulation-object-form" aria-label="编辑所选对象草稿" onSubmit={(event) => { event.preventDefault(); apply() }}>
    <div className="simulation-object-edit-fields">
      <label>{zone ? '中心 X（米）' : 'X（米）'}<input aria-label={zone ? '中心 X（米）' : 'X（米）'} type="number" step="any" required value={x} disabled={!editable} onChange={(event) => { setX(event.target.value); setMessage('') }} /></label>
      <label>{zone ? '中心 Y（米）' : 'Y（米）'}<input aria-label={zone ? '中心 Y（米）' : 'Y（米）'} type="number" step="any" required value={y} disabled={!editable} onChange={(event) => { setY(event.target.value); setMessage('') }} /></label>
      {!translateOnly && <label>朝向（度）<input aria-label="朝向（度）" type="number" step="any" required value={yaw} disabled={!editable} onChange={(event) => { setYaw(event.target.value); setMessage('') }} /></label>}
    </div>
    {translateOnly && <p className="simulation-panel-note">禁区保持世界轴对齐，只修改中心位置；当前导航合同不支持禁区旋转。</p>}
    {!editable && <p className="simulation-panel-note">当前任务、保存或连接状态不允许修改；原草稿仍保留。</p>}
    <div className="simulation-object-edit-actions"><button className="simulation-button simulation-primary" type="submit" disabled={!editable}>应用到草稿</button>
      {onLocate && <button className="simulation-button simulation-quiet" type="button" onClick={onLocate}>在地图查看</button>}</div>
    {message && <p className={failed ? 'simulation-object-edit-error' : 'simulation-panel-note'} role={failed ? 'alert' : 'status'}>{message}</p>}
  </form>
}
