import { Activity, Clock3, Radar, Router, Wifi } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { ConnectionSnapshot, LaserScanSnapshot } from '@/types/station'

function formatTime(timestamp: string) {
  if (!timestamp || timestamp.startsWith('1970-01-01')) {
    return '--:--:--'
  }

  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(timestamp))
}

export function RadarStatusStrip({
  connection,
  hz,
  scan,
}: {
  connection: ConnectionSnapshot
  scan: LaserScanSnapshot
  hz: number
}) {
  const transportTone = connection.laserBridge.connected ? 'success' : 'danger'
  const scanTone = scan.ready ? 'success' : 'warning'

  return (
    <div className="glass-panel rounded-[30px] px-5 py-4">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex flex-wrap items-center gap-3 text-xs uppercase tracking-[0.18em] text-muted-foreground">
          <Badge variant={transportTone}>{connection.laserBridge.connected ? 'transport up' : 'transport down'}</Badge>
          <Badge variant={scanTone}>{scan.ready ? 'scan live' : 'scan waiting'}</Badge>
          <span className="station-readout text-foreground/92">FishBot Radar Workbench</span>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <Metric icon={Router} label="Endpoint" value={connection.laserBridge.endpoint} />
          <Metric icon={Radar} label="Frame" value={scan.frameId || 'laser_frame'} />
          <Metric icon={Activity} label="Refresh" value={`${hz.toFixed(1)} Hz`} />
          <Metric icon={Wifi} label="Beams" value={`${scan.samplePoints.length}/${scan.beamCount}`} />
          <Metric icon={Clock3} label="Last update" value={formatTime(scan.lastUpdate)} />
        </div>
      </div>
    </div>
  )
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Router
  label: string
  value: string
}) {
  return (
    <div className="station-well rounded-[20px] px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="truncate text-sm font-semibold text-foreground/92">{value}</div>
    </div>
  )
}
