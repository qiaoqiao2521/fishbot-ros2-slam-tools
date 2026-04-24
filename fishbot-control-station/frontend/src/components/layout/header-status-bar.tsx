import { Radio, Router, ShieldCheck, TimerReset } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { useStationStore } from '@/store/station-store'

export function HeaderStatusBar() {
  const { connection, usingFallbackData } = useStationStore()
  const isOffline = connection.mode === 'offline'
  const bannerVariant = usingFallbackData ? 'warning' : isOffline ? 'neutral' : 'success'
  const bannerText = usingFallbackData
    ? 'fallback snapshot'
    : isOffline
      ? 'offline simulator'
      : 'live robot link'
  const descriptionText = usingFallbackData
    ? '前端当前在展示本地兜底快照。后端或事件流还没有接管状态。'
    : isOffline
      ? '当前是无车开发模式。控制命令会驱动模拟 odom/imu 状态，适合继续做 UI 和交互联调。'
      : '当前是实机链路。Spring Boot 同时聚合控制桥 9090 和雷达桥 9091，Web 控制台只连一个 backend。'

  return (
    <Card className="rounded-[36px] px-6 py-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-2">
          <Badge variant={bannerVariant} className="w-fit">
            {bannerText}
          </Badge>
          <div className="station-kicker">industrial survey deck / field operator console</div>
          <CardTitle className="text-2xl font-semibold tracking-[0.1em] md:text-[2.2rem]">
            FishBot Control Station
          </CardTitle>
          <CardDescription>{descriptionText}</CardDescription>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatusChip
            icon={Radio}
            label="Control bridge"
            value={isOffline ? 'bypassed' : connection.controlBridge.connected ? 'connected' : 'offline'}
            tone={isOffline ? 'neutral' : connection.controlBridge.connected ? 'success' : 'danger'}
          />
          <StatusChip
            icon={ShieldCheck}
            label="Control feed"
            value={isOffline ? 'simulated' : connection.controlBridge.telemetryOnline ? 'online' : 'stale'}
            tone={isOffline ? 'neutral' : connection.controlBridge.telemetryOnline ? 'success' : 'warning'}
          />
          <StatusChip
            icon={TimerReset}
            label="Laser bridge"
            value={isOffline ? 'bypassed' : connection.laserBridge.connected ? 'connected' : 'offline'}
            tone={isOffline ? 'neutral' : connection.laserBridge.connected ? 'success' : 'danger'}
          />
          <StatusChip
            icon={Router}
            label="Laser feed"
            value={isOffline ? 'simulated' : connection.laserBridge.telemetryOnline ? 'online' : 'stale'}
            tone={isOffline ? 'neutral' : connection.laserBridge.telemetryOnline ? 'success' : 'warning'}
          />
        </div>
      </div>
    </Card>
  )
}

function StatusChip({
  icon: Icon,
  label,
  tone,
  value,
}: {
  icon: typeof Radio
  label: string
  value: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
}) {
  return (
    <div className="station-well rounded-[24px] px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="flex items-center gap-2">
        <Badge variant={tone}>{tone}</Badge>
        <span className="station-readout truncate text-sm font-medium text-foreground/92">{value}</span>
      </div>
    </div>
  )
}
