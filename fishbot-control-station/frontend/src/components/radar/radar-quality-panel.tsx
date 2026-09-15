import { AlertTriangle, Gauge, ShieldCheck, Waves } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { buildRadarWorkbenchMetrics } from '@/lib/radar-workbench'
import type { PerceptionSnapshot } from '@/types/station'

export function RadarQualityPanel({
  perception,
}: {
  perception: PerceptionSnapshot
}) {
  const metrics = buildRadarWorkbenchMetrics(perception.scan)
  const obstructionTone = metrics.obstructionLevel === 'high' ? 'danger' : metrics.obstructionLevel === 'moderate' ? 'warning' : 'success'

  return (
    <Card className="h-full">
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">scan health / density / obstacle pressure</div>
          <CardTitle>Data Quality</CardTitle>
          <CardDescription>把 `/scan` 的可用度、覆盖范围和近场风险放到一个固定面板里看。</CardDescription>
        </div>
        <Badge variant={perception.scan.ready ? 'success' : 'warning'}>{perception.scan.ready ? 'live' : 'waiting'}</Badge>
      </div>

      <div className="grid gap-4">
        <MetricRow
          icon={ShieldCheck}
          label="Valid point ratio"
          value={`${metrics.validRatio.toFixed(1)}%`}
          hint={`${metrics.sampleCount} samples / ${metrics.beamCount} beams`}
        />
        <Progress value={Math.min(metrics.validRatio, 100)} tone={metrics.validRatio > 20 ? 'success' : 'warning'} />

        <div className="grid gap-3 md:grid-cols-2">
          <MetricCard
            icon={Gauge}
            label="Coverage"
            value={`${metrics.coverageRatio.toFixed(0)}%`}
            detail="12-sector occupancy"
          />
          <MetricCard
            icon={AlertTriangle}
            label="Near-field hits"
            value={`${metrics.nearFieldCount}`}
            detail="points <= 0.8m"
          />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <SensorCard
            label="Ultrasonic"
            value={perception.ultrasonic.ready ? `${perception.ultrasonic.distanceMeters.toFixed(2)} m` : 'waiting'}
            detail={perception.ultrasonic.statusMessage}
            tone={perception.ultrasonic.blocked ? 'danger' : perception.ultrasonic.ready ? 'success' : 'warning'}
          />
          <SensorCard
            label="Infrared"
            value={perception.infrared.ready ? `${perception.infrared.distanceMeters.toFixed(2)} m` : 'waiting'}
            detail={perception.infrared.statusMessage}
            tone={perception.infrared.blocked ? 'danger' : perception.infrared.ready ? 'success' : 'warning'}
          />
        </div>

        <div className="station-well rounded-[22px] px-4 py-4">
          <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
            <Waves className="h-4 w-4" />
            Obstruction level
          </div>
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm leading-6 text-foreground/88">
              近场点过多时，说明机器人前方存在明显障碍，适合在后续接局部代价地图时直接高亮。
            </div>
            <Badge variant={obstructionTone}>{metrics.obstructionLevel}</Badge>
          </div>
        </div>
      </div>
    </Card>
  )
}

function MetricRow({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof ShieldCheck
  label: string
  value: string
  hint: string
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="station-well rounded-[18px] p-3">
          <Icon className="h-4 w-4 text-[hsl(var(--accent))]" />
        </div>
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
          <div className="text-xs text-muted-foreground">{hint}</div>
        </div>
      </div>
      <div className="station-readout text-xl font-semibold text-foreground/96">{value}</div>
    </div>
  )
}

function MetricCard({
  detail,
  icon: Icon,
  label,
  value,
}: {
  icon: typeof ShieldCheck
  label: string
  value: string
  detail: string
}) {
  return (
    <div className="station-well rounded-[22px] px-4 py-4">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="station-readout text-2xl font-semibold text-foreground/96">{value}</div>
      <div className="mt-2 text-xs text-muted-foreground">{detail}</div>
    </div>
  )
}

function SensorCard({
  detail,
  label,
  tone,
  value,
}: {
  label: string
  value: string
  detail: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
}) {
  return (
    <div className="station-well rounded-[22px] px-4 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
        <Badge variant={tone}>{tone}</Badge>
      </div>
      <div className="station-readout text-lg font-semibold text-foreground/96">{value}</div>
      <div className="mt-2 text-xs leading-5 text-muted-foreground">{detail}</div>
    </div>
  )
}

function Progress({
  tone,
  value,
}: {
  value: number
  tone: 'success' | 'warning'
}) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-[rgba(91,69,35,0.12)]">
      <div
        className={tone === 'success' ? 'h-full bg-[hsl(var(--accent))]' : 'h-full bg-[hsl(var(--destructive))]'}
        style={{ width: `${value}%` }}
      />
    </div>
  )
}
