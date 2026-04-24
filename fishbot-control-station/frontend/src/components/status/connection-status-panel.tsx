import { Activity, Bot, Cable, Clock3 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { useStationStore } from '@/store/station-store'

export function ConnectionStatusPanel() {
  const { connection } = useStationStore()
  const isOffline = connection.mode === 'offline'
  const badgeVariant = isOffline ? 'neutral' : connection.reconnecting ? 'warning' : 'success'
  const badgeLabel = isOffline ? 'offline simulator' : connection.reconnecting ? 'reconnecting' : 'steady'
  const summary = isOffline
    ? '当前没有走 rosbridge 真链路，面板展示的是后端离线遥测。适合继续做控制台开发和动作回放。'
    : '面向联调的双桥连接面板。控制页看 9090，雷达页看 9091，但浏览器始终只连同一个 backend。'

  return (
    <Card>
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">transport summary / signal integrity</div>
          <CardTitle>Connection Surface</CardTitle>
          <CardDescription>{summary}</CardDescription>
        </div>
        <Badge variant={badgeVariant}>
          {badgeLabel}
        </Badge>
      </div>

      <div className="metric-grid">
        <ConnectionMetric
          icon={Cable}
          label="Control bridge"
          value={isOffline ? 'bypassed' : connection.controlBridge.connected ? 'connected' : 'disconnected'}
        />
        <ConnectionMetric
          icon={Bot}
          label="Control feed"
          value={isOffline ? 'simulated' : connection.controlBridge.telemetryOnline ? 'online' : 'stale'}
        />
        <ConnectionMetric
          icon={Clock3}
          label="Laser bridge"
          value={isOffline ? 'bypassed' : connection.laserBridge.connected ? 'connected' : 'disconnected'}
        />
        <ConnectionMetric
          icon={Activity}
          label="Laser feed"
          value={isOffline ? 'simulated' : connection.laserBridge.telemetryOnline ? 'online' : 'stale'}
        />
        <ConnectionMetric icon={Cable} label="Control endpoint" value={connection.controlBridge.endpoint} />
        <ConnectionMetric icon={Activity} label="Laser endpoint" value={connection.laserBridge.endpoint} />
      </div>
    </Card>
  )
}

function ConnectionMetric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Cable
  label: string
  value: string
}) {
  return (
    <div className="station-well rounded-[24px] p-4">
      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="station-readout text-lg font-semibold text-foreground/92">{value}</div>
    </div>
  )
}
