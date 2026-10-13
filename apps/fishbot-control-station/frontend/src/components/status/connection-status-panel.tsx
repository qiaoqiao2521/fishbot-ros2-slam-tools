import { Badge } from '@/components/ui/badge'
import { useStationStore } from '@/store/station-store'

export function ConnectionStatusPanel() {
  const { connection, usingFallbackData } = useStationStore()
  const isFallback = usingFallbackData || connection.mode === 'fallback'
  const isOffline = connection.mode === 'offline'
  const connectionReport = (connected: boolean) => isFallback ? '未核实' : isOffline ? '未使用' : connected ? '已连接' : '未连接'
  const telemetryReport = (online: boolean) => isFallback ? '示例数据' : isOffline ? '后端模拟' : online ? '已报告遥测' : '未报告新遥测'

  return <section className="station-section" aria-labelledby="connection-details-heading">
    <div className="station-section-heading">
      <h2 id="connection-details-heading">链路与来源</h2>
      <Badge variant={isFallback ? 'warning' : 'neutral'}>
        {isFallback ? '示例快照' : isOffline ? '离线模拟' : connection.reconnecting ? '正在重连' : '最近桥接报告'}
      </Badge>
    </div>
    <dl className="station-data-grid">
      <ConnectionMetric label="控制传输" value={connectionReport(connection.controlBridge.connected)} />
      <ConnectionMetric label="控制遥测" value={telemetryReport(connection.controlBridge.telemetryOnline)} />
      <ConnectionMetric label="雷达传输" value={connectionReport(connection.laserBridge.connected)} />
      <ConnectionMetric label="雷达遥测" value={telemetryReport(connection.laserBridge.telemetryOnline)} />
      <ConnectionMetric label="控制地址" value={connection.controlBridge.endpoint} />
      <ConnectionMetric label="雷达地址" value={connection.laserBridge.endpoint} />
      <ConnectionMetric label="控制报告时间" value={connection.controlBridge.lastMessageAt} />
      <ConnectionMetric label="雷达报告时间" value={connection.laserBridge.lastMessageAt} />
    </dl>
    <p className="mt-3 text-xs leading-5 text-muted-foreground">传输连接不代表实体在线或已经停稳。</p>
  </section>
}

function ConnectionMetric({ label, value }: { label: string; value: string }) {
  return <div className="station-metric"><dt>{label}</dt><dd className="station-value break-all">{value || '未提供'}</dd></div>
}
