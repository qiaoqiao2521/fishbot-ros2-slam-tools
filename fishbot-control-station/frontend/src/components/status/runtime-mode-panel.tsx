import { Cpu, DatabaseZap, RadioTower, ShieldEllipsis } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { getModePresentation } from '@/lib/station-runtime'
import { useStationStore } from '@/store/station-store'

export function RuntimeModePanel() {
  const { connection, usingFallbackData } = useStationStore()
  const mode = getModePresentation(connection, usingFallbackData)

  const facts = [
    {
      icon: ShieldEllipsis,
      label: 'Runtime mode',
      value: mode.label,
    },
    {
      icon: DatabaseZap,
      label: 'Capability',
      value: mode.capability,
    },
    {
      icon: RadioTower,
      label: 'Data source',
      value: usingFallbackData ? 'frontend local mock' : connection.endpoint,
    },
    {
      icon: Cpu,
      label: 'Operator note',
      value: connection.statusLabel,
    },
  ]

  return (
    <Card>
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">source of truth / capability envelope</div>
          <CardTitle>Runtime Mode</CardTitle>
          <CardDescription>{mode.summary}</CardDescription>
        </div>
        <Badge variant={mode.tone}>{mode.label}</Badge>
      </div>

      <div className="station-well rounded-[28px] p-5">
        <p className="mb-4 text-sm leading-6 text-foreground/84">{mode.detail}</p>

        <div className="grid gap-4 md:grid-cols-2">
          {facts.map((fact) => (
            <div key={fact.label} className="station-chip rounded-2xl p-4">
              <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                <fact.icon className="h-4 w-4" />
                {fact.label}
              </div>
              <div className="station-readout text-sm font-semibold text-foreground/92">{fact.value}</div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  )
}
