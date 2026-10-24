import { lazy, Suspense, startTransition, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Bot, ChevronRight, House, LayoutDashboard, Radar, FileCheck2, GitCompare, Workflow } from 'lucide-react'

import { LeasedMotionPanel, ManualStopButton } from '@/components/control/leased-motion-panel'
import { useManualOwner } from '@/hooks/use-manual-owner'
import type { ManualController } from '@/lib/manual-control'
import { HeaderStatusBar } from '@/components/layout/header-status-bar'
import { DiagnosticsPanel } from '@/components/logs/diagnostics-panel'
import { MapNavShell } from '@/components/navigation/map-nav-shell'
const RadarWorkbenchPage = lazy(() => import('@/components/radar/radar-workbench-page').then((module) => ({ default: module.RadarWorkbenchPage })))
const SimulationPage = lazy(() => import('@/components/simulation/simulation-page').then((module) => ({ default: module.SimulationPage })))
const CooperationPage = lazy(() => import('@/components/cooperation/cooperation-page').then((module) => ({ default: module.CooperationPage })))
import { ExpansionPanel } from '@/components/roadmap/expansion-panel'
const WorkbenchPage = lazy(() => import('@/components/workbench/workbench-page').then((module) => ({ default: module.WorkbenchPage })))
const RegressionPage = lazy(() => import('@/components/workbench/regression-page').then((module) => ({ default: module.RegressionPage })))
import { ConnectionStatusPanel } from '@/components/status/connection-status-panel'
import { RobotStatePanel } from '@/components/status/robot-state-panel'
import { RuntimeModePanel } from '@/components/status/runtime-mode-panel'
import { useStationBootstrap } from '@/hooks/use-station-bootstrap'
import { RuntimeContextStatus } from '@/components/layout/runtime-context-status'
import { VoiceController } from '@/lib/voice'
import { runtimeRegistry } from '@/lib/runtime-context'
import { resolveAppRoute, type AppRoute } from '@/lib/app-route'

