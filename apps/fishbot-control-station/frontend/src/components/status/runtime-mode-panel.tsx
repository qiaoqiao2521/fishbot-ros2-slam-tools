import { Badge } from '@/components/ui/badge'
import { getModePresentation } from '@/lib/station-runtime'
import { useStationStore } from '@/store/station-store'

export function RuntimeModePanel() {
  const { connection, usingFallbackData } = useStationStore()
  const mode = getModePresentation(connection, usingFallbackData)
  const isFallback = usingFallbackData || connection.mode === 'fallback'
  const isOffline = connection.mode === 'offline'
  const label = isFallback ? '前端示例快照' : isOffline ? '离线模拟' : 'ROS 实时链路'
  const capability = isFallback ? '界面预览' : isOffline ? '后端模拟遥测与控制' : connection.robotOnline ? 'ROS 遥测与控制' : '控制链路，等待遥测'

  return <section className="station-section" aria-labelledby="runtime-mode-heading">
    <div className="station-section-heading">
      <h2 id="runtime-mode-heading">运行模式</h2>
      <Badge variant={isFallback ? mode.tone : 'neutral'}>{label}</Badge>
    </div>
    <dl className="station-data-grid">
      <RuntimeMetric label="当前能力" value={capability} />
      <RuntimeMetric label="数据来源" value={isFallback ? '前端本地示例' : connection.endpoint} />
      <RuntimeMetric label="服务报告" value={connection.statusLabel} />
    </dl>
    <p className="mt-3 text-xs leading-5 text-muted-foreground">
      {isFallback ? '尚未确认实时数据来源。' : isOffline ? '模拟状态用于界面和控制联调。' : 'ROS 消息可能来自仿真或设备；链路连接不证明实体在线。'}
    </p>
  </section>
}

function RuntimeMetric({ label, value }: { label: string; value: string }) {
  return <div className="station-metric"><dt>{label}</dt><dd className="station-value break-all">{value || '未提供'}</dd></div>
}
