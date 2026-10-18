import { createContext, useContext } from 'react'

/** Visibility controls rendering only. Never use it to cancel or recreate a task owner. */
export const WorkspaceVisibilityContext = createContext(true)
export const useWorkspaceVisible = () => useContext(WorkspaceVisibilityContext)

export function focusWorkspaceCanvas(id: string) {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('fishbot:focus-canvas', { detail: id }))
}
