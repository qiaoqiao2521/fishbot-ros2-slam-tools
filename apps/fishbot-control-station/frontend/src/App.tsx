import { startTransition, useEffect, useState } from 'react'
import { LayoutDashboard, Radar, Route } from 'lucide-react'

import { MotionControlPanel } from '@/components/control/motion-control-panel'
import { HeaderStatusBar } from '@/components/layout/header-status-bar'
import { DiagnosticsPanel } from '@/components/logs/diagnostics-panel'
import { MapNavShell } from '@/components/navigation/map-nav-shell'
import { RadarWorkbenchPage } from '@/components/radar/radar-workbench-page'
import { SimulationPage } from '@/components/simulation/simulation-page'
import { ExpansionPanel } from '@/components/roadmap/expansion-panel'
import { ConnectionStatusPanel } from '@/components/status/connection-status-panel'
import { RobotStatePanel } from '@/components/status/robot-state-panel'
import { RuntimeModePanel } from '@/components/status/runtime-mode-panel'
import { Button } from '@/components/ui/button'
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
    const pathname = next === 'simulation' ? '/simulation' : next === 'radar' ? '/radar' : '/'
    if (window.location.pathname === pathname) {
      return
    }

    window.history.pushState({}, '', pathname)
    startTransition(() => {
      setRoute(next)
    })
  }

  if (route === 'simulation') {
    return <SimulationPage onBack={() => navigate('dashboard')} />
  }

  return <StationSurface route={route} navigate={navigate} />
}

function StationSurface({ route, navigate }: { route: 'dashboard' | 'radar'; navigate: (route: AppRoute) => void }) {
  useStationBootstrap()
  if (route === 'radar') {
    return <RadarWorkbenchPage onBack={() => navigate('dashboard')} />
  }

  return (
    <div className="relative min-h-screen overflow-hidden text-foreground">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-48 bg-[linear-gradient(180deg,rgba(94,70,38,0.16),transparent)]" />
      <div className="pointer-events-none absolute left-[6%] top-16 h-32 w-32 rounded-full bg-[rgba(199,147,56,0.18)] blur-3xl" />
      <div className="pointer-events-none absolute bottom-10 right-[10%] h-40 w-40 rounded-full bg-[rgba(124,91,39,0.14)] blur-3xl" />

      <div className="mx-auto flex min-h-screen max-w-[1620px] flex-col gap-6 px-4 py-5 md:px-6 lg:px-8">
        <HeaderStatusBar />

        <div className="flex items-center justify-end gap-3">
          <Button variant="outline" onClick={() => navigate('dashboard')}>
            <LayoutDashboard className="mr-2 h-4 w-4" />
            Console
          </Button>
          <Button variant="default" onClick={() => navigate('radar')}>
            <Radar className="mr-2 h-4 w-4" />
            Radar Workbench
          </Button>
          <Button variant="outline" onClick={() => navigate('simulation')}>
            <Route className="mr-2 h-4 w-4" />
            仿真巡逻
          </Button>
        </div>

        <main className="grid flex-1 gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
          <section className="grid gap-6">
            <MotionControlPanel />
            <MapNavShell />
            <DiagnosticsPanel />
          </section>

          <section className="grid gap-6">
            <ConnectionStatusPanel />
            <RuntimeModePanel />
            <RobotStatePanel />
            <ExpansionPanel />
          </section>
        </main>
      </div>
    </div>
  )
}

export default App
