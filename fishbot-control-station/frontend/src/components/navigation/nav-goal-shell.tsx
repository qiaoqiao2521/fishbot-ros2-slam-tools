import { useState } from 'react'
import { CircleDashed, Route, Trash2, Undo2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { getNavigationTaskPresentation, type NavigationActionPreview } from '@/components/navigation/navigation-task'
import { useStationStore } from '@/store/station-store'

export function NavGoalShell() {
  const { connection, robotState, navigation, usingFallbackData } = useStationStore()
  const [previewAction, setPreviewAction] = useState<NavigationActionPreview>('idle')
  const view = getNavigationTaskPresentation(connection, robotState, navigation, usingFallbackData, previewAction)

  return (
    <section className="station-well rounded-[28px] p-5 md:p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <div className="station-kicker mb-2">queue preview / command fence / dispatch guardrail</div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em] text-foreground/90">
            <Route className="h-4 w-4 text-accent" />
            goal queue
          </div>
          <h3 className="text-xl font-semibold tracking-[0.02em] text-foreground">Navigation goal queue</h3>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            这里先保留目标点队列、取消和清空的交互骨架。按钮只改本地预览，不会假装已经把真实目标送进 Nav2。
          </p>
        </div>
        <Badge variant={view.cancelDisabled ? 'warning' : 'neutral'}>{view.modeLabel}</Badge>
      </div>

      <div className="station-chip mb-4 rounded-3xl p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="station-kicker">preview state</div>
          <Badge variant={previewAction === 'idle' ? 'neutral' : 'success'}>{view.actionLabel}</Badge>
        </div>
        <p className="text-sm leading-6 text-foreground/84">{view.actionHint}</p>
      </div>

      <div className="space-y-3">
        {view.queueItems.map((item) => (
          <div
            key={item.slot}
            className="station-chip rounded-3xl p-4 transition-colors hover:bg-[rgba(255,248,235,0.92)]"
          >
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                  <CircleDashed className="h-4 w-4" />
                  slot {item.slot}
                </div>
                <div className="mt-2 text-base font-semibold text-foreground/92">{item.title}</div>
              </div>
              <Badge variant={item.tone}>{item.state}</Badge>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
              <span>{item.source}</span>
              <span className="text-white/18">/</span>
              <span>{item.detail}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          className="gap-2"
          disabled={view.cancelDisabled}
          onClick={() => setPreviewAction('cancel-active')}
        >
          <Trash2 className="h-4 w-4" />
          Cancel active
        </Button>
        <Button
          type="button"
          variant="emergency"
          className="gap-2"
          disabled={view.clearDisabled}
          onClick={() => setPreviewAction('clear-queue')}
        >
          <Trash2 className="h-4 w-4" />
          Clear queue
        </Button>
        {previewAction !== 'idle' ? (
          <Button type="button" variant="ghost" className="gap-2" onClick={() => setPreviewAction('idle')}>
            <Undo2 className="h-4 w-4" />
            Reset preview
          </Button>
        ) : null}
      </div>
    </section>
  )
}
