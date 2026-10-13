import { Badge } from '@/components/ui/badge'
import { useStationStore } from '@/store/station-store'

export function RobotStatePanel() {
  const { connection, robotState, usingFallbackData } = useStationStore()
  const { imu, odom } = robotState
  const isFallback = usingFallbackData || connection.mode === 'fallback'
  const isOffline = connection.mode === 'offline'

  return <section className="station-section" aria-labelledby="robot-state-heading">
    <div className="station-section-heading">
      <h2 id="robot-state-heading">机器人状态</h2>
      <Badge variant={isFallback ? 'warning' : 'neutral'}>{isFallback ? '示例快照' : isOffline ? '离线模拟' : '最近遥测'}</Badge>
    </div>
    <dl className="station-data-grid">
      <StateMetric label="位置 X" value={odom.x.toFixed(3)} unit="m" />
      <StateMetric label="位置 Y" value={odom.y.toFixed(3)} unit="m" />
      <StateMetric label="朝向" value={odom.yaw.toFixed(3)} unit="rad" />
      <StateMetric label="线速度" value={odom.linearVelocity.toFixed(3)} unit="m/s" />
      <StateMetric label="角速度" value={odom.angularVelocity.toFixed(3)} unit="rad/s" />
      <StateMetric label="消息频率" value={robotState.messageRateHz == null ? '未测量' : robotState.messageRateHz.toFixed(1)} unit={robotState.messageRateHz == null ? undefined : 'Hz'} />
    </dl>
    <p className="mt-3 text-xs leading-5 text-muted-foreground">状态时间 {new Date(robotState.lastUpdatedAt).toLocaleTimeString('zh-CN')}</p>
    <details className="station-details">
      <summary>IMU 数据</summary>
      <dl className="grid gap-3">
        <StateMetric label="角速度 X / Y / Z" value={[imu.angularVelocity.x, imu.angularVelocity.y, imu.angularVelocity.z].map((value) => value.toFixed(3)).join(' / ')} unit="rad/s" />
        <StateMetric label="加速度 X / Y / Z" value={[imu.linearAcceleration.x, imu.linearAcceleration.y, imu.linearAcceleration.z].map((value) => value.toFixed(2)).join(' / ')} unit="m/s²" />
        <StateMetric label="横滚 / 俯仰 / 偏航" value={imu.orientation ? [imu.orientation.roll, imu.orientation.pitch, imu.orientation.yaw].map((value) => value.toFixed(2)).join(' / ') : '未提供'} unit={imu.orientation ? 'rad' : undefined} />
      </dl>
    </details>
  </section>
}

function StateMetric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return <div className="station-metric"><dt>{label}</dt><dd className="station-value" style={{ fontSize: 18 }}>{value}{unit && <> <small>{unit}</small></>}</dd></div>
}
