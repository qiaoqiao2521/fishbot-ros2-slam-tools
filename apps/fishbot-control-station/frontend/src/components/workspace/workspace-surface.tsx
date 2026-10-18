import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { Layers, SlidersHorizontal, ListChecks } from 'lucide-react'
import { WorkspaceSlotsContext, workspaceLabels, type WorkspaceSlot } from './workspace-slots'
import { WorkspaceViewBoundary } from './workspace-view-boundary'
import { WorkspaceVisibilityContext } from './workspace-visibility'
import './workspace.css'

const DesktopWorkspace = lazy(() => import('./workspace-desktop'))

/** Business hooks belong to the parent session; these slots have no command lifecycle. */
export function WorkspaceSurface({ id, title, subtitle, active = true, toolbar, notice, canvas, objects, properties, task }: {
  id: string; title: string; subtitle?: string; active?: boolean
  toolbar: ReactNode; notice?: ReactNode; canvas: ReactNode; objects: ReactNode; properties: ReactNode; task: ReactNode
}) {
  const [desktop, setDesktop] = useState(() => typeof window !== 'undefined' && window.innerWidth >= 1050)
  const [documentVisible, setDocumentVisible] = useState(() => typeof document === 'undefined' || !document.hidden)
  const [tab, setTab] = useState<Exclude<WorkspaceSlot, 'canvas'>>('objects')
  useEffect(() => {
    const query = window.matchMedia('(min-width: 1050px)')
    const resize = () => setDesktop(query.matches)
    const visibility = () => setDocumentVisible(!document.hidden)
    query.addEventListener('change', resize); document.addEventListener('visibilitychange', visibility)
    return () => { query.removeEventListener('change', resize); document.removeEventListener('visibilitychange', visibility) }
  }, [])
  const slots = { canvas, objects, properties, task }
  const visible = active && documentVisible
  return <WorkspaceSlotsContext.Provider value={{ slots, active: visible }}>
    <main className="workspace-surface" data-workspace={id} hidden={!active}>
      <header className="workspace-heading"><div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
        <div className="workspace-primary-actions">{toolbar}</div>
      </header>
      {notice && <div className="workspace-notice">{notice}</div>}
      {desktop ? <Suspense fallback={<div className="workspace-loading" role="status">正在载入工作面…</div>}><DesktopWorkspace id={id} /></Suspense>
        : <div className="workspace-mobile">
          <WorkspaceVisibilityContext.Provider value={visible}><section className="workspace-mobile-canvas" aria-label="场景画布">{visible && <WorkspaceViewBoundary>{canvas}</WorkspaceViewBoundary>}</section></WorkspaceVisibilityContext.Provider>
          <div className="workspace-mobile-sheet">
            <nav role="tablist" aria-label="工作面板">{(['objects', 'properties', 'task'] as const).map((slot) => {
              const Icon = { objects: Layers, properties: SlidersHorizontal, task: ListChecks }[slot]
              return <button key={slot} role="tab" id={`${id}-tab-${slot}`} aria-controls={`${id}-panel-${slot}`} aria-selected={tab === slot} onClick={() => setTab(slot)}><Icon size={15} />{workspaceLabels[slot]}</button>
            })}</nav>
            {(['objects', 'properties', 'task'] as const).map((slot) => <section key={slot} role="tabpanel" id={`${id}-panel-${slot}`} aria-labelledby={`${id}-tab-${slot}`} hidden={tab !== slot} className="workspace-panel-content">
              <WorkspaceVisibilityContext.Provider value={visible && tab === slot}><WorkspaceViewBoundary>{slots[slot]}</WorkspaceViewBoundary></WorkspaceVisibilityContext.Provider>
            </section>)}
          </div>
        </div>}
    </main>
  </WorkspaceSlotsContext.Provider>
}
