import { Compass, Gauge, Orbit, Waves } from 'lucide-react'

import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useStationStore } from '@/store/station-store'

export function RobotStatePanel() {
  const { connection, robotState } = useStationStore()
  const { imu, odom } = robotState
  const isOffline = connection.mode === 'offline'

  return (
    <Card>
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">odometry / inertial stream / cadence</div>
          <CardTitle>Robot Observation</CardTitle>
          <CardDescription>
            {isOffline
              ? '当前显示的是离线运动学回放状态。适合校验控制交互、节奏和面板布局，不代表真实传感器噪声。'
              : '实时显示 odom、imu、消息频率和最后一次状态时间戳。'}
          </CardDescription>
        </div>
        <div className="text-right">
          {isOffline ? (
            <Badge variant="neutral" className="mb-2 ml-auto w-fit">
              simulated state
            </Badge>
          ) : null}
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Stream cadence</div>
          <div className="station-readout text-2xl font-semibold text-accent">{robotState.messageRateHz == null ? '未测量' : `${robotState.messageRateHz.toFixed(1)} Hz`}</div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <StateCluster
          icon={Compass}
          title="Odom pose"
          metrics={[
            ['x', `${odom.x.toFixed(3)} m`],
            ['y', `${odom.y.toFixed(3)} m`],
            ['yaw', `${odom.yaw.toFixed(3)} rad`],
          ]}
        />
        <StateCluster
          icon={Gauge}
          title="Velocity"
          metrics={[
            ['linear', `${odom.linearVelocity.toFixed(3)} m/s`],
            ['angular', `${odom.angularVelocity.toFixed(3)} rad/s`],
            ['last update', new Date(robotState.lastUpdatedAt).toLocaleTimeString('zh-CN')],
          ]}
        />
        <StateCluster
          icon={Waves}
          title="IMU angular velocity"
          metrics={[
            ['x', imu.angularVelocity.x.toFixed(3)],
            ['y', imu.angularVelocity.y.toFixed(3)],
            ['z', imu.angularVelocity.z.toFixed(3)],
          ]}
        />
        <StateCluster
          icon={Orbit}
          title="IMU acceleration / orientation"
          metrics={[
            [
              'acc',
              `${imu.linearAcceleration.x.toFixed(2)}, ${imu.linearAcceleration.y.toFixed(2)}, ${imu.linearAcceleration.z.toFixed(2)}`,
            ],
            [
              'rpy',
              imu.orientation
                ? `${imu.orientation.roll.toFixed(2)}, ${imu.orientation.pitch.toFixed(2)}, ${imu.orientation.yaw.toFixed(2)}`
                : 'n/a',
            ],
            ['frame', 'imu_link'],
          ]}
        />
      </div>
    </Card>
  )
}

function StateCluster({
  icon: Icon,
  metrics,
  title,
}: {
  icon: typeof Compass
  title: string
  metrics: Array<[string, string]>
}) {
  return (
    <div className="station-well rounded-[28px] p-5">
      <div className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">
        <Icon className="h-4 w-4 text-accent" />
        {title}
      </div>
      <div className="space-y-3">
        {metrics.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-3 border-b border-border/40 pb-3 last:border-b-0 last:pb-0">
            <span className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{label}</span>
            <span className="station-readout text-sm font-semibold text-foreground/92">{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
