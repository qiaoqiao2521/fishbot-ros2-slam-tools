import { startTransition, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Bot, ChevronRight, LayoutDashboard, Radar, Route, Workflow } from 'lucide-react'

import { MotionControlPanel } from '@/components/control/motion-control-panel'
import { HeaderStatusBar } from '@/components/layout/header-status-bar'
import { DiagnosticsPanel } from '@/components/logs/diagnostics-panel'
import { MapNavShell } from '@/components/navigation/map-nav-shell'
import { RadarWorkbenchPage } from '@/components/radar/radar-workbench-page'
import { SimulationPage } from '@/components/simulation/simulation-page'
import { CooperationPage } from '@/components/cooperation/cooperation-page'
import { ExpansionPanel } from '@/components/roadmap/expansion-panel'
import { ConnectionStatusPanel } from '@/components/status/connection-status-panel'
import { RobotStatePanel } from '@/components/status/robot-state-panel'
import { RuntimeModePanel } from '@/components/status/runtime-mode-panel'
import { useStationBootstrap } from '@/hooks/use-station-bootstrap'
import { resolveAppRoute, type AppRoute } from '@/lib/app-route'

function App() {
  const [route, setRoute] = useState<AppRoute>(() => resolveAppRoute(window.location.pathname))

  useEffect(() => {
    function handlePopState() {
      setRoute(resolveAppRoute(window.location.pathname))
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  function navigate(next: AppRoute) {
    const pathname = next === 'cooperation' ? '/cooperation' : next === 'simulation' ? '/simulation' : next === 'radar' ? '/radar' : '/'
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
    <StationFrame route={route} navigate={navigate}>
      {route === 'simulation' ? (
        <SimulationPage onBack={() => navigate('dashboard')} onCooperation={() => navigate('cooperation')} />
      ) : route === 'cooperation' ? (
        <CooperationPage onBack={() => navigate('dashboard')} />
      ) : <StationSurface route={route} navigate={navigate} />}
    </StationFrame>
  )
}

const workspaces = [
  { route: 'dashboard', label: '控制总览', icon: LayoutDashboard },
  { route: 'radar', label: '雷达与地图', icon: Radar },
  { route: 'simulation', label: '仿真巡逻', icon: Route },
  { route: 'cooperation', label: '车臂协同', icon: Workflow },
] as const

function StationFrame({ route, navigate, children }: {
  route: AppRoute
  navigate: (route: AppRoute) => void
  children: ReactNode
}) {
  return (
    <div className="station-app">
      <aside className="station-sidebar">
        <div className="station-brand"><span><Bot size={22} /></span><div>FishBot<small>机器人工作台</small></div></div>
        <nav aria-label="工作区" className="station-navigation">
          {workspaces.map((workspace) => (
            <button key={workspace.route} type="button" onClick={() => navigate(workspace.route)}
              aria-current={route === workspace.route ? 'page' : undefined} title={workspace.label}>
              <workspace.icon size={19} /><span>{workspace.label}</span>
              <ChevronRight size={14} className="station-nav-arrow" />
            </button>
          ))}
        </nav>
        <div className="station-sidebar-note"><span>FishBot + SO101</span><small>控制 · 感知 · 协作</small></div>
      </aside>
      <div className="station-workspace">
        <div className="station-topbar"><span>工作台 <ChevronRight size={14} /> <strong>{workspaces.find((item) => item.route === route)?.label}</strong></span><span className="station-topbar-mark">FishBot 控制站</span></div>
        {children}
      </div>
    </div>
  )
}

function StationSurface({ route, navigate }: { route: 'dashboard' | 'radar'; navigate: (route: AppRoute) => void }) {
  useStationBootstrap()
  if (route === 'radar') {
    return <RadarWorkbenchPage onBack={() => navigate('dashboard')} onPatrol={() => navigate('simulation')} />
  }

  return (
    <main className="station-dashboard">
      <header className="station-page-heading"><div><h1>控制总览</h1><p>手动控制、实时观测与地图诊断</p></div><span className="station-page-tag"><Bot size={15} /> FishBot</span></header>
      <HeaderStatusBar />
      <div className="station-overview-grid"><MotionControlPanel /><RobotStatePanel /></div>
      <MapNavShell onOpen={() => navigate('radar')} />
      <DiagnosticsPanel />
      <details className="station-details station-advanced"><summary>连接与运行详情<span>数据来源、连接端点与导航队列</span></summary><div className="station-advanced-content"><ConnectionStatusPanel /><RuntimeModePanel /><ExpansionPanel /></div></details>
    </main>
  )
}

export default App
