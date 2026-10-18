import { useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { DockviewReact, themeLight, type DockviewApi, type DockviewReadyEvent, type IDockviewPanelProps } from 'dockview-react'
import 'dockview-react/dist/styles/dockview.css'
import { WorkspaceSlotsContext, workspaceLabels, workspaceSlots, type WorkspaceSlot } from './workspace-slots'
import { decodeWorkspaceLayout, encodeWorkspaceLayout, workspaceLayoutKey } from './workspace-layout'
import { WorkspaceViewBoundary } from './workspace-view-boundary'
import { WorkspaceVisibilityContext } from './workspace-visibility'

function SlotPanel({ api }: IDockviewPanelProps) {
  const { slots, active } = useContext(WorkspaceSlotsContext)
  const subscribe = useCallback((notify: () => void) => {
    const subscription = api.onDidVisibilityChange(notify)
    return () => subscription.dispose()
  }, [api])
  const visible = useSyncExternalStore(subscribe, () => api.isVisible, () => true)
  const id = api.id as WorkspaceSlot
  return <WorkspaceVisibilityContext.Provider value={active && visible}>
    <div className={`workspace-panel-content workspace-slot-${id}`} data-workspace-slot={id}>{active && visible ? <WorkspaceViewBoundary>{slots[id]}</WorkspaceViewBoundary> : null}</div>
  </WorkspaceVisibilityContext.Provider>
}
const components = { slot: SlotPanel }

export default function DesktopWorkspace({ id }: { id: string }) {
  const api = useRef<DockviewApi | null>(null)
  const [revision, update] = useState(0)
  const [layoutMessage, setLayoutMessage] = useState('')
  const [instance, setInstance] = useState<DockviewApi | null>(null)
  const { active } = useContext(WorkspaceSlotsContext)
  function add(slot: WorkspaceSlot) {
    const current = api.current
    if (!current) return
    const existing = current.getPanel(slot)
    if (existing) { existing.api.setActive(); return }
    const canvas = current.getPanel('canvas')
    current.addPanel({ id: slot, component: 'slot', title: workspaceLabels[slot],
      minimumWidth: slot === 'canvas' ? 260 : 180, minimumHeight: slot === 'task' ? 90 : 120,
      initialWidth: slot === 'objects' ? 260 : slot === 'properties' ? 240 : undefined,
      initialHeight: slot === 'task' ? 115 : undefined,
      position: canvas && slot !== 'canvas' ? { referencePanel: canvas, direction: slot === 'objects' ? 'left' : slot === 'properties' ? 'right' : 'below' } : undefined,
    })
  }
  function reset() { api.current?.clear(); for (const slot of workspaceSlots) add(slot); api.current?.getPanel('canvas')?.api.setActive() }
  function ready({ api: instance }: DockviewReadyEvent) {
    api.current = instance
    try {
      const saved = window.localStorage.getItem(workspaceLayoutKey(id))
      if (saved) instance.fromJSON(decodeWorkspaceLayout(saved)); else reset()
    } catch (error) {
      reset(); setLayoutMessage(error instanceof Error ? error.message : '布局未能恢复，已显示默认工作面。')
    }
    setInstance(instance)
  }
  useEffect(() => {
    if (!instance) return
    let timer: ReturnType<typeof setTimeout> | undefined
    const save = () => {
      if (instance.width < 1 || instance.height < 1) return
      try { window.localStorage.setItem(workspaceLayoutKey(id), encodeWorkspaceLayout(instance.toJSON())) }
      catch { setLayoutMessage('布局未能保存在浏览器；当前布局和任务仍保留。') }
    }
    const change = instance.onDidLayoutChange(() => {
      update((value) => value + 1); clearTimeout(timer); timer = setTimeout(save, 180)
    })
    return () => { clearTimeout(timer); change.dispose() }
  }, [instance, id])
  useEffect(() => {
    const focus = (event: Event) => { if ((event as CustomEvent).detail === id) add('canvas') }
    window.addEventListener('fishbot:focus-canvas', focus)
    return () => window.removeEventListener('fishbot:focus-canvas', focus)
    // add reads the stable API ref; no command or session state is captured.
  }, [id])
  return <div className="workspace-desktop" data-layout-revision={revision} data-active={active}>
    <nav className="workspace-layout-tools" aria-label="显示面板">{workspaceSlots.map((slot) => <button type="button" key={slot} onClick={() => add(slot)} aria-pressed={!!api.current?.getPanel(slot)}>{workspaceLabels[slot]}</button>)}<button type="button" onClick={reset}>恢复布局</button></nav>
    <div className="workspace-layout-message" role="status">{layoutMessage}</div>
    <div className="workspace-dock"><DockviewReact components={components} onReady={ready} theme={themeLight} disableFloatingGroups /></div>
  </div>
}
