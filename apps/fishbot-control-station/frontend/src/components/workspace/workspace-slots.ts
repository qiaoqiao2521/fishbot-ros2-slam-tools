import { createContext, type ReactNode } from 'react'
export const workspaceSlots = ['canvas', 'objects', 'properties', 'task'] as const
export type WorkspaceSlot = typeof workspaceSlots[number]
export const workspaceLabels: Record<WorkspaceSlot, string> = { canvas: '场景', objects: '对象', properties: '属性', task: '任务与反馈' }
export const WorkspaceSlotsContext = createContext<{ slots: Record<WorkspaceSlot, ReactNode>; active: boolean }>({
  slots: { canvas: null, objects: null, properties: null, task: null }, active: true,
})