function App() {
  const [route, setRoute] = useState<AppRoute>(() => resolveAppRoute(window.location.pathname))

  const [voiceController] = useState(() => new VoiceController())
  const manual = useManualOwner()
  const [visited, setVisited] = useState<AppRoute[]>([route])
  const navigationActive = route === 'workbench' || route === 'simulation'
  const navigationVisited = navigationActive || visited.includes('workbench') || visited.includes('simulation')
  const radarVisited = route === 'radar' || visited.includes('radar')
  const cooperationVisited = route === 'cooperation' || visited.includes('cooperation')
  const stationVisited = radarVisited || route === 'dashboard' || visited.includes('dashboard')
  useEffect(() => { setVisited((current) => current.includes(route) ? current : [...current, route]) }, [route])
  useEffect(() => runtimeRegistry.start(), [])

  useEffect(() => {
    function handlePopState() {
      setRoute(resolveAppRoute(window.location.pathname))
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  function navigate(next: AppRoute) {
    const pathname = next === 'workbench' ? '/workbench' : next === 'results' ? '/results' : next === 'regression' ? '/regression' : next === 'cooperation' ? '/cooperation' : next === 'simulation' ? '/simulation' : next === 'radar' ? '/radar' : '/'
    if (window.location.pathname === pathname) {
      return
    }

    window.history.pushState({}, '', pathname)
    startTransition(() => {
      setRoute(next)
    })
    window.scrollTo(0, 0)
  }

  return (
    <StationFrame route={route} navigate={navigate} manualEnabled={manual.enabled}
      stop={['dashboard', 'workbench', 'simulation'].includes(route) ? <ManualStopButton {...manual} /> : null}>
      {stationVisited && <StationTelemetrySession />}
      {navigationVisited && <Suspense fallback={navigationActive ? <div className="workspace-loading">正在打开地图工作面…</div> : null}>
        <SimulationPage active={navigationActive} onBack={() => navigate('dashboard')} onCooperation={() => navigate('cooperation')} />
      </Suspense>}
      {cooperationVisited && <Suspense fallback={route === 'cooperation' ? <div className="workspace-loading">正在打开协同工作面…</div> : null}>
        <CooperationPage active={route === 'cooperation'} onBack={() => navigate('dashboard')} />
      </Suspense>}
      {radarVisited && <Suspense fallback={route === 'radar' ? <div className="workspace-loading">正在打开雷达工作面…</div> : null}>
        <RadarWorkbenchPage active={route === 'radar'} onBack={() => navigate('dashboard')} onPatrol={() => navigate('workbench')} />
      </Suspense>}
      {route === 'results' && <Suspense fallback={<div className="workspace-loading">正在读取成果与验收…</div>}><WorkbenchPage onNavigate={navigate} voiceController={voiceController} /></Suspense>}
      {route === 'regression' && <Suspense fallback={<div className="workspace-loading">正在打开配送对照…</div>}><RegressionPage /></Suspense>}
      {route === 'dashboard' && <StationSurface navigate={navigate} manual={manual} />}
    </StationFrame>
  )
}

const workspaces = [
  { route: 'workbench', label: '地图巡逻', icon: House },
  { route: 'dashboard', label: '控制总览', icon: LayoutDashboard },
  { route: 'radar', label: '雷达与地图', icon: Radar },
  { route: 'cooperation', label: '车臂协同', icon: Workflow },
  { route: 'results', label: '成果验收', icon: FileCheck2 },
  { route: 'regression', label: '配送回归', icon: GitCompare },
] as const

function StationFrame({ route, navigate, children, stop, manualEnabled }: {
  route: AppRoute
  navigate: (route: AppRoute) => void
  children: ReactNode
  stop: ReactNode
  manualEnabled: boolean
}) {
  return (
    <div className="station-app">
      <aside className="station-sidebar">
        <button type="button" className="station-brand" onClick={() => navigate('workbench')} aria-label="打开工作台"><span><Bot size={22} /></span><div>FishBot<small>机器人工作台</small></div></button>
        <nav aria-label="工作区" className="station-navigation">
          {workspaces.map((workspace) => (
            <button key={workspace.route} type="button" onClick={() => navigate(workspace.route)}
              aria-current={(route === workspace.route || route === 'simulation' && workspace.route === 'workbench') ? 'page' : undefined} title={workspace.label} aria-label={workspace.label}>
              <workspace.icon size={19} /><span>{workspace.label}</span>
              <ChevronRight size={14} className="station-nav-arrow" />
            </button>
          ))}
        </nav>
        <div className="station-sidebar-note"><span>FishBot + SO101</span><small>控制 · 感知 · 协作</small></div>
      </aside>
      <div className="station-workspace">
        <div className="station-topbar"><span>FishBot <ChevronRight size={14} /> <strong>{workspaces.find((item) => item.route === (route === 'simulation' ? 'workbench' : route))?.label}</strong></span>{stop}<RuntimeContextStatus route={route === 'regression' ? 'results' : route === 'dashboard' && manualEnabled ? 'workbench' : route} /></div>
        {children}
      </div>
    </div>
  )
}

function StationTelemetrySession() { useStationBootstrap(); return null }

function StationSurface({ navigate, manual }: { navigate: (route: AppRoute) => void; manual: { controller: ManualController; enabled: boolean } }) {
  return (
    <main className="station-dashboard">
      <header className="station-page-heading"><div><h1>控制总览</h1><p>手动控制、实时观测与地图诊断</p></div><span className="station-page-tag"><Bot size={15} /> FishBot</span></header>
      {!manual.enabled && <HeaderStatusBar />}
      <div className={manual.enabled ? 'station-manual-surface' : 'station-overview-grid'}><LeasedMotionPanel {...manual} />{!manual.enabled && <RobotStatePanel />}</div>
      {manual.enabled ? <>
        <section className="station-section"><h2>当前导航环境</h2><p>人工控制与地图巡逻共用本页顶部标明的执行器。前往地图查看实时位置、路线和原任务。</p><button className="simulation-button" onClick={() => navigate('workbench')}>打开当前地图</button></section>
        <details className="station-details station-advanced"><summary>兼容控制站观测<span>独立数据来源，不用于确认当前人工动作</span></summary><div className="station-advanced-content"><HeaderStatusBar /><RobotStatePanel /><MapNavShell onOpen={() => navigate('radar')} /><DiagnosticsPanel /></div></details>
      </> : <><MapNavShell onOpen={() => navigate('radar')} /><DiagnosticsPanel /></>}
      <details className="station-details station-advanced"><summary>连接与运行详情<span>数据来源、连接端点与导航队列</span></summary><div className="station-advanced-content"><ConnectionStatusPanel /><RuntimeModePanel /><ExpansionPanel /></div></details>
    </main>
  )
}

export default App
