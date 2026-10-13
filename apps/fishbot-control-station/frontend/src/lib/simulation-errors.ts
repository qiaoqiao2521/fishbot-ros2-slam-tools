import type { MapZone } from '@/lib/simulation-workspace'
import type { Pose, SimulationGoalIssue } from '@/lib/simulation'

export function goalIssueTarget(issue: SimulationGoalIssue): string {
  return issue.target === 'return_home' ? '返航起点' : `巡逻点 ${issue.waypoint_index}`
}

function coordinates(point: { x: number; y: number }): string {
  return `（${point.x.toFixed(2)}, ${point.y.toFixed(2)}）米`
}

/** Round available space down and required space up; rounded numbers never imply extra clearance. */
function centimeters(value: number, direction: 'down' | 'up'): string {
  const tenths = value * 1000
  return ((direction === 'down' ? Math.floor(tenths + 1e-9) : Math.ceil(tenths - 1e-9)) / 10).toFixed(1)
}

function clearanceText(issue: SimulationGoalIssue): string {
  const values: string[] = []
  if (issue.clearance_m !== undefined) values.push(`${issue.kind === 'map_rule' && issue.rule_kind === 'wall' ? '距墙边净距' : '距阻挡边缘净距'} ${centimeters(issue.clearance_m, 'down')} 厘米`)
  if (issue.required_clearance_m !== undefined) values.push(`车体检查至少需要 ${centimeters(issue.required_clearance_m, 'up')} 厘米`)
  if (issue.shortfall_m !== undefined) values.push(issue.shortfall_m === 0
    ? '车体与边缘相接，需留出额外净距' : `净距不足约 ${centimeters(issue.shortfall_m, 'up')} 厘米`)
  return values.length ? `${values.join('，')}。` : ''
}

/** Identity only: collision geometry remains exclusively a backend decision. */
export function goalDraftIdentity(points: Pose[], returnHome: boolean): string {
  return JSON.stringify({ points, returnHome })
}

export function goalIssueMatchesWaypoint(issue: SimulationGoalIssue, index: number, point: Pose): boolean {
  return issue.target === 'waypoint' && issue.waypoint_index === index + 1
    && point.x === issue.point.x && point.y === issue.point.y && point.yaw === issue.point.yaw
}

/** Keep the server's rejection authoritative; translate its rule ID for display. */
export function mapRuleErrorMessage(message: string | null, zones: MapZone[], issue?: SimulationGoalIssue | null): string | null {
  if (issue) {
    const target = `${goalIssueTarget(issue)}${coordinates(issue.point)}`
    let reason: string
    if (issue.kind === 'map_rule') {
      const rule = issue.rule_kind === 'wall' ? '虚拟墙' : issue.rule_kind === 'no_go' ? '禁区' : '地图规则'
      reason = `${target}的车体范围与${rule}${issue.rule_index ? ` ${issue.rule_index}` : ''}冲突。`
    } else if (issue.kind === 'map_boundary') {
      reason = `${target}的车体范围越过地图边缘。`
    } else {
      const blocker = issue.blocking_point ? coordinates(issue.blocking_point) : ''
      reason = `${target}的车体范围碰到${issue.kind === 'unknown_cell' ? '地图未知格' : '地图占用格'}${blocker}。`
    }
    const action = issue.target === 'return_home'
      ? '请检查返航起点附近的规则或障碍，或取消“巡逻结束后返回起点”。'
      : '请将该点移离标出的规则或障碍，再重新派发。'
    return `${reason}${clearanceText(issue)}${action}`
  }
  if (!message) return message
  const match = /^Waypoint footprint intersects map rule (\S+)$/.exec(message)
  if (!match) return message
  const index = zones.findIndex((zone) => zone.id === match[1])
  const rule = index < 0 ? '地图中的虚拟墙或禁区' : `${zones[index].kind === 'wall' ? '虚拟墙' : '禁区'} ${index + 1}`
  return `某个巡逻点或返航起点的车体范围与${rule}重叠。请将点位移远，或调整该规则；若是返航起点冲突，可取消“巡逻结束后返回起点”。`
}
