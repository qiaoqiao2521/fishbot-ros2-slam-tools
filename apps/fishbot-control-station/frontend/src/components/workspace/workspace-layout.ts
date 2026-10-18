import type { SerializedDockview } from 'dockview-react'
import { workspaceLabels, workspaceSlots, type WorkspaceSlot } from './workspace-slots'

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const dimension = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 16000
const slotId = (value: unknown): value is WorkspaceSlot => typeof value === 'string' && (workspaceSlots as readonly string[]).includes(value)
const groupId = (value: unknown): value is string => typeof value === 'string' && /^[\w-]{1,100}$/.test(value)
export const WORKSPACE_LAYOUT_VERSION = 1
export const workspaceLayoutKey = (workspace: string) => `fishbot.workspace-layout.v1.${workspace}`

/** Accept only display geometry and the four fixed slots, never params, tasks or popout URLs. */
export function sanitizeWorkspaceLayout(value: unknown): SerializedDockview {
  const fail = () => { throw new Error('布局缓存无效，已恢复默认工作面；任务与草稿保持。') }
  if (!record(value) || !record(value.grid) || !record(value.panels)) return fail()
  const grid = value.grid
  if (!dimension(grid.width) || !dimension(grid.height) || !['HORIZONTAL', 'VERTICAL'].includes(String(grid.orientation))) return fail()
  if (Object.keys(value.panels).length > 4 || (Array.isArray(value.floatingGroups) && value.floatingGroups.length)
    || (Array.isArray(value.popoutGroups) && value.popoutGroups.length) || value.edgeGroups != null) return fail()
  const panels: Record<string, unknown> = {}
  for (const [id, panel] of Object.entries(value.panels)) {
    if (!slotId(id) || !record(panel) || panel.id !== id || panel.contentComponent !== 'slot') return fail()
    panels[id] = { id, contentComponent: 'slot', title: workspaceLabels[id] }
  }
  const groups = new Set<string>(), used = new Set<string>()
  let count = 0
  function node(input: unknown, depth: number): unknown {
    if (!record(input) || ++count > 12 || depth > 8 || (input.size !== undefined && !dimension(input.size))) return fail()
    const base = { ...(input.size === undefined ? {} : { size: input.size }), ...(typeof input.visible === 'boolean' ? { visible: input.visible } : {}) }
    if (input.type === 'branch') {
      if (!Array.isArray(input.data) || input.data.length > 4) return fail()
      return { ...base, type: 'branch', data: input.data.map((child) => node(child, depth + 1)) }
    }
    if (input.type !== 'leaf' || !record(input.data)) return fail()
    const data = input.data
    if (!groupId(data.id) || groups.has(data.id) || !Array.isArray(data.views) || data.views.length < 1 || data.views.length > 4) return fail()
    groups.add(data.id)
    for (const slot of data.views) {
      if (!slotId(slot) || !Object.hasOwn(panels, slot) || used.has(slot)) return fail()
      used.add(slot)
    }
    if (data.activeView !== undefined && !data.views.includes(data.activeView)) return fail()
    return { ...base, type: 'leaf', data: { id: data.id, views: [...data.views], activeView: data.activeView ?? data.views[0] } }
  }
  const root = node(grid.root, 0)
  if (used.size !== Object.keys(panels).length || (value.activeGroup !== undefined && !groups.has(String(value.activeGroup)))) return fail()
  return { grid: { root, width: grid.width, height: grid.height, orientation: grid.orientation }, panels,
    ...(value.activeGroup === undefined ? {} : { activeGroup: value.activeGroup }) } as SerializedDockview
}
export function encodeWorkspaceLayout(layout: unknown): string {
  return JSON.stringify({ version: WORKSPACE_LAYOUT_VERSION, layout: sanitizeWorkspaceLayout(layout) })
}
export function decodeWorkspaceLayout(text: string): SerializedDockview {
  if (text.length > 32768) throw new Error('布局缓存过大，已恢复默认工作面；任务与草稿保持。')
  let value: unknown
  try { value = JSON.parse(text) } catch { throw new Error('布局缓存损坏，已恢复默认工作面；任务与草稿保持。') }
  if (!record(value) || value.version !== WORKSPACE_LAYOUT_VERSION) throw new Error('布局版本已变化，已恢复默认工作面；任务与草稿保持。')
  return sanitizeWorkspaceLayout(value.layout)
}
