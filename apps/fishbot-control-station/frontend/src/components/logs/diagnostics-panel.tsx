import { Download } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
    <section className="station-section" aria-labelledby="diagnostics-heading">
      <div className="station-section-heading">
        <h2 id="diagnostics-heading">日志与诊断</h2>
        <Button variant="outline" className="gap-2" onClick={exportLogs}>
          <Download className="h-4 w-4" />
          导出快照
        </Button>
      </div>

      <div className="station-logs-grid">
        <LogColumn title="控制命令" entries={diagnostics.commands} />
        <LogColumn title="错误与警告" entries={diagnostics.errors} />
        <LogColumn title="连接记录" entries={diagnostics.transport} />
      </div>
    </section>
  )
}

function LogColumn({
  entries,
  title,
}: {
  title: string
  entries: DiagnosticEntry[]
}) {
  return (
    <div className="min-w-0">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {entries.length === 0 && <p className="text-sm text-muted-foreground">暂无记录</p>}
      <ul className="station-log-list">
        {entries.map((entry) => (
          <li key={entry.id}>
            <div className="mb-1 flex items-center justify-between gap-3">
              <Badge
                variant={
                  entry.level === 'error'
                    ? 'danger'
                    : entry.level === 'warning'
                      ? 'warning'
                      : 'neutral'
                }
              >
                {{ error: '错误', warning: '警告', info: '记录' }[entry.level]}
              </Badge>
              <time dateTime={entry.timestamp} className="text-xs text-muted-foreground">
                {new Date(entry.timestamp).toLocaleTimeString('zh-CN')}
              </time>
            </div>
            <p className="break-words text-sm leading-6">{entry.message}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
