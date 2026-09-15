import { Activity, Clock3, MessageSquareMore, ShieldCheck, Radar } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { getNavigationTaskPresentation } from '@/components/navigation/navigation-task'
import { useStationStore } from '@/store/station-store'

export function TaskStatusShell() {
  const { connection, robotState, navigation, usingFallbackData } = useStationStore()
  const view = getNavigationTaskPresentation(connection, robotState, navigation, usingFallbackData)

  return (
    <section className="station-well rounded-[28px] p-5 md:p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <div className="station-kicker mb-2">action state / queue policy / operator guard</div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-foreground/90">
            <Activity className="h-4 w-4 text-accent" />
            task status
          </div>
          <h3 className="text-xl font-semibold tracking-[0.02em] text-foreground">Operator task status</h3>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            这些状态卡只描述操作骨架、源头和接线点，不把当前页面包装成已经接好真实导航回执。
          </p>
        </div>
        <Badge variant={view.cancelDisabled ? 'warning' : 'neutral'}>{view.modeLabel}</Badge>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {view.taskCards.map((card) => (
          <div key={card.title} className="station-chip rounded-3xl p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
                {iconForCard(card.title)}
                {card.title}
              </div>
              <Badge variant={card.tone}>{card.tone}</Badge>
            </div>
            <div className="text-lg font-semibold text-foreground/92">{card.value}</div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{card.hint}</p>
          </div>
        ))}
      </div>

      <div className="station-dashed mt-4 rounded-3xl p-4">
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
          <ShieldCheck className="h-4 w-4 text-accent" />
          operator note
        </div>
        <p className="text-sm leading-6 text-foreground/84">{view.operatorNote}</p>
      </div>

      <div className="station-chip mt-4 grid gap-3 rounded-3xl p-4 md:grid-cols-[1fr_auto] md:items-center">
        <div>
          <div className="station-kicker">wiring checklist</div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-foreground/82">
            <span className="rounded-full border border-border/80 px-3 py-1">`/navigate_to_pose`</span>
            <span className="rounded-full border border-border/80 px-3 py-1">`/goal_pose`</span>
            <span className="rounded-full border border-border/80 px-3 py-1">`/cancel_goal`</span>
            <span className="rounded-full border border-border/80 px-3 py-1">task ack</span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <MessageSquareMore className="h-4 w-4 text-accent" />
          {view.modeSummary}
        </div>
      </div>
    </section>
  )
}

function iconForCard(title: string) {
  if (title === 'Source of truth') return <Radar className="h-4 w-4 text-accent" />
  if (title === 'Dispatch path') return <Activity className="h-4 w-4 text-accent" />
  if (title === 'Queue policy') return <ShieldCheck className="h-4 w-4 text-accent" />
  return <Clock3 className="h-4 w-4 text-accent" />
}
