import { AlertTriangle, Command, Download, WavesLadder } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { buildExportSnapshot } from '@/lib/station-runtime'
import { useStationStore } from '@/store/station-store'
import type { DiagnosticEntry } from '@/types/station'

export function DiagnosticsPanel() {
  const { connection, controlFeedback, diagnostics, navigation, perception, robotState, usingFallbackData } = useStationStore()

  function exportLogs() {
    const snapshot = buildExportSnapshot(
      connection,
      robotState,
      navigation,
      perception,
      diagnostics,
      controlFeedback,
      usingFallbackData,
    )
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    link.href = url
    link.download = `fishbot-station-${snapshot.mode}-${timestamp}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Card>
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">operator trace / transport notes / incident export</div>
          <CardTitle>Logs & Diagnostics</CardTitle>
          <CardDescription>
            保留最近控制命令、错误和 rosbridge 连接日志，同时为地图、导航和任务调试扩展留出入口。
          </CardDescription>
        </div>
        <Button variant="outline" className="gap-2" onClick={exportLogs}>
          <Download className="h-4 w-4" />
          导出快照
        </Button>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <LogColumn icon={Command} title="Recent commands" entries={diagnostics.commands} />
        <LogColumn icon={AlertTriangle} title="Recent errors" entries={diagnostics.errors} />
        <LogColumn icon={WavesLadder} title="Transport log" entries={diagnostics.transport} />
      </div>
    </Card>
  )
}

function LogColumn({
  entries,
  icon: Icon,
  title,
}: {
  icon: typeof Command
  title: string
  entries: DiagnosticEntry[]
}) {
  return (
    <div className="station-well rounded-[28px] p-4">
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">
        <Icon className="h-4 w-4 text-accent" />
        {title}
      </div>
      <div className="space-y-3">
        {entries.map((entry) => (
          <div key={entry.id} className="station-chip rounded-2xl p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <Badge
                variant={
                  entry.level === 'error'
                    ? 'danger'
                    : entry.level === 'warning'
                      ? 'warning'
                      : 'neutral'
                }
              >
                {entry.level}
              </Badge>
              <span className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                {new Date(entry.timestamp).toLocaleTimeString('zh-CN')}
              </span>
            </div>
            <p className="text-sm leading-6 text-foreground/84">{entry.message}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
