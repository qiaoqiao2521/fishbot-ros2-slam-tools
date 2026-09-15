import { useEffect, useState } from 'react'
import { ArrowLeft, Box, Map, Radar } from 'lucide-react'

import { RadarQualityPanel } from '@/components/radar/radar-quality-panel'
import { RadarStatusStrip } from '@/components/radar/radar-status-strip'
import { RadarViewport } from '@/components/radar/radar-viewport'
import { RadarWorkbenchControls } from '@/components/radar/radar-workbench-controls'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { createDefaultRadarWorkbenchConfig, type RadarSelectedPoint, type RadarWorkbenchConfig } from '@/lib/radar-workbench'
import { useStationStore } from '@/store/station-store'
import type { LaserScanSnapshot } from '@/types/station'

export function RadarWorkbenchPage({
  onBack,
}: {
  onBack: () => void
}) {
  const { connection, navigation, perception, robotState } = useStationStore()
  const [config, setConfig] = useState<RadarWorkbenchConfig>(createDefaultRadarWorkbenchConfig)
  const [history, setHistory] = useState<LaserScanSnapshot[]>([])
  const [selectedPoint, setSelectedPoint] = useState<RadarSelectedPoint | null>(null)
  const [hz, setHz] = useState(0)
  const [lastUpdate, setLastUpdate] = useState<string | null>(null)

  useEffect(() => {
    if (!perception.scan.ready || config.freeze || perception.scan.lastUpdate === lastUpdate) {
      return
    }

    if (lastUpdate) {
      const deltaMs = new Date(perception.scan.lastUpdate).getTime() - new Date(lastUpdate).getTime()
      if (deltaMs > 0) {
        setHz(1000 / deltaMs)
      }
    }

    setLastUpdate(perception.scan.lastUpdate)
    setHistory((current) => [...current.slice(-5), { ...perception.scan, samplePoints: [...perception.scan.samplePoints] }])
  }, [config.freeze, lastUpdate, perception.scan])

  return (
    <div className="relative min-h-screen overflow-hidden text-foreground">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-52 bg-[linear-gradient(180deg,rgba(78,56,28,0.16),transparent)]" />
      <div className="pointer-events-none absolute left-[8%] top-20 h-40 w-40 rounded-full bg-[rgba(196,132,34,0.16)] blur-3xl" />
      <div className="pointer-events-none absolute bottom-16 right-[9%] h-48 w-48 rounded-full bg-[rgba(58,87,82,0.14)] blur-3xl" />

      <div className="mx-auto flex min-h-screen max-w-[1680px] flex-col gap-5 px-4 py-5 md:px-6 lg:px-8">
        <div className="flex items-center justify-between gap-3">
          <Button variant="outline" onClick={onBack}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Console
          </Button>

          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
            <Radar className="h-4 w-4" />
            /radar
          </div>
        </div>

        <RadarStatusStrip connection={connection} scan={perception.scan} hz={hz} />

        <div className="grid flex-1 gap-5 xl:grid-cols-[340px_minmax(0,1fr)_340px]">
          <div className="grid gap-5">
            <RadarQualityPanel perception={perception} />
            <Card>
              <div className="panel-header">
                <div>
                  <div className="station-kicker mb-2">mapping hooks / nav handoff / future slots</div>
                  <CardTitle>Mapping Prep</CardTitle>
                  <CardDescription>这页先把建图前观察和后续 Nav2 接入位都留好。</CardDescription>
                </div>
              </div>

              <div className="grid gap-3">
                <PrepRow title="SLAM source" value={navigation.map.ready ? `${navigation.map.width} x ${navigation.map.height}` : 'waiting /map'} />
                <PrepRow title="TF graph" value={navigation.tf.ready ? navigation.tf.statusMessage : 'waiting /tf'} />
                <PrepRow title="Localization" value={navigation.localization.ready ? navigation.localization.statusMessage : 'waiting /amcl_pose'} />
                <PrepRow title="Nav status" value={navigation.navStatus.ready ? navigation.navStatus.statusSummary : 'waiting nav2 actions'} />
              </div>
            </Card>
          </div>

          <div className="grid gap-5">
            <RadarViewport
              config={config}
              history={history}
              navigation={navigation}
              onPointSelect={setSelectedPoint}
              robotState={robotState}
              scan={perception.scan}
              selectedPoint={selectedPoint}
            />
            <RadarWorkbenchControls config={config} onClearHistory={() => setHistory([])} onConfigChange={setConfig} />
          </div>

          <div className="grid gap-5">
            <Card>
              <div className="panel-header">
                <div>
                  <div className="station-kicker mb-2">point inspector / field pick</div>
                  <CardTitle>Point Inspector</CardTitle>
                  <CardDescription>鼠标停在雷达点上时，这里显示当前射线的极坐标和直角坐标。</CardDescription>
                </div>
                <BadgeLike active={!!selectedPoint}>{selectedPoint ? 'locked' : 'idle'}</BadgeLike>
              </div>

              {selectedPoint ? (
                <div className="grid gap-3">
                  <InspectorRow label="Range" value={`${selectedPoint.rangeMeters.toFixed(3)} m`} />
                  <InspectorRow label="Angle" value={`${(selectedPoint.angleRad * 180 / Math.PI).toFixed(2)}°`} />
                  <InspectorRow label="X" value={selectedPoint.x.toFixed(3)} />
                  <InspectorRow label="Y" value={selectedPoint.y.toFixed(3)} />
                </div>
              ) : (
                <div className="station-well flex min-h-[240px] flex-col items-center justify-center rounded-[24px] text-center">
                  <Box className="mb-3 h-8 w-8 text-muted-foreground/45" />
                  <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">hover a point to inspect</div>
                </div>
              )}
            </Card>

            <Card>
              <div className="panel-header">
                <div>
                  <div className="station-kicker mb-2">operator note / source of truth</div>
                  <CardTitle>Sensor Note</CardTitle>
                  <CardDescription>当前页面显示的是 LaserScan 采样点，不是完整点云地图。</CardDescription>
                </div>
                <Map className="h-5 w-5 text-[hsl(var(--accent))]" />
              </div>

              <div className="grid gap-3 text-sm leading-6 text-muted-foreground">
                <div className="station-well rounded-[22px] px-4 py-4">
                  真相源是 `/scan`。如果后面要接点云、代价地图、路径规划，应该在这个页面继续叠层，而不是把当前扫描点当地图本身。
                </div>
                <div className="station-well rounded-[22px] px-4 py-4">
                  现在这页已经适合做三件事：检查扫描是否稳定、判断量程是否完整、确认建图前的姿态与传感器朝向是否合理。
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}

function PrepRow({
  title,
  value,
}: {
  title: string
  value: string
}) {
  return (
    <div className="station-well rounded-[22px] px-4 py-4">
      <div className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">{title}</div>
      <div className="text-sm font-semibold text-foreground/92">{value}</div>
    </div>
  )
}

function InspectorRow({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="station-well flex items-center justify-between gap-3 rounded-[20px] px-4 py-4">
      <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
      <div className="station-readout text-base font-semibold text-foreground/96">{value}</div>
    </div>
  )
}

function BadgeLike({
  active,
  children,
}: {
  active: boolean
  children: string
}) {
  return (
    <div
      className={
        active
          ? 'rounded-full border border-[hsl(var(--accent))] bg-[hsl(var(--accent))] px-3 py-1 text-xs uppercase tracking-[0.18em] text-[hsl(var(--accent-foreground))]'
          : 'rounded-full border border-border bg-secondary px-3 py-1 text-xs uppercase tracking-[0.18em] text-secondary-foreground'
      }
    >
      {children}
    </div>
  )
}
