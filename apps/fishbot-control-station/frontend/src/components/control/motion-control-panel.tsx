import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, CircleStop, Keyboard, Pause, Radio, TriangleAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'
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
const directionLabels: Record<string, string> = { forward: '前进', backward: '后退', left: '左转', right: '右转' }

export function MotionControlPanel() {
  const { activeDirection, begin, emergencyStop, stop } = useTeleopControl()
  const { angularSpeed, controlFeedback, linearSpeed, setAngularSpeed, setLinearSpeed } = useStationStore()

  return (
    <section className="station-section station-motion" aria-label="手动控制">
      <div className="station-section-heading">
        <div><h2><CircleStop size={17} />手动控制</h2><p>按住行驶，松手即停</p></div>
        <Button size="sm" variant="emergency" onClick={() => void emergencyStop()} className="gap-1.5"><TriangleAlert size={14} />软件停止锁定</Button>
      </div>
      <div className="station-control-layout">
        <div>
          <div className="station-direction-pad">
            {motionButtons.map((button) => (
              <Button key={button.direction} type="button" aria-label={button.label}
                className={`station-console-button ${activeDirection === button.direction ? 'station-console-button-active' : ''} ${button.className}`}
                variant="ghost" onPointerCancel={() => void stop()} onPointerDown={() => void begin(button.direction)}
                onPointerLeave={() => void stop()} onPointerUp={() => void stop()}>
                <button.icon size={18} /><span>{button.label}</span><small>{button.hint}</small>
              </Button>
            ))}
            <Button type="button" className="station-pad-stop col-start-2 row-start-2" variant="outline" onClick={() => void stop()}><Pause size={17} /><span>停止</span></Button>
          </div>
          <p className="station-pad-caption"><Keyboard size={12} />WASD / 方向键 · 空格停车</p>
        </div>
        <div className="station-control-settings">
          <Slider label="线速度" max={1.2} min={0.05} onChange={setLinearSpeed} value={linearSpeed} suffix=" m/s" />
          <Slider label="角速度" max={2.4} min={0.05} onChange={setAngularSpeed} value={angularSpeed} suffix=" rad/s" />
          <div className="station-control-current"><span>当前指令</span><strong>{activeDirection ? directionLabels[activeDirection] ?? activeDirection : '待命'}</strong><span>发送间隔 {controlFeedback.holdCadenceMs} ms</span></div>
        </div>
      </div>
      <div className="station-ack"><Radio size={13} /><div><span>最近回执</span><div>{controlFeedback.lastAckMessage}</div><time>{controlFeedback.lastAckAt ?? '尚未收到控制回执'}</time></div></div>
      <details className="station-details"><summary>键盘与停止说明</summary><p>方向键和 WASD 按住持续发指令；松开、窗口失焦或切走页面时停车。软件停止会锁定本控制台并重复发零速，检查后重启控制台解锁；它无法排除 Nav2 等其他发布源，不能替代硬件急停。</p><p>{controlFeedback.releaseToZeroArmed ? '松手回零已启用。' : '当前无挂起运动方向。'}{controlFeedback.throttleActive ? '重复发送节流生效。' : ''}</p></details>
    </section>
  )
}
