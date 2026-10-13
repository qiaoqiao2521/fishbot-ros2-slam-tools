import type { MapZone } from '@/lib/simulation-workspace'

/** Keep the server's rejection authoritative; translate its rule ID for display. */
export function mapRuleErrorMessage(message: string | null, zones: MapZone[]): string | null {
  if (!message) return message
  const match = /^Waypoint footprint intersects map rule (\S+)$/.exec(message)
  if (!match) return message
  const index = zones.findIndex((zone) => zone.id === match[1])
  const rule = index < 0 ? '地图中的虚拟墙或禁区' : `${zones[index].kind === 'wall' ? '虚拟墙' : '禁区'} ${index + 1}`
  return `某个巡逻点或返航起点的车体范围与${rule}重叠。请将点位移远，或调整该规则；若是返航起点冲突，可取消“巡逻结束后返回起点”。`
}
