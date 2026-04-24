import type { ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, CornerDownLeft, Pause, RotateCcw, TriangleAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { Slider } from '@/components/ui/slider'
import { useTeleopControl } from '@/hooks/use-teleop-control'
import { useStationStore } from '@/store/station-store'
import type { ControlDirection } from '@/types/station'

const motionButtons: Array<{
  direction: Exclude<ControlDirection, 'stop'>
  label: string
  hint: string
  icon: typeof ChevronUp
  className: string
}> = [
  { direction: 'forward', label: '前进', hint: 'W / ↑', icon: ChevronUp, className: 'col-start-2 row-start-1' },
  { direction: 'left', label: '左转', hint: 'A / ←', icon: ChevronLeft, className: 'col-start-1 row-start-2' },
  { direction: 'right', label: '右转', hint: 'D / →', icon: ChevronRight, className: 'col-start-3 row-start-2' },
  { direction: 'backward', label: '后退', hint: 'S / ↓', icon: ChevronDown, className: 'col-start-2 row-start-3' },
]

export function MotionControlPanel() {
  const { activeDirection, begin, emergencyStop, stop } = useTeleopControl()
  const { angularSpeed, controlFeedback, linearSpeed, setAngularSpeed, setLinearSpeed } = useStationStore()

  return (
    <Card className="overflow-hidden">
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">manual vector dispatch / hold to run</div>
          <CardTitle>Motion Control</CardTitle>
          <CardDescription>
            方向键和 WASD 已全局启用：按住持续发指令，松开即停；窗口失焦或切走页面会自动停车。
          </CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={activeDirection ? 'success' : 'neutral'}>{activeDirection ? `keyboard: ${activeDirection}` : 'keyboard armed'}</Badge>
          <Button size="lg" variant="emergency" onClick={() => void emergencyStop()} className="gap-2">
            <TriangleAlert className="h-5 w-5" />
            急停
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="station-well rounded-[30px] p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="station-kicker">Directional pad</div>
            <div className="text-sm text-foreground/80">
              当前指令:
              <span className="station-readout ml-2 font-semibold uppercase tracking-[0.16em] text-accent">
                {activeDirection ?? 'idle'}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-3 grid-rows-3 gap-3">
            {motionButtons.map((button) => (
              <Button
                key={button.direction}
                className={`station-console-button station-well h-24 flex-col gap-1 rounded-[26px] border-[hsl(var(--border)/0.84)] bg-[linear-gradient(180deg,rgba(255,251,243,0.72),rgba(229,217,191,0.82))] text-base shadow-[0_12px_28px_rgba(92,70,30,0.08)] hover:bg-[linear-gradient(180deg,rgba(255,252,246,0.88),rgba(235,224,200,0.94))] ${activeDirection === button.direction ? 'station-console-button-active' : ''} ${button.className}`}
                variant="ghost"
                onPointerCancel={() => void stop()}
                onPointerDown={() => void begin(button.direction)}
                onPointerLeave={() => void stop()}
                onPointerUp={() => void stop()}
              >
                <button.icon className="h-5 w-5 text-accent" />
                <span>{button.label}</span>
                <span className="station-kicker">{button.hint}</span>
              </Button>
            ))}

            <Button
              className="col-start-2 row-start-2 h-24 flex-col gap-2 rounded-[26px]"
              variant="outline"
              onClick={() => void stop()}
            >
              <Pause className="h-5 w-5" />
              停止
            </Button>
          </div>
        </div>

        <div className="grid gap-5">
          <div className="station-well grid gap-4 rounded-[30px] p-5 md:grid-cols-2">
            <Slider label="Linear velocity" max={1.2} min={0.05} onChange={setLinearSpeed} value={linearSpeed} suffix=" m/s" />
            <Slider label="Angular velocity" max={2.4} min={0.05} onChange={setAngularSpeed} value={angularSpeed} suffix=" rad/s" />
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <ReadoutCard
              label="Linear setpoint"
              value={`${linearSpeed.toFixed(2)} m/s`}
              detail="低速建图先从 0.12 到 0.18 m/s 开始。"
            />
            <ReadoutCard
              label="Angular setpoint"
              value={`${angularSpeed.toFixed(2)} rad/s`}
              detail="角速度过大时，地图边角最容易撕裂。"
            />
            <ReadoutCard
              label="Hold cadence"
              value={`${controlFeedback.holdCadenceMs} ms`}
              detail={controlFeedback.throttleActive ? '节流窗生效，阻止过快重复发送。' : '长按期间按固定节奏重复派发。'}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <ReadoutCard
              label="Release to zero"
              value={controlFeedback.releaseToZeroArmed ? 'armed' : 'idle'}
              detail={controlFeedback.releaseToZeroArmed ? '当前有运动指令悬挂，松手会主动回零。' : '当前没有挂起运动方向。'}
            />
            <ReadoutCard
              label="Last control ack"
              value={controlFeedback.lastAckMessage}
              detail={controlFeedback.lastAckAt ?? '尚未收到本地控制回执。'}
              compact
            />
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <TelemetryHint
              title="Hold-to-run"
              description="按住发送重复 cmd_vel，释放立即调用 stop。"
            />
            <TelemetryHint
              title="Safety first"
              description="急停是独立接口，不走普通控制路径。"
            />
            <TelemetryHint
              title="Keyboard backup"
              description="空格立即 stop，方向键与 WASD 只作为备份。"
              icon={<CornerDownLeft className="h-4 w-4" />}
            />
          </div>
        </div>
      </div>
    </Card>
  )
}

function ReadoutCard({
  compact = false,
  detail,
  label,
  value,
}: {
  label: string
  value: string
  detail: string
  compact?: boolean
}) {
  return (
    <div className="station-chip rounded-[24px] p-4">
      <div className="station-kicker mb-2">{label}</div>
      <div className={`${compact ? 'text-sm tracking-[0.04em]' : 'text-lg'} station-readout font-semibold text-foreground/92`}>
        {value}
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{detail}</p>
    </div>
  )
}

function TelemetryHint({
  description,
  icon,
  title,
}: {
  title: string
  description: string
  icon?: ReactNode
}) {
  return (
    <div className="station-chip rounded-[24px] p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">
        {icon ?? <RotateCcw className="h-4 w-4 text-accent" />}
        {title}
      </div>
      <p className="text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  )
}
