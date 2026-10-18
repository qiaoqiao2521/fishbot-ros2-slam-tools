import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, CircleStop, Keyboard, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ManualController, manualAdmissionMessage, manualIdleRecoveryMessage, manualResetBlockReason, type ManualDirection } from '@/lib/manual-control'
import './leased-motion.css'

const directions = [
  { id: 'forward', label: '前进', key: 'W / ↑', Icon: ArrowUp, className: 'col-start-2 row-start-1' },
  { id: 'left', label: '左转', key: 'A / ←', Icon: ArrowLeft, className: 'col-start-1 row-start-2' },
  { id: 'right', label: '右转', key: 'D / →', Icon: ArrowRight, className: 'col-start-3 row-start-2' },
  { id: 'backward', label: '后退', key: 'S / ↓', Icon: ArrowDown, className: 'col-start-2 row-start-3' },
] as const
const keys: Record<string, ManualDirection> = { KeyW: 'forward', ArrowUp: 'forward', KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right', KeyS: 'backward', ArrowDown: 'backward' }
function typing(target: EventTarget | null) { return target instanceof HTMLElement && !!target.closest('input:not([type="checkbox"]),textarea,select,[contenteditable="true"]') }

export function ManualStopButton({ controller, enabled }: { controller: ManualController; enabled: boolean }) {
  const value = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot)
  if (!enabled) return null
  return <Button size="sm" variant="emergency" disabled={!value.status?.can_stop || value.pending === 'stop'} onClick={() => void controller.stop()} aria-label="停止当前执行器"><CircleStop size={15} />停止</Button>
}

export function LeasedMotionPanel({ controller, enabled }: { controller: ManualController; enabled: boolean }) {
  const value = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot)
  const panel = useRef<HTMLElement>(null), heldKey = useRef<string | null>(null)
  const [keyboard, setKeyboard] = useState(false), [linear, setLinear] = useState(.04), [angular, setAngular] = useState(.15)
  const canBegin = enabled && controller.canBegin()
  const resetBlocked = manualResetBlockReason(value)
  const idleRecovery = manualIdleRecoveryMessage(value.status)
  useEffect(() => {
    const release = () => { heldKey.current = null; void controller.release() }
    const hidden = () => { if (document.hidden) release() }
    const keydown = (event: KeyboardEvent) => {
      if (!keyboard || !enabled || event.ctrlKey || event.metaKey || event.altKey || typing(event.target) || !panel.current?.contains(document.activeElement)) return
      if (event.code === 'Space') {
        if (event.target instanceof HTMLInputElement && event.target.type === 'checkbox') return
        event.preventDefault(); release(); void controller.stop(); return
      }
      const direction = keys[event.code]
      if (!direction || event.repeat) return
      event.preventDefault()
      if (heldKey.current) { release(); return }
      heldKey.current = event.code; void controller.begin(direction, linear, angular)
    }
    const keyup = (event: KeyboardEvent) => { if (event.code === heldKey.current) { event.preventDefault(); release() } }
    window.addEventListener('blur', release); window.addEventListener('pointerup', release); window.addEventListener('pointercancel', release)
    document.addEventListener('visibilitychange', hidden); window.addEventListener('keydown', keydown); window.addEventListener('keyup', keyup)
    return () => {
      window.removeEventListener('blur', release); window.removeEventListener('pointerup', release); window.removeEventListener('pointercancel', release)
      document.removeEventListener('visibilitychange', hidden); window.removeEventListener('keydown', keydown); window.removeEventListener('keyup', keyup); release()
    }
  }, [controller, enabled, keyboard, linear, angular])
  return <section ref={panel} tabIndex={0} className="station-section station-motion leased-motion" aria-label="低速人工控制"
    onBlur={event => {
      if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return
      heldKey.current = null; void controller.release()
    }}>
    <div className="station-section-heading"><div><h2><CircleStop size={17} />低速人工控制</h2><p>按住行驶 · 松手撤销控制权</p></div><ManualStopButton controller={controller} enabled={enabled} /></div>
    {!enabled && <p role="status">当前执行器未启用人工控制。请启动带速度仲裁与碰撞监测的仿真实例。</p>}
    {enabled && <>
      <div className="station-control-layout"><div>
        <div className="station-direction-pad">{directions.map(({ id, label, key, Icon, className }) => <Button key={id} variant="ghost" aria-label={`按住${label}`} disabled={!canBegin && value.direction !== id}
          className={`station-console-button ${className} ${value.direction === id ? 'station-console-button-active' : ''}`}
          onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); panel.current?.focus({ preventScroll: true }); void controller.begin(id, linear, angular) }}
          onPointerUp={() => void controller.release()} onPointerCancel={() => void controller.release()} onLostPointerCapture={() => void controller.release()}>
          <Icon size={18} /><span>{label}</span><small>{key}</small>
        </Button>)}<Button className="station-pad-stop col-start-2 row-start-2" variant="outline" onClick={() => void controller.release()}>松手停车</Button></div>
        <label className="leased-keyboard"><input type="checkbox" checked={keyboard} onChange={event => setKeyboard(event.target.checked)} /><Keyboard size={13} />启用键盘（焦点留在本面板）</label>
      </div><div className="station-control-settings">
        <label>前进速度 <output>{linear.toFixed(2)} m/s</output><input aria-label="人工线速度" type="range" min="0.01" max={value.status?.limits.forward_mps ?? .08} step="0.01" value={linear} disabled={!!value.direction} onChange={event => setLinear(Number(event.target.value))} /></label>
        <label>转弯速度 <output>{angular.toFixed(2)} rad/s</output><input aria-label="人工角速度" type="range" min="0.05" max={value.status?.limits.angular_rps ?? .25} step="0.05" value={angular} disabled={!!value.direction} onChange={event => setAngular(Number(event.target.value))} /></label>
        <p>后退上限 {value.status?.limits.reverse_mps ?? .03} m/s</p>
        <p role="status">{manualAdmissionMessage(value.status)}</p>
        {idleRecovery && <p role="status">{idleRecovery}</p>}
      </div></div>
      <p role="status">{value.message}</p>{value.error && <p role="alert" className="leased-error">{value.error}</p>}
      <div className="leased-evidence"><span>接纳：{value.lease?.state ?? value.stop?.state ?? '尚无请求'}</span><span>守卫停车：{(value.stop?.guard_stop_acknowledged ?? value.lease?.guard_stop_acknowledged) === true ? '已确认' : '未确认'}</span><span>连续静止：{(value.stop?.quiet ?? value.lease?.quiet ?? value.status?.quiet)?.confirmed ? '已确认' : '未确认'}</span></div>
      {value.status?.stop_latched && <div><Button variant="outline" size="sm" disabled={resetBlocked !== null} onClick={() => void controller.reset()}><RotateCcw size={14} />解除本次停车锁</Button>
        {resetBlocked && <p role="status">{resetBlocked}</p>}</div>}
      <details className="station-details"><summary>控制与停车证据</summary><p>只有原生任务结束且车辆停稳后，才接纳新的人工控制。失联后命令到期，恢复连接只读取原回执。解除停车锁不会恢复行驶。</p><p>原控制：{value.lease?.lease_id ?? '无'} · 原停车：{value.stop?.request_id ?? '无'}</p></details>
    </>}
  </section>
}
